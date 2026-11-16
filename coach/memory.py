"""SQLite storage: sessions, turns, errors, chunks (Leitner), profile."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get("COACH_DB", Path(__file__).resolve().parent.parent / "data" / "coach.db"))

# Leitner box -> days until next review
BOX_DAYS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16, 6: 32}

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
  user_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  level TEXT NOT NULL,
  about TEXT NOT NULL,
  recurring_errors TEXT NOT NULL DEFAULT '[]',
  last_summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  user_id TEXT NOT NULL,
  scenario TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  system_prompt TEXT NOT NULL,
  offered_chunks TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  ended_at TEXT,
  analyzed_at TEXT,
  metrics TEXT,
  report TEXT
);
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  lang TEXT,
  is_help INTEGER NOT NULL DEFAULT 0,
  response_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  kind TEXT NOT NULL,
  original TEXT NOT NULL,
  better TEXT NOT NULL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  user_id TEXT NOT NULL,
  phrase TEXT NOT NULL,
  meaning TEXT,
  example TEXT,
  box INTEGER NOT NULL DEFAULT 1,
  due_date TEXT NOT NULL,
  times_used INTEGER NOT NULL DEFAULT 0,
  last_used TEXT,
  UNIQUE(user_id, phrase)
);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id);
"""

TURKISH_CHARS = re.compile(r"[çğışöüÇĞİŞÖÜ]")
TURKISH_WORDS = re.compile(
    r"\b(ve|bir|bu|şu|çok|ama|değil|nasıl|denir|yani|şey|biz|onu|bunu|için|gibi|mi|mı|ne|evet|hayır|yaptık|yaptım)\b",
    re.I,
)
HELP = re.compile(r"^\s*(help|help me|help please|yardım)\b|\bhelp\s*(please)?\s*[.!]*\s*$", re.I)


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def detect_lang(text: str) -> str:
    words = re.findall(r"\w+", text)
    if not words:
        return "en"
    tr = len(TURKISH_WORDS.findall(text)) + (2 if TURKISH_CHARS.search(text) else 0)
    if tr == 0:
        return "en"
    return "tr" if tr >= len(words) * 0.5 else "mixed"


def is_help(text: str) -> bool:
    return bool(HELP.search(text))


def get_profile(db: sqlite3.Connection, user_id: str, defaults: dict) -> dict:
    row = db.execute("SELECT * FROM profile WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO profile(user_id, name, level, about) VALUES (?,?,?,?)",
            (user_id, defaults["name"], defaults["level"], defaults["about"]),
        )
        db.commit()
        row = db.execute("SELECT * FROM profile WHERE user_id=?", (user_id,)).fetchone()
    p = dict(row)
    p["recurring_errors"] = json.loads(p["recurring_errors"])
    return p


def due_chunks(db: sqlite3.Connection, user_id: str, limit: int = 4) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM chunks WHERE user_id=? AND due_date<=? ORDER BY box, due_date LIMIT ?",
        (user_id, date.today().isoformat(), limit),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_chunk(db: sqlite3.Connection, user_id: str, phrase: str, meaning: str = "", example: str = "",
                 due_in_days: int = 1) -> None:
    db.execute(
        """INSERT INTO chunks(user_id, phrase, meaning, example, box, due_date) VALUES (?,?,?,?,1,?)
           ON CONFLICT(user_id, phrase) DO NOTHING""",
        (user_id, phrase.strip(), meaning, example, (date.today() + timedelta(days=due_in_days)).isoformat()),
    )


def review_chunk(db: sqlite3.Connection, chunk_id: int, used: bool) -> None:
    """Leitner step: used in conversation -> next box, offered but not used -> box 1."""
    row = db.execute("SELECT box, times_used FROM chunks WHERE id=?", (chunk_id,)).fetchone()
    box = min(row["box"] + 1, max(BOX_DAYS)) if used else 1
    db.execute(
        "UPDATE chunks SET box=?, due_date=?, times_used=times_used+?, last_used=COALESCE(?, last_used) WHERE id=?",
        (box, (date.today() + timedelta(days=BOX_DAYS[box])).isoformat(), int(used),
         date.today().isoformat() if used else None, chunk_id),
    )


def phrase_used(phrase: str, user_texts: list[str]) -> bool:
    """Each fragment of the phrase (split on '...') must appear in order in one user turn."""
    def norm(s: str) -> str:
        return " ".join(re.sub(r"[^\w\s']", " ", s.lower().replace("’", "'")).split())

    frags = [norm(f) for f in re.split(r"\.\.\.|…", phrase) if norm(f)]
    for t in map(norm, user_texts):
        pos = 0
        for f in frags:
            m = re.search(rf"\b{re.escape(f)}\b", t[pos:])
            if not m:
                break
            pos += m.end()
        else:
            return bool(frags)
    return False
