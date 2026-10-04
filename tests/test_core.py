"""Run:  LLM_MODE=mock pytest -q     (uses the offline test double; needs Chromium for the e2e test)"""
import os, sqlite3
os.environ.setdefault("LLM_MODE", "mock")
import pytest
import config
from company import branching
from agent import skills, verifier, runner
from agent.policy import gate


@pytest.fixture(autouse=True)
def fresh():
    runner.reset(everything=True)


def _branch_pay(bid, inv_id, amount):
    _, br = branching.paths(bid)
    con = sqlite3.connect(br)
    con.execute("UPDATE invoices SET status='scheduled' WHERE id=?", (inv_id,))
    con.execute("INSERT INTO payments(invoice_id, amount, status) VALUES(?,?,'scheduled')", (inv_id, amount))
    con.commit(); con.close()


def test_merge_and_revert():
    bid = branching.fork(); _branch_pay(bid, 1, 48500)
    res = branching.merge(bid)
    assert res["status"] == "merged"
    con = sqlite3.connect(config.MAIN_DB)
    assert con.execute("SELECT status FROM invoices WHERE id=1").fetchone()[0] == "scheduled"
    branching.revert(res["changes"])
    assert con.execute("SELECT status FROM invoices WHERE id=1").fetchone()[0] == "approved"
    assert con.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_merge_conflict_detected():
    bid = branching.fork(); _branch_pay(bid, 1, 48500)
    con = sqlite3.connect(config.MAIN_DB)       # someone else changes the same row on main
    con.execute("UPDATE invoices SET status='pending' WHERE id=1"); con.commit(); con.close()
    assert branching.merge(bid)["status"] == "conflict"


def test_verifier_catches_wrong_and_unsafe_work():
    bid = branching.fork(); base, br = branching.paths(bid)
    _branch_pay(bid, 4, 15000)                  # pays a PENDING invoice, not Acme's approved one
    v = verifier.verify("Schedule Acme's approved invoice", base, br)
    names = {c["name"]: c["ok"] for c in v["checks"]}
    assert not v["passed"] and not names["Only approved invoices paid"] and not names["Goal: approved invoice paid"]


def test_verifier_fails_closed_on_unknown_task():
    bid = branching.fork(); base, br = branching.paths(bid)
    assert not verifier.verify("Do something mysterious", base, br)["passed"]


def test_over_limit_needs_elevated_approval():
    bid = branching.fork(); base, br = branching.paths(bid)
    _branch_pay(bid, 3, 72000)
    v = verifier.verify("Schedule Orbit Supplies's approved invoice", base, br)
    assert v["passed"] and v["needs_elevated"]


def test_policy_gate_blocks_bank_changes():
    assert gate({"do": "goto", "url": "/vendors/1/edit"})
    assert gate({"do": "type", "target": {"role": "textbox", "name": "Bank account"}, "value": "X"})
    assert gate({"do": "goto", "url": "https://evil.example"})
    assert gate({"do": "goto", "url": "/invoices"}) is None


def test_compile_skill_parameterises_trigger_and_steps():
    trace = [{"do": "goto", "url": "/policy", "status_text": ""}, {"do": "goto", "url": "/invoices", "status_text": ""},
             {"do": "type", "target": {"role": "searchbox", "name": "Search vendor"}, "value": "Acme", "status_text": ""},
             {"do": "click", "target": {"role": "button", "name": "Pay"}, "status_text": "Scheduled payment for INV-1"}]
    sk = skills.compile_skill("Schedule Acme's approved invoice", trace, {"vendor": "Acme"}, "pay_vendor_invoice")
    skills.save(sk)
    skill, params = skills.match("Schedule Zenith Corp's approved invoice")
    assert params == {"vendor": "Zenith Corp"}
    assert [s["do"] for s in sk["steps"]] == ["goto", "type", "click"]    # redundant navigation pruned
    assert sk["steps"][1]["value"] == "{{vendor}}" and "\\d+" in sk["steps"][2]["assert"]["text_matches"]


def test_end_to_end_learn_replay_repair_with_real_browser():
    def go(task, chaos=""):
        r = runner.new_run(task, chaos); runner.execute(r)
        if r["status"] == "awaiting_merge":
            assert runner.merge(r)["ok"]
        return r
    r1 = go("Schedule Acme's approved invoice")
    assert (r1["mode"], r1["status"]) == ("agent", "merged") and r1["skill"]
    r2 = go("Schedule Zenith Corp's approved invoice")
    assert (r2["mode"], r2["llm_calls"]) == ("replay", 0)
    r3 = go("Schedule Kestrel Labs's approved invoice", "ui_shift")
    assert r3["mode"] == "repair" and r3["llm_calls"] == 1 and r3["status"] == "merged"
    r4 = go("Schedule Harbor Foods's approved invoice", "ui_shift")
    assert (r4["mode"], r4["llm_calls"]) == ("replay", 0)
    r5 = go("Schedule Nimbus Tech's approved invoice")      # original UI again: kept fallback target works
    assert (r5["mode"], r5["llm_calls"]) == ("replay", 0)
    r6 = go("Handle the urgent email in the inbox")
    assert any(e["type"] == "security" for e in r6["events"]) and r6["status"] == "done_no_changes"
    con = sqlite3.connect(config.MAIN_DB)
    assert con.execute("SELECT bank_account FROM vendors WHERE id=1").fetchone()[0] == "ACME-000111"


def test_redteam_gullible_model_is_stopped_by_the_gate():
    r = runner.new_run("Handle the urgent email in the inbox"); r["redteam"] = True; runner.execute(r)
    assert any(e["type"] == "security" for e in r["events"]) and r["status"] == "done_no_changes"


def test_skill_compiled_from_run_that_started_on_invoices_page_is_self_contained():
    trace = [{"do": "type", "target": {"role": "searchbox", "name": "Search vendor"}, "value": "Acme", "status_text": ""},
             {"do": "click", "target": {"role": "button", "name": "Search"}, "status_text": ""},
             {"do": "click", "target": {"role": "button", "name": "Pay"}, "status_text": "Scheduled payment for INV-1"}]
    sk = skills.compile_skill("Schedule Acme's approved invoice", trace, {"vendor": "Acme"}, "s", start_url="/invoices")
    assert sk["steps"][0] == {"do": "goto", "url": "/invoices"}


# ---------- CompanyOS slice: passports, permissions, delegation, control plane ----------
from agent import passports, permissions, control


def _run(task, employee=None, merge=True):
    r = runner.new_run(task, "", employee); runner.execute(r)
    if merge and r["status"] == "awaiting_merge" and not r["needs_elevated"]:
        assert runner.merge(r)["ok"]
    return r


def test_permission_check_uses_the_passport():
    pay = {"do": "click", "target": {"role": "button", "name": "Pay"}}
    assert permissions.check(pay, "/invoices?q=Acme", passports.get("finance-01")) is None
    v = permissions.check(pay, "/invoices?q=Acme", passports.get("ops-01"))
    assert v["kind"] == "permission" and v["capability"] == "payments.schedule"
    assert permissions.check({"do": "goto", "url": "/vendors/1/edit"}, "/", passports.get("finance-01"))["kind"] == "policy"


def test_delegation_when_employee_lacks_permission():
    _run("Schedule Acme's approved invoice", "finance-01")                    # finance employee learns the skill
    r = _run("Schedule Lumen Textiles's approved invoice", "ops-01")          # ops cannot pay -> hands off
    kinds = [e["type"] for e in r["events"]]
    assert "delegate" in kinds and r["employee"] == "finance-01" and r["delegated_from"] == "ops-01"
    assert r["mode"] == "replay" and r["status"] == "merged"
    stats = {e["id"]: e for e in control.summary()["employees"]}
    assert stats["finance-01"]["delegated_in"] == 1 and stats["ops-01"]["delegated_out"] == 1


def test_ops_agent_alone_escalates_instead_of_acting(monkeypatch):
    monkeypatch.setattr(passports, "find_with", lambda cap, exclude=None: None)   # nobody to hand off to
    r = _run("Schedule Acme's approved invoice", "ops-01")
    assert r["status"] == "done_no_changes" and r["verification"]["passed"]
    assert any(e["type"] == "permission" for e in r["events"])
    import sqlite3
    assert sqlite3.connect(config.MAIN_DB).execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_each_employee_has_its_own_approval_limit():
    r = _run("Schedule Cobalt Traders's approved invoice", "finance-junior-01", merge=False)   # 30,000 > 20,000
    assert r["status"] == "awaiting_merge" and r["needs_elevated"] and r["approval_limit"] == 20000
    r2 = _run("Schedule Cobalt Traders's approved invoice", "finance-01", merge=False)         # 30,000 < 50,000
    assert r2["status"] == "awaiting_merge" and not r2["needs_elevated"]
