"""Daily SQLite backup with 14-day rotation. Cron: 30 3 * * * .venv/bin/python deploy/backup.py"""
import sqlite3
from datetime import date
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src, out = root / "data" / "coach.db", root / "backups"
out.mkdir(exist_ok=True)
if src.exists():
    with sqlite3.connect(src) as s, sqlite3.connect(out / f"coach-{date.today()}.db") as d:
        s.backup(d)
for old in sorted(out.glob("coach-*.db"))[:-14]:
    old.unlink()
