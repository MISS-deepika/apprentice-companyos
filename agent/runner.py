"""Orchestrates one run: fork -> (skill replay | full agent) -> independent verify -> learn -> await human merge."""
import json, socket, subprocess, sys, threading, time, urllib.request
import config
from company import branching, seed
from agent import skills, verifier, passports
from agent.browser import Browser
from agent.llm import LLM
from agent.loop import run_agent
from agent.tasks import parse_task

RUNS = {}
_lock = threading.Lock()
_counter = [0]


def new_run(task, chaos="", employee=None):
    with _lock:
        _counter[0] += 1
        rid = _counter[0]
    run = {"id": rid, "task": task, "chaos": chaos, "status": "running", "mode": None, "events": [], "t0": time.time(),
           "verification": None, "diff": [], "llm_calls": 0, "seconds": 0, "skill": None, "needs_elevated": False,
           "summary": "", "bid": None, "employee": employee or passports.DEFAULT, "delegated_from": None,
           "approval_limit": config.APPROVAL_LIMIT, "can_pay": True}
    RUNS[rid] = run
    return run


_AUDITED = {"security": "policy_block", "permission": "permission_denied", "delegate": "delegated"}


def audit(run, event, detail=""):
    with open(config.AUDIT, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "run": run["id"], "employee": run.get("employee"),
                            "event": event, "detail": detail[:200]}) + "\n")


def emit(run, kind, text):
    run["events"].append({"t": round(time.time() - run["t0"], 1), "type": kind, "text": text})
    if kind in _AUDITED:
        audit(run, _AUDITED[kind], text)


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _start_branch_server(db_path, chaos, port):
    import os
    env = {**os.environ, "DB_PATH": str(db_path), "CHAOS": chaos or ""}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "company.app:app", "--port", str(port), "--log-level", "error"],
                            cwd=str(config.ROOT), env=env)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/policy", timeout=1); return proc
        except Exception:
            time.sleep(0.25)
    proc.terminate()
    raise RuntimeError("branch company app did not start")


def execute(run):
    try:
        _execute(run)
    except Exception as e:   # surface any failure to the UI instead of dying silently
        emit(run, "error", f"Run crashed: {e}")
        run["status"] = "failed"; run["summary"] = str(e)


def _set_employee(run, emp):
    run["employee"] = emp["id"]; run["approval_limit"] = emp["approval_limit"]
    run["can_pay"] = "payments.schedule" in emp["permissions"]


def _attempt(run, emp, task, bid, browser, llm):
    """One employee's try at the task: replay a known skill if one matches, else explore with the agent."""
    say = lambda k, t: emit(run, k, t)
    outcome, mode, patched = None, "agent", None
    found = skills.match(task)
    if found:
        skill, params = found
        say("info", f"Known skill '{skill['name']}' v{skill['version']} matches {params} - replaying without the model")
        res = skills.run_skill(skill, params, browser, llm, say, emp)
        if res["ok"]:
            mode = "repair" if res["repairs"] else "replay"
            patched, outcome = res["skill"], {"status": "success", "summary": "skill replayed"}
        elif res.get("denied"):
            mode = "replay"
            outcome = {"status": "needs_human", "summary": res["error"] + ". Escalating.", "denied": res["denied"]}
        else:
            say("error", f"Skill failed at step {res['failed_step'] + 1}: {res['error']}. Falling back to the full agent on a clean branch.")
            branching.reset(bid)
            browser.page.goto(browser.base + "/invoices")
            mode = "fallback"
    if outcome is None:
        say("info", "No usable skill - the agent will explore the task from scratch")
        outcome = run_agent(task, browser, llm, say, passport=emp)
        mode = "fallback" if mode == "fallback" else "agent"
    return outcome, mode, patched


def _execute(run):
    task = run["task"]
    emp = passports.get(run.get("employee"))
    _set_employee(run, emp)
    bid = branching.fork(); run["bid"] = bid
    base, branch = branching.paths(bid)
    port = _free_port()
    proc = _start_branch_server(branch, run["chaos"], port)
    emit(run, "info", f"Employee {emp['id']} ({emp['role']}) accepted the task. Forked company database into branch {bid}" + (f" (UI variant: {run['chaos']})" if run["chaos"] else ""))
    llm, browser = (LLM(mode="mock") if run.get("redteam") else LLM()), None
    if run.get("redteam"):
        emit(run, "info", "RED-TEAM TEST: using a deliberately gullible test model that obeys injected instructions, to prove the code-level policy gate holds even when the model is fooled")
    try:
        browser = Browser(f"http://127.0.0.1:{port}")
        t0 = time.time()
        outcome, mode, patched = _attempt(run, emp, task, bid, browser, llm)
        if outcome.get("denied"):
            helper = passports.find_with(outcome["denied"], exclude=emp["id"])
            if helper:
                emit(run, "delegate", f"{emp['id']} cannot do this (needs '{outcome['denied']}'). Delegating to {helper['id']} ({helper['role']}), who holds that permission.")
                run["delegated_from"] = emp["id"]; emp = helper; _set_employee(run, emp)
                outcome, mode, patched = _attempt(run, emp, task, bid, browser, llm)
            else:
                emit(run, "info", "No employee holds that permission - escalating to a human.")
        run["seconds"] = round(time.time() - t0, 1)
        run["llm_calls"] = llm.calls
        run["mode"] = mode
        run["summary"] = outcome.get("summary", "")
        shot = config.EVIDENCE / f"{run['id']}.png"
        browser.screenshot(shot); run["screenshot"] = f"/evidence/{run['id']}.png"
    finally:
        if browser:
            browser.close()
        proc.terminate()

    v = verifier.verify(task, base, branch, outcome["status"], emp["approval_limit"], run["can_pay"])
    run["verification"] = v; run["needs_elevated"] = v["needs_elevated"]
    run["diff"] = branching.diff(base, branch)
    for c in v["checks"]:
        emit(run, "verify" if c["ok"] else ("approval" if c["level"] == "approval" else "error"), f"{'PASS' if c['ok'] else ('NEEDS APPROVAL' if c['level'] == 'approval' else 'FAIL')}: {c['name']} - {c['detail']}")
    audit(run, "verified" if v["passed"] else "verification_failed", f"mode={mode}")

    if v["passed"] and outcome["status"] == "success" and mode in ("agent", "fallback") and outcome.get("trace"):
        params = dict(outcome.get("params") or {})
        spec = parse_task(task)
        if not params and spec["kind"] == "pay_vendor":
            params = {"vendor": spec["vendor"]}   # model forgot to report parameters: use the task parser
        sk = skills.compile_skill(task, outcome["trace"], params, outcome.get("skill_name"), outcome.get("start_url"))
        if sk["steps"]:
            skills.save(sk); run["skill"] = sk["name"]
            emit(run, "learn", f"Verified run compiled into skill '{sk['name']}' ({len(sk['steps'])} steps, params: {sk['params']})")
    elif mode in ("replay", "repair") and patched and outcome["status"] == "success":
        patched["stats"]["runs"] += 1
        if v["passed"]:
            patched["stats"]["verified"] += 1
            if mode == "repair":
                patched["version"] += 1; patched["stats"]["repairs"] += 1
                emit(run, "learn", f"Repair verified - skill '{patched['name']}' updated to v{patched['version']}")
            skills.save(patched); run["skill"] = patched["name"]
        else:
            emit(run, "error", "Replay output FAILED independent verification - skill left unchanged")

    if not v["passed"]:
        run["status"] = "failed"
    elif not run["diff"]:
        run["status"] = "done_no_changes"
    else:
        run["status"] = "awaiting_merge"
    if run["status"] != "awaiting_merge":
        branching.discard(bid)
    with open(config.METRICS, "a") as f:
        f.write(json.dumps({"run": run["id"], "task": task, "mode": mode, "llm_calls": run["llm_calls"],
                            "seconds": run["seconds"], "verified": v["passed"], "chaos": run["chaos"],
                            "employee": run["employee"], "delegated_from": run["delegated_from"]}) + "\n")


def merge(run, elevated_ok=False):
    if run["status"] != "awaiting_merge":
        return {"ok": False, "error": f"run is '{run['status']}', nothing to merge"}
    if run["needs_elevated"] and not elevated_ok:
        return {"ok": False, "error": "this change includes a payment above the approval limit - explicit approval required"}
    res = branching.merge(run["bid"])
    if res["status"] == "conflict":
        run["status"] = "conflict"; emit(run, "error", "Merge conflict: main changed the same rows while the agent worked. Rerun the task.")
        branching.discard(run["bid"])
        return {"ok": False, "error": "merge conflict"}
    base, _ = branching.paths(run["bid"])
    post = verifier.verify(run["task"], base, config.MAIN_DB, "needs_human" if run["needs_elevated"] else "success", run.get("approval_limit"), run.get("can_pay", True))
    if not post["passed"]:
        branching.revert(res["changes"]); run["status"] = "reverted"
        emit(run, "error", "Post-merge verification failed - changes automatically reverted"); audit(run, "reverted")
        branching.discard(run["bid"])
        return {"ok": False, "error": "post-merge verification failed, reverted"}
    run["status"] = "merged"; emit(run, "verify", "Merged into main and re-verified against the live database"); audit(run, "merged")
    branching.discard(run["bid"])
    return {"ok": True}


def reject(run):
    if run["status"] == "awaiting_merge":
        branching.discard(run["bid"]); run["status"] = "rejected"; emit(run, "info", "Branch discarded. Main database untouched."); audit(run, "rejected")
    return {"ok": True}


def reset(everything=True):
    seed.seed()
    if everything:
        skills.clear()
        config.METRICS.unlink(missing_ok=True)
        config.AUDIT.unlink(missing_ok=True)
        RUNS.clear(); _counter[0] = 0
