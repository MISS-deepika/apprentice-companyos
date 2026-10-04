"""Independent task understanding for the VERIFIER (deliberately separate from the agent's own reasoning)."""
import re

PAY = re.compile(r"schedule\s+(?:payment\s+for\s+)?(?P<vendor>[\w .&-]+?)(?:'s|\u2019s)?\s+approved\s+invoices?", re.I)
INBOX = re.compile(r"\b(inbox|e-?mails?|urgent)\b", re.I)


def parse_task(text):
    m = PAY.search(text)
    if m:
        return {"kind": "pay_vendor", "vendor": m.group("vendor").strip()}
    if INBOX.search(text):
        return {"kind": "inbox_review"}
    return {"kind": "unknown"}
