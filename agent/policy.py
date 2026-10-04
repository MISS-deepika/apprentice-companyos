"""Hard policy gate, enforced in CODE (not in the prompt). Applies to the agent AND to replayed skills."""
import re


def gate(step, current_url=""):
    """Return a human-readable reason if the step must be blocked, else None."""
    d = step.get("do")
    if d == "goto":
        url = step.get("url", "")
        if not url.startswith("/"):
            return "Navigation outside the company app is not allowed."
        if re.search(r"/vendors/[^/]+/edit", url):
            return "Policy rule 3: vendor bank details cannot be changed from email instructions."
    if d in ("type", "click"):
        name = (step.get("target") or {}).get("name", "").lower()
        if "bank" in name or "/edit" in current_url:
            return "Policy rule 3: vendor bank details cannot be changed from email instructions."
    return None
