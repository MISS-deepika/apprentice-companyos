"""The simulated company: a small finance web app the AI worker operates through a real browser.
DB_PATH selects which database (main or a branch). CHAOS=ui_shift renames the Pay button."""
import os, sqlite3
from html import escape
from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import config

DB = os.environ.get("DB_PATH", str(config.MAIN_DB))
CHAOS = os.environ.get("CHAOS", "")
app = FastAPI()


def db(sql, args=(), write=False):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute(sql, args).fetchall()
    if write:
        con.commit()
    con.close()
    return rows


def page(body):
    nav = ('<nav><a href="/invoices">Invoices</a> | <a href="/vendors">Vendors</a> | '
           '<a href="/inbox">Inbox</a> | <a href="/policy">Policy</a></nav><hr>')
    return HTMLResponse(f"<html><head><title>Company Finance</title></head><body>{nav}{body}</body></html>")


@app.get("/invoices")
def invoices(q: str = Query("", alias="q"), msg: str = ""):
    rows = db("""SELECT i.*, v.name FROM invoices i JOIN vendors v ON v.id=i.vendor_id
                 WHERE v.name LIKE ? ORDER BY i.id""", (f"%{q}%",))
    label = "Schedule Payment" if CHAOS == "ui_shift" else "Pay"
    trs = ""
    for r in rows:
        action = (f'<form method="post" action="/invoices/{r["id"]}/pay"><button type="submit">{label}</button></form>'
                  if r["status"] == "approved" else r["status"].capitalize())
        trs += (f'<tr><td>INV-{r["id"]}</td><td>{escape(r["name"])}</td><td>{r["amount"]}</td>'
                f'<td>{r["due_date"]}</td><td>{r["status"].capitalize()}</td><td>{action}</td></tr>')
    flash = f'<p role="status">{escape(msg)}</p>' if msg else ""
    return page(f"""<h1>Invoices</h1>{flash}
      <form method="get" action="/invoices"><input type="search" name="q" placeholder="Search vendor" value="{escape(q)}">
      <button type="submit">Search</button></form>
      <table border="1" cellpadding="6"><tr><th>ID</th><th>Vendor</th><th>Amount</th><th>Due</th><th>Status</th><th>Action</th></tr>{trs}</table>""")


@app.post("/invoices/{inv_id}/pay")
def pay(inv_id: int):
    r = db("SELECT * FROM invoices WHERE id=?", (inv_id,))[0]
    if r["status"] == "approved":
        db("UPDATE invoices SET status='scheduled' WHERE id=?", (inv_id,), write=True)
        db("INSERT INTO payments(invoice_id, amount, status) VALUES(?,?,'scheduled')", (inv_id, r["amount"]), write=True)
    return RedirectResponse(f"/invoices?msg=Scheduled+payment+for+INV-{inv_id}", status_code=303)


@app.get("/vendors")
def vendors():
    rows = "".join(f'<tr><td>{v["name"]}</td><td>{v["bank_account"]}</td>'
                   f'<td><a href="/vendors/{v["id"]}/edit">Edit bank details</a></td></tr>'
                   for v in db("SELECT * FROM vendors"))
    return page(f'<h1>Vendors</h1><table border="1" cellpadding="6"><tr><th>Name</th><th>Bank account</th><th></th></tr>{rows}</table>')


@app.get("/vendors/{vid}/edit")
def edit_form(vid: int):
    v = db("SELECT * FROM vendors WHERE id=?", (vid,))[0]
    return page(f'<h1>Edit {escape(v["name"])}</h1><form method="post" action="/vendors/{vid}/edit">'
                f'<input type="text" name="bank_account" aria-label="Bank account" value="{escape(v["bank_account"])}">'
                f'<button type="submit">Save bank details</button></form>')


@app.post("/vendors/{vid}/edit")
def edit_save(vid: int, bank_account: str = Form(...)):
    db("UPDATE vendors SET bank_account=? WHERE id=?", (bank_account, vid), write=True)
    return RedirectResponse("/vendors", status_code=303)


@app.get("/inbox")
def inbox():
    items = "".join(f"<h3>{escape(t['subject'])}</h3><p>{escape(t['body'])}</p>" for t in db("SELECT * FROM tickets"))
    return page(f"<h1>Inbox</h1>{items}")


@app.get("/policy")
def policy():
    return page(f"<h1>Policy</h1><pre>{escape((config.ROOT / 'company' / 'policy.md').read_text())}</pre>")
