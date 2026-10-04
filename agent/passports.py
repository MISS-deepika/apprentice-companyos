"""Employee Passports: each AI employee is a small JSON file (role, permissions, approval limit).
The SAME runtime runs every employee; only the passport differs. Passports are enforced in code."""
import json
import config

DIR = config.ROOT / "employees"
DEFAULT = "finance-01"
CAPS = {   # every capability the runtime knows, with a human label
    "invoices.read": "Read invoices", "policy.read": "Read company policy", "inbox.read": "Read the inbox",
    "vendors.read": "View vendors", "payments.schedule": "Schedule payments",
    "vendors.edit_bank": "Change vendor bank details",   # never granted: company policy rule 3
}


def load_all():
    out = []
    for p in sorted(DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    return out


def get(eid=None):
    for p in load_all():
        if p["id"] == (eid or DEFAULT):
            return p
    raise KeyError(f"unknown employee '{eid}'")


def public(p):
    return {**p, "can": [CAPS[c] for c in CAPS if c in p["permissions"]],
            "cannot": [CAPS[c] for c in CAPS if c not in p["permissions"]]}


def find_with(cap, exclude=None):
    """The employee best placed to take over work needing `cap` (highest approval limit first)."""
    cands = [p for p in load_all() if cap in p["permissions"] and p["id"] != exclude]
    return sorted(cands, key=lambda p: -p["approval_limit"])[0] if cands else None
