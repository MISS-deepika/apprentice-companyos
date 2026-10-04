"""Full autonomous agent: observe -> decide -> (policy gate) -> act -> observe ... until finish."""
from agent.browser import StepError
from agent.permissions import check


def _fmt(step):
    t = step.get("target")
    if step["do"] == "goto":
        return f"open {step['url']}"
    if step["do"] == "type":
        return f"type '{step['value']}' into {t['role']} '{t['name']}'"
    return f"click {t['role']} '{t['name']}'"


def run_agent(task, browser, llm, emit, max_steps=15, passport=None):
    """Each model reply may carry up to 4 actions (a batch). A batch stops at the first block or error,
    then the loop re-observes the page. This keeps model calls (cost and rate limits) low."""
    history, trace, notes, errors = [], [], [], 0
    start_url = browser.path()
    for _ in range(max_steps):
        snap = browser.snapshot()
        d = llm.decide(task, snap, history, notes)
        batch = d["actions"][:4] if isinstance(d.get("actions"), list) and d["actions"] else [d]
        for a in batch:
            if a.get("note"):
                notes.append(a["note"]); emit("info", f"Remembered: {a['note']}")
            if a.get("action") == "finish":
                return {"status": a.get("status", "failed"), "summary": a.get("summary", ""),
                        "params": a.get("params") or {}, "skill_name": a.get("skill_name"), "trace": trace, "start_url": start_url}
            step = {"do": a.get("action"), **{k: a[k] for k in ("url", "target", "value") if k in a}}
            verdict = check(step, browser.path(), passport)
            if verdict:
                emit("permission" if verdict["kind"] == "permission" else "security", f"BLOCKED: {_fmt(step)} - {verdict['reason']}")
                history.append({"step": step, "result": "BLOCKED: " + verdict["reason"]})
                if verdict["kind"] == "permission":   # not allowed to do this: stop and escalate, never retry around it
                    return {"status": "needs_human", "summary": verdict["reason"] + ". Escalating.", "params": {},
                            "trace": trace, "start_url": start_url, "denied": verdict["capability"]}
                break
            try:
                browser.act(step)
                after = browser.snapshot()
                trace.append({**step, "status_text": after["status"]})
                history.append({"step": step, "result": "ok" + (f" - page says: {after['status']}" if after["status"] else "")})
                emit("step", _fmt(step) + (f"  ->  \"{after['status']}\"" if after["status"] else ""))
                errors = 0
            except StepError as e:
                errors += 1
                history.append({"step": step, "result": f"ERROR: {e}"})
                emit("error", f"{_fmt(step)} failed: {e}")
                if errors >= 3:
                    return {"status": "failed", "summary": "too many consecutive errors", "params": {}, "trace": trace}
                break
    return {"status": "failed", "summary": "step limit reached", "params": {}, "trace": trace}
