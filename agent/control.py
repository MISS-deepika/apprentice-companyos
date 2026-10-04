"""Control plane: per-employee numbers computed ONLY from recorded runs (metrics.jsonl) and the audit trail."""
import json
import config
from agent import passports


def _read(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def summary():
    runs, audit = _read(config.METRICS), _read(config.AUDIT)
    out = []
    for p in passports.load_all():
        mine = [r for r in runs if r.get("employee") == p["id"]]
        ev = [a for a in audit if a.get("employee") == p["id"]]
        n = len(mine)
        out.append({
            "id": p["id"], "role": p["role"], "approval_limit": p["approval_limit"],
            "tasks": n,
            "verified_pct": round(100 * sum(1 for r in mine if r["verified"]) / n) if n else None,
            "model_calls": sum(r["llm_calls"] for r in mine),
            "replays": sum(1 for r in mine if r["mode"] == "replay"),
            "repairs": sum(1 for r in mine if r["mode"] == "repair"),
            "policy_blocks": sum(1 for a in ev if a["event"] == "policy_block"),
            "permission_denials": sum(1 for a in ev if a["event"] == "permission_denied"),
            "delegated_in": sum(1 for r in mine if r.get("delegated_from")),
            "delegated_out": sum(1 for r in runs if r.get("delegated_from") == p["id"]),
        })
    return {"employees": out, "audit": audit[-12:][::-1]}
