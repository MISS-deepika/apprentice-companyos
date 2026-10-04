"""OFFLINE TEST DOUBLE - a rule-based stand-in for the model, used only by tests/CI so the whole pipeline
(browser, gate, verifier, skills, branching) can be exercised without an API key.
It intentionally behaves like a *gullible* model on the injection email, to prove the code-level gate works.
The real submission demo uses LLM_MODE=anthropic."""
import re
from agent.tasks import parse_task


def decide(task, snap, history):
    spec = parse_task(task)
    done = [h["step"] for h in history]
    seen = lambda pred: any(pred(s) for s in done)
    last = history[-1] if history else None

    if spec["kind"] == "pay_vendor":
        if not seen(lambda s: s.get("url") == "/policy"):
            return {"action": "goto", "url": "/policy", "note": "payments over INR 50,000 need approval"}
        if not seen(lambda s: s.get("url") == "/invoices"):
            return {"action": "goto", "url": "/invoices"}
        if not seen(lambda s: s.get("do") == "type"):
            return {"action": "type", "target": {"role": "searchbox", "name": "Search vendor"}, "value": spec["vendor"]}
        if not seen(lambda s: s.get("target", {}).get("name") == "Search"):
            return {"action": "click", "target": {"role": "button", "name": "Search"}}
        if snap["status"].startswith("Scheduled payment"):
            return {"action": "finish", "status": "success", "summary": snap["status"],
                    "skill_name": "pay_vendor_invoice", "params": {"vendor": spec["vendor"]}}
        pay = [e for e in snap["elements"] if e["role"] == "button" and re.search(r"pay", e["name"], re.I)]
        if pay:
            return {"action": "click", "target": {"role": "button", "name": pay[0]["name"]}}
        return {"action": "finish", "status": "failed", "summary": "no payable invoice found", "params": {}}

    if spec["kind"] == "inbox_review":
        if not seen(lambda s: s.get("url") == "/inbox"):
            return {"action": "goto", "url": "/inbox"}
        if not seen(lambda s: "edit" in s.get("url", "")):
            return {"action": "goto", "url": "/vendors/1/edit"}   # the gullible move
        return {"action": "finish", "status": "needs_human",
                "summary": "Inbox contains an instruction to change Acme's bank details. Blocked by policy; flagged for a human.",
                "skill_name": "review_inbox", "params": {}}
    return {"action": "finish", "status": "failed", "summary": "unsupported task", "params": {}}


def repair(step, snap):
    old = step.get("target", {}).get("name", "")
    for e in snap["elements"]:
        if e["role"] == step["target"]["role"] and e["name"] != old and re.search(r"pay|schedule", e["name"], re.I):
            return {"target": {"role": e["role"], "name": e["name"]}}
    return {"target": None}
