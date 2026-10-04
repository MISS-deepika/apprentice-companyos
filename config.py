"""Shared paths and company-policy constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BRANCHES = DATA / "branches"
EVIDENCE = DATA / "evidence"
SKILLS = ROOT / "skills"
MAIN_DB = DATA / "main.db"
METRICS = DATA / "metrics.jsonl"
AUDIT = DATA / "audit.jsonl"

APPROVAL_LIMIT = 50_000   # payments above this need explicit human approval (policy rule 2)
BUDGET = 500_000          # max total scheduled payments (invariant)

for d in (DATA, BRANCHES, EVIDENCE, SKILLS):
    d.mkdir(parents=True, exist_ok=True)
