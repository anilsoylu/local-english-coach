"""SQLite storage: sessions, turns, errors, chunks (Leitner), profile."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from functools import cache

from lingua import IsoCode639_1, Language, LanguageDetectorBuilder

from coach import languages
from coach.config import DB_PATH, LEARNER_ABOUT, LEARNER_LEVEL, LEARNER_NAME

# Leitner box -> days until next review
BOX_DAYS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16, 6: 32}

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
  user_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  level TEXT NOT NULL,
  about TEXT NOT NULL,
  recurring_errors TEXT NOT NULL DEFAULT '[]',
  last_summary TEXT NOT NULL DEFAULT '',
  native_language TEXT NOT NULL DEFAULT ''
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

HELP = re.compile(r"^\s*(help|help me|help please)\b|\bhelp\s*(please)?\s*[.!]*\s*$", re.I)
LETTER_WORD = re.compile(r"[^\W\d_]+")  # CJK runs without spaces count as one word
# Per-word confidence for the native language, with the detector limited to {English, native} so the two values add
# up to 1. A word "leans native" above 0.5. A message needs at least one word at 0.9 or more to count as native at
# all: short English words ("a", "I", "ok") often sit between 0.5 and 0.8 for one language or another, while real
# native words ("nasıl", "pidió", "weiß", any CJK or Cyrillic run) score 0.9 to 1.0. Then 70% leaning-native words
# make it a native message and anything less a mixed one ("It was good but el cliente pidió muchos cambios").
STRONG_NATIVE = 0.9
NATIVE_SHARE = 0.7


def _migrate(db: sqlite3.Connection) -> None:
    """Databases from before native languages: the app assumed Turkish, so those learners keep Turkish, Turkish turns
    become "native", and stored reports and metrics get the language-neutral key names."""
    if any(c["name"] == "native_language" for c in db.execute("PRAGMA table_info(profile)")):
        return
    renames = {"note_tr": "note", "meaning_tr": "meaning", "feedback_tr": "feedback", "turkish_turns": "native_turns"}

    def rename(obj):
        if isinstance(obj, dict):
            return {renames.get(k, k): rename(v) for k, v in obj.items()}
        return [rename(v) for v in obj] if isinstance(obj, list) else obj

    with db:
        # Legacy isolation mode does not open a transaction before DDL, so the ALTER would commit on its own and a
        # failed step after it would leave a half-migrated database that the column check above never retries.
        db.execute("BEGIN")
        db.execute("ALTER TABLE profile ADD COLUMN native_language TEXT NOT NULL DEFAULT ''")
        db.execute("UPDATE profile SET native_language='tr'")
        db.execute("UPDATE turns SET lang='native' WHERE lang='tr'")
        for r in db.execute("SELECT id, metrics, report FROM sessions WHERE report IS NOT NULL OR metrics IS NOT NULL"
                            ).fetchall():
            metrics, report = (r[k] and json.dumps(rename(json.loads(r[k])), ensure_ascii=False)
                               for k in ("metrics", "report"))
            db.execute("UPDATE sessions SET metrics=?, report=? WHERE id=?", (metrics, report, r["id"]))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    # Safe with WAL: no corruption, at worst the last commit is lost on power failure.
    # https://www.sqlite.org/pragma.html#pragma_synchronous
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    _migrate(db)
    return db


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@cache
def _detector(native: str):
    """Built once per native language, limited to it and English. No low-accuracy mode: it is meant for long texts
    and these messages are short. https://github.com/pemistahl/lingua-py"""
    lang = Language.from_iso_code_639_1(getattr(IsoCode639_1, native.split("-")[0].upper()))
    return lang, LanguageDetectorBuilder.from_languages(Language.ENGLISH, lang).build()


def detect_lang(text: str, native: str) -> str:
    """en / native / mixed. Capitalized words are skipped: they are names (Çeşme, Barcelona, München) or a
    sentence's first word, and a name must not turn an English sentence into a native one. English or no native
    language chosen: always en."""
    native = languages.resolve(native)
    words = [w for w in LETTER_WORD.findall(text) if not w[0].isupper()]
    if native == languages.DEFAULT or not words:
        return "en"
    lang, detector = _detector(native)
    conf = [detector.compute_language_confidence(w, lang) for w in words]
    if max(conf) < STRONG_NATIVE:
        return "en"
    return "native" if sum(c > 0.5 for c in conf) >= NATIVE_SHARE * len(conf) else "mixed"


def is_help(text: str) -> bool:
    return bool(HELP.search(text))


def get_profile(db: sqlite3.Connection, user_id: str) -> dict:
    """Creates the row on first use. name/about always follow config.yaml; level starts there and is then learned,
    like recurring errors and summary; the native language is picked in the UI ('' until then)."""
    row = db.execute("SELECT * FROM profile WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        db.execute("INSERT INTO profile(user_id, name, level, about) VALUES (?,?,?,?)",
                   (user_id, LEARNER_NAME, LEARNER_LEVEL, LEARNER_ABOUT))
        db.commit()
    elif (row["name"], row["about"]) != (LEARNER_NAME, LEARNER_ABOUT):
        db.execute("UPDATE profile SET name=?, about=? WHERE user_id=?", (LEARNER_NAME, LEARNER_ABOUT, user_id))
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


def normalize(text: str) -> str:
    """Lowercase, punctuation to spaces, single spaces. Apostrophes stay so "I'll" != "ill"."""
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower().replace("’", "'")).split())


# A fragment ending in one of these before a "..." slot matches without it:
# "a heads-up about ..." is used in "I wanted to give you a heads-up, the API is down".
SLOT_WORDS = {"about", "with", "on", "to", "for", "of", "in", "that", "if"}


def phrase_used(phrase: str, user_texts: list[str]) -> bool:
    """Each fragment of the phrase (split on '...') must appear in order in one user turn."""
    patterns = []
    for frag in filter(None, map(normalize, re.split(r"\.\.\.|…", phrase))):
        *head, last = frag.split()
        if head and last in SLOT_WORDS:
            patterns.append(rf"\b{re.escape(' '.join(head))}(?: {last})?\b")
        else:
            patterns.append(rf"\b{re.escape(frag)}\b")
    for text in map(normalize, user_texts):
        pos = 0
        for pattern in patterns:
            m = re.search(pattern, text[pos:])
            if not m:
                break
            pos += m.end()
        else:
            return bool(patterns)
    return False
