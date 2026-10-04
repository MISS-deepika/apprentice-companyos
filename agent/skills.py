"""Skill memory: compile a VERIFIED trace into a parameterised skill, replay it without the LLM,
and repair only the step that broke (semantic target swap). Skills are plain, auditable JSON."""
import json, re, time
import config
from agent.browser import StepError, render
from agent.loop import _fmt
from agent.permissions import check


def _path(name):
    return config.SKILLS / f"{name}.json"


def load_all():
    out = []
    for p in sorted(config.SKILLS.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    return out


def save(skill):
    _path(skill["name"]).write_text(json.dumps(skill, indent=2))


def clear():
    for p in config.SKILLS.glob("*.json"):
        p.unlink()


def match(task):
    for s in load_all():
        m = re.match(s["trigger"], task.strip(), re.I)
        if m:
            return s, {k: v.strip() for k, v in m.groupdict().items()}
    return None


def _template(text, params):
    for k, v in params.items():
        text = re.sub(re.escape(v), "{{%s}}" % k, text, flags=re.I)
    return text


def _generalize(text, params):
    """Turn observed confirmation text into a regex: parameters -> .+?, numbers -> \\d+."""
    esc = re.escape(text)
    for v in params.values():
        esc = re.sub(re.escape(re.escape(v)), lambda m: r".+?", esc, flags=re.I)
    return re.sub(r"\d+", lambda m: r"\d+", esc)


def compile_skill(task, trace, params, name, start_url=None):
    params = {k: v for k, v in params.items() if isinstance(v, str) and v and v.lower() in task.lower()}
    spans = sorted((task.lower().find(v.lower()), len(v), k) for k, v in params.items())
    pattern, pos = "", 0
    for idx, ln, k in spans:
        if idx < pos:
            continue
        pattern += re.escape(task[pos:idx]) + f"(?P<{k}>.+?)"
        pos = idx + ln
    trigger = "^" + pattern + re.escape(task[pos:]) + "$"

    steps = []
    for i, t in enumerate(trace):
        if t["do"] == "goto" and i + 1 < len(trace) and trace[i + 1]["do"] == "goto":
            continue   # pure navigation noise
        s = {"do": t["do"]}
        if t["do"] == "goto":
            s["url"] = _template(t["url"], params)
        else:
            s["target"] = t["target"]
        if t["do"] == "type":
            s["value"] = _template(t["value"], params)
        if t["do"] == "click" and t.get("status_text"):
            s["assert"] = {"text_matches": _generalize(t["status_text"], params)}
        steps.append(s)
    if steps and steps[0]["do"] != "goto" and start_url and start_url.startswith("/"):
        steps.insert(0, {"do": "goto", "url": start_url})   # make the skill self-contained
    name = re.sub(r"\W+", "_", name or "skill").strip("_").lower() or "skill"
    return {"name": name, "description": f"Learned from: {task}", "trigger": trigger, "params": list(params),
            "version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stats": {"runs": 1, "verified": 1, "repairs": 0}, "steps": steps}


def run_skill(skill, params, browser, llm, emit, passport=None):
    """Deterministic replay with per-step assertions. Returns the (possibly patched) skill; the caller
    only persists it after the independent verifier has passed."""
    new = json.loads(json.dumps(skill))
    repairs = 0
    for i, s in enumerate(new["steps"]):
        step = {k: render(s[k], params) for k in ("do", "url", "value") if k in s}
        cur = browser.path()
        if s.get("target"):
            candidates = [s["target"]] + s.get("alts", [])
            usable = next((t for t in candidates if browser.has(t)), None)
            err = f"No {s['target']['role']} named '{s['target']['name']}' on {cur}"
            if usable is None:
                emit("repair", f"Step {i + 1} broke: {err}. Asking the model to repair only this step.")
                fix = (llm.repair({**step, "target": s["target"]}, err, browser.snapshot(), skill["description"]) or {}).get("target")
                if not fix or not browser.has(fix):
                    return {"ok": False, "failed_step": i, "error": err, "repairs": repairs, "skill": new}
                s["alts"] = [s["target"]] + s.get("alts", [])
                s["target"], usable = fix, fix
                repairs += 1
                emit("repair", f"Repaired step {i + 1}: now uses {fix['role']} '{fix['name']}'. Old target kept as fallback.")
            step["target"] = usable
        verdict = check(step, cur, passport)
        if verdict:
            emit("permission" if verdict["kind"] == "permission" else "security", f"BLOCKED during replay: {_fmt(step)} - {verdict['reason']}")
            return {"ok": False, "failed_step": i, "error": verdict["reason"], "repairs": repairs, "skill": new,
                    "denied": verdict.get("capability")}
        try:
            browser.act(step)
            browser.check_assert(s.get("assert"), params)
        except StepError as e:
            return {"ok": False, "failed_step": i, "error": str(e), "repairs": repairs, "skill": new}
        emit("step", "replay: " + _fmt(step))
    return {"ok": True, "repairs": repairs, "skill": new}
