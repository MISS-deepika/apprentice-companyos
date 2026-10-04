"""Dashboard backend. Run via:  python start.py"""
import json, threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import config
from agent import runner, skills, passports, control

app = FastAPI(title="Apprentice")
app.mount("/evidence", StaticFiles(directory=str(config.EVIDENCE)), name="evidence")
_active = threading.Lock()


class RunReq(BaseModel):
    task: str
    chaos: str = ""
    redteam: bool = False
    employee: str = "finance-01"


class MergeReq(BaseModel):
    elevated: bool = False


class ResetReq(BaseModel):
    everything: bool = True


def _public(run):
    return {k: run[k] for k in ("id", "task", "chaos", "status", "mode", "events", "verification", "diff", "llm_calls",
                                "seconds", "skill", "needs_elevated", "summary", "screenshot", "employee", "delegated_from", "approval_limit") if k in run}


@app.get("/")
def index():
    return FileResponse(config.ROOT / "ui" / "index.html")


@app.post("/api/run")
def start(req: RunReq):
    if not req.task.strip():
        raise HTTPException(400, "task is empty")
    if not _active.acquire(blocking=False):
        raise HTTPException(409, "another run is in progress")
    run = runner.new_run(req.task.strip(), req.chaos, req.employee)
    run["redteam"] = req.redteam

    def work():
        try:
            runner.execute(run)
        finally:
            _active.release()
    threading.Thread(target=work, daemon=True).start()
    return {"id": run["id"]}


@app.get("/api/runs/{rid}")
def get_run(rid: int):
    if rid not in runner.RUNS:
        raise HTTPException(404, "no such run")
    return _public(runner.RUNS[rid])


@app.post("/api/runs/{rid}/merge")
def merge(rid: int, req: MergeReq):
    return runner.merge(runner.RUNS[rid], req.elevated)


@app.post("/api/runs/{rid}/reject")
def reject(rid: int):
    return runner.reject(runner.RUNS[rid])


@app.get("/api/metrics")
def metrics():
    if not config.METRICS.exists():
        return []
    return [json.loads(l) for l in config.METRICS.read_text().splitlines() if l.strip()]


@app.get("/api/skills")
def list_skills():
    return skills.load_all()


@app.post("/api/reset")
def reset(req: ResetReq):
    if not _active.acquire(blocking=False):
        raise HTTPException(409, "a run is in progress")
    try:
        runner.reset(req.everything)
    finally:
        _active.release()
    return {"ok": True}


@app.get("/api/main")
def main_state():
    """Live view of the MAIN database, to prove it only changes on merge."""
    import sqlite3
    con = sqlite3.connect(config.MAIN_DB); con.row_factory = sqlite3.Row
    inv = [dict(r) for r in con.execute(
        "SELECT i.id, v.name, i.amount, i.status FROM invoices i JOIN vendors v ON v.id=i.vendor_id ORDER BY i.id")]
    con.close()
    return inv


@app.get("/api/employees")
def employees():
    return [passports.public(p) for p in passports.load_all()]


@app.get("/api/control")
def control_plane():
    return control.summary()
