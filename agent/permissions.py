"""Maps raw browser steps to capabilities and enforces (1) company-wide policy and (2) the employee's passport."""
import re
from agent.policy import gate

_PAGES = (("/vendors", "vendors.read"), ("/invoices", "invoices.read"), ("/inbox", "inbox.read"), ("/policy", "policy.read"))


def classify(step, url=""):
    d = step.get("do")
    if d == "goto":
        u = step.get("url", "")
        if re.match(r"/vendors/[^/]+/edit", u):
            return "vendors.edit_bank"
        for prefix, cap in _PAGES:
            if u.startswith(prefix):
                return cap
        return None
    if d in ("type", "click"):
        t = step.get("target") or {}
        name = t.get("name", "").lower()
        if "bank" in name or "/edit" in url:
            return "vendors.edit_bank"
        if d == "click" and t.get("role") == "button" and re.search(r"\bpay\b|schedule payment", name):
            return "payments.schedule"
        if url.startswith("/invoices"):
            return "invoices.read"
    return None


def check(step, url="", passport=None):
    """Return None if allowed, else {'kind': 'policy'|'permission', 'reason': ..., 'capability': ...}."""
    reason = gate(step, url)
    if reason:
        return {"kind": "policy", "reason": reason}
    cap = classify(step, url)
    if passport and cap and cap not in passport["permissions"]:
        return {"kind": "permission", "capability": cap,
                "reason": f"Permission denied: {passport['id']} ({passport['role']}) does not hold '{cap}'"}
    return None
