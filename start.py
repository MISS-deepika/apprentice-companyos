"""One command to run everything:  python start.py   ->  dashboard http://localhost:8000"""
import subprocess, sys, os
import uvicorn
import config
from company import seed

if not config.MAIN_DB.exists():
    seed.seed()
env = {**os.environ, "DB_PATH": str(config.MAIN_DB), "CHAOS": ""}
company = subprocess.Popen([sys.executable, "-m", "uvicorn", "company.app:app", "--port", "8100", "--log-level", "warning"],
                           cwd=str(config.ROOT), env=env)
print("\n  Company app (main DB):  http://localhost:8100/invoices")
print("  Apprentice dashboard:   http://localhost:8000\n")
try:
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="warning")
finally:
    company.terminate()
