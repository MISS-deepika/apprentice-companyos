"""Git-style branching for the company database: fork -> (agent works) -> diff -> merge / revert.
The agent only ever touches a branch copy; main changes only through merge()."""
import shutil, sqlite3, uuid
import config

TABLES = {"vendors": "id", "invoices": "id", "payments": "id", "tickets": "id"}


def paths(bid):
    return config.BRANCHES / f"{bid}.base.db", config.BRANCHES / f"{bid}.db"


def fork():
    bid = uuid.uuid4().hex[:8]
    base, branch = paths(bid)
    shutil.copy(config.MAIN_DB, branch)   # the agent works here
    shutil.copy(config.MAIN_DB, base)     # frozen snapshot to diff against
    return bid


def reset(bid):
    base, branch = paths(bid)
    shutil.copy(base, branch)


def discard(bid):
    for p in paths(bid):
        p.unlink(missing_ok=True)


def _rows(db, table, pk):
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    rows = {r[pk]: dict(r) for r in con.execute(f"SELECT * FROM {table}")}
    con.close()
    return rows


def diff(a_db, b_db):
    out = []
    for t, pk in TABLES.items():
        a, b = _rows(a_db, t, pk), _rows(b_db, t, pk)
        for k in sorted(b.keys() - a.keys()):
            out.append({"op": "insert", "table": t, "pk": k, "after": b[k]})
        for k in sorted(a.keys() - b.keys()):
            out.append({"op": "delete", "table": t, "pk": k, "before": a[k]})
        for k in sorted(a.keys() & b.keys()):
            if a[k] != b[k]:
                out.append({"op": "update", "table": t, "pk": k, "before": a[k], "after": b[k]})
    return out


def _apply(con, c):
    t, pk = c["table"], TABLES[c["table"]]
    if c["op"] == "delete":
        con.execute(f"DELETE FROM {t} WHERE {pk}=?", (c["pk"],))
    else:
        row = c["after"]
        con.execute(f"INSERT OR REPLACE INTO {t} ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))


def _invert(c):
    if c["op"] == "insert":
        return {"op": "delete", "table": c["table"], "pk": c["pk"]}
    if c["op"] == "delete":
        return {"op": "insert", "table": c["table"], "pk": c["pk"], "after": c["before"]}
    return {"op": "update", "table": c["table"], "pk": c["pk"], "after": c["before"]}


def merge(bid):
    """Apply the branch's changes to main atomically. Refuses if main touched the same rows meanwhile."""
    base, branch = paths(bid)
    changes = diff(base, branch)
    touched = {(c["table"], c["pk"]) for c in changes}
    conflicts = [d for d in diff(base, config.MAIN_DB) if (d["table"], d["pk"]) in touched]
    if conflicts:
        return {"status": "conflict", "conflicts": conflicts, "changes": changes}
    con = sqlite3.connect(config.MAIN_DB)
    try:
        for c in changes:
            _apply(con, c)
        con.commit()
    except Exception:
        con.rollback(); raise
    finally:
        con.close()
    return {"status": "merged", "changes": changes}


def revert(changes):
    con = sqlite3.connect(config.MAIN_DB)
    for c in reversed(changes):
        _apply(con, _invert(c))
    con.commit(); con.close()
