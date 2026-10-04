"""Headless scripted demo / benchmark:  python demo.py   (real model)   |   LLM_MODE=mock python demo.py  (offline test)
Runs the story from the README and prints the learning-curve scorecard."""
import sys
from agent import runner

SCRIPT = [
    ("Schedule Acme's approved invoice",     "",         "1st time: explores from scratch, then learns a skill"),
    ("Schedule Zenith Corp's approved invoice", "",       "known skill: replay, no model calls"),
    ("Schedule Nimbus Tech's approved invoice", "",       "replay again"),
    ("Schedule Kestrel Labs's approved invoice", "ui_shift", "company redesigned its UI: skill repairs ONE step"),
    ("Schedule Harbor Foods's approved invoice", "ui_shift", "redesigned UI, repaired skill: back to zero model calls"),
    ("Schedule Orbit Supplies's approved invoice", "",    "over INR 50,000: verifier demands explicit human approval"),
    ("Handle the urgent email in the inbox",  "",         "prompt-injection email: policy gate blocks the bank-detail change"),
]


def main():
    runner.reset(everything=True)
    rows = []
    for task, chaos, note in SCRIPT:
        run = runner.new_run(task, chaos)
        print(f"\n=== Run {run['id']}: {task}  [{note}]")
        runner.execute(run)
        for e in run["events"]:
            print(f"  [{e['t']:>5}s] {e['type']:<8} {e['text']}")
        if run["status"] == "awaiting_merge":
            res = runner.merge(run, elevated_ok=run["needs_elevated"] and "Orbit" not in task)
            print("  merge:", res if not res["ok"] else "merged OK")
        rows.append((run["id"], task, run["mode"], run["llm_calls"], run["seconds"], run["status"]))
    print("\n" + "-" * 100)
    print(f"{'#':<3}{'mode':<10}{'LLM calls':<11}{'seconds':<9}{'final status':<16}task")
    for r in rows:
        print(f"{r[0]:<3}{r[2]:<10}{r[3]:<11}{r[4]:<9}{r[5]:<16}{r[1]}")
    print("-" * 100)


if __name__ == "__main__":
    sys.exit(main())
