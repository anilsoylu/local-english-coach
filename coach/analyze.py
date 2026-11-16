"""End-of-session analysis: metrics in code, errors/chunks/summary from the larger model (JSON schema)."""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
from datetime import datetime, timedelta

import httpx

from coach import memory

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
ANALYSIS_MODEL = os.environ.get("COACH_ANALYSIS_MODEL", "qwen3.5:9b")
CHAT_MODEL = os.environ.get("COACH_MODEL", "qwen3.5:9b")
ANALYSIS_THINK = os.environ.get("COACH_ANALYSIS_THINK", "0") == "1"
STALE_AFTER = timedelta(hours=2)

log = logging.getLogger("coach.analyze")
_lock = threading.Lock()  # one analysis at a time: GPU holds one model

SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array", "maxItems": 4,
            "items": {"type": "object", "properties": {
                "kind": {"type": "string"},
                "original": {"type": "string"},
                "better": {"type": "string"},
                "note_tr": {"type": "string"},
            }, "required": ["kind", "original", "better", "note_tr"]},
        },
        "natural": {
            "type": "array", "maxItems": 3,
            "items": {"type": "object", "properties": {
                "original": {"type": "string"},
                "natural": {"type": "string"},
            }, "required": ["original", "natural"]},
        },
        "chunks": {
            "type": "array", "maxItems": 3,
            "items": {"type": "object", "properties": {
                "phrase": {"type": "string"},
                "meaning_tr": {"type": "string"},
                "example": {"type": "string"},
            }, "required": ["phrase", "meaning_tr", "example"]},
        },
        "recurring_errors": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "level_estimate": {"type": "string", "enum": ["A2", "A2+", "B1", "B1+", "B2"]},
        "summary": {"type": "string"},
        "feedback_tr": {"type": "string"},
    },
    "required": ["errors", "natural", "chunks", "recurring_errors", "level_estimate", "summary", "feedback_tr"],
}

PROMPT = """\
You are reviewing an English speaking-practice chat between a coach and {name}, a Turkish speaker (about {level}). \
The goal is fluent everyday and work English, not perfect grammar.

Previously known recurring errors: {recurring}
Phrases {name} is already practicing (don't suggest these as new chunks): {known}
Lines marked [asked for help] mean {name} was stuck and asked for a hint. The word "help" there is not part of the sentence.
Lines marked [Turkish] were written in Turkish on purpose to get the English version. Don't list them as errors.

Transcript ({name}'s lines are marked USER):
{transcript}

Return JSON with:
- errors: the 3-4 most important mistakes in USER lines, the ones that hurt understanding or repeat. Quote the original exactly, give the corrected sentence, and a one-sentence explanation in simple Turkish (note_tr). Skip tiny slips. If a USER line is correct, don't invent errors.
- natural: up to 3 USER sentences that are correct but sound unnatural, with how a native speaker would say it in conversation.
- chunks: 2-3 useful spoken phrases for situations in this chat that {name} didn't know (not single words). Meaning in Turkish, example in English.
- recurring_errors: updated short list (English, max 5) of error patterns that keep coming back, merging the old list with what you saw.
- level_estimate: from the USER lines.
- summary: 2 sentences in English for the coach to read next time: what {name} talked about and what to practice.
- feedback_tr: 2-3 short sentences in Turkish to {name}: one concrete thing that went well and one thing to focus on. \
Plain and specific. No praise words like "harika", "mükemmel", no exclamation marks, no lists, no dashes.

Only judge USER lines. Use only things that appear in the transcript."""


def text_metrics(turns: list[dict]) -> dict:
    user = [t for t in turns if t["role"] == "user"]
    words = [len(t["content"].split()) for t in user if not t["is_help"]]
    times = [t["response_ms"] for t in user if t["response_ms"]]
    return {
        "user_turns": len(user),
        "avg_words": round(statistics.mean(words), 1) if words else 0,
        "long_turn_pct": round(100 * sum(w >= 12 for w in words) / len(words)) if words else 0,
        "median_response_s": round(statistics.median(times) / 1000, 1) if times else None,
        "turkish_turns": sum(t["lang"] == "tr" for t in user),
        "mixed_turns": sum(t["lang"] == "mixed" for t in user),
        "help_count": sum(t["is_help"] for t in user),
    }


def call_model(prompt: str) -> dict:
    body = {
        "model": ANALYSIS_MODEL, "stream": False, "think": ANALYSIS_THINK, "format": SCHEMA,
        "messages": [{"role": "user", "content": prompt + "\n\nJSON schema:\n" + json.dumps(SCHEMA)}],
        "options": {"temperature": 0, "num_ctx": 16384},
    }
    r = httpx.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def analyze_session(sid: int) -> None:
    with _lock:
        try:
            _analyze(sid)
        except Exception:
            log.exception("analysis failed for session %s (will retry on next start)", sid)
        finally:
            if ANALYSIS_MODEL != CHAT_MODEL:  # bring the chat model back so the next session starts fast
                try:
                    httpx.post(f"{OLLAMA}/api/chat", json={"model": CHAT_MODEL, "messages": []}, timeout=300)
                except Exception:
                    pass


def _analyze(sid: int) -> None:
    db = memory.connect()
    s = dict(db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    if s["analyzed_at"]:
        return
    turns = [dict(t) for t in db.execute("SELECT * FROM turns WHERE session_id=? ORDER BY id", (sid,))]
    user_texts = [t["content"] for t in turns if t["role"] == "user"]
    metrics = text_metrics(turns)

    # Spaced repetition: offered phrases the learner actually used move up a box.
    offered = json.loads(s["offered_chunks"])
    used = []
    with db:
        for cid in offered:
            row = db.execute("SELECT phrase FROM chunks WHERE id=?", (cid,)).fetchone()
            if row:
                ok = memory.phrase_used(row["phrase"], user_texts)
                memory.review_chunk(db, cid, ok)
                if ok:
                    used.append(row["phrase"])
    metrics["chunks_offered"] = len(offered)
    metrics["chunks_used"] = used

    if metrics["user_turns"] < 2:
        with db:
            db.execute("UPDATE sessions SET analyzed_at=?, metrics=?, report=? WHERE id=?",
                       (memory.now(), json.dumps(metrics), json.dumps({}), sid))
        return

    prof = memory.get_profile(db, s["user_id"], {})
    def line(t: dict) -> str:
        if t["role"] != "user":
            return f"COACH: {t['content']}"
        tag = " [asked for help]" if t["is_help"] else " [Turkish]" if t["lang"] in ("tr", "mixed") else ""
        return f"USER{tag}: {t['content']}"

    transcript = "\n".join(line(t) for t in turns)
    known = [r["phrase"] for r in db.execute("SELECT phrase FROM chunks WHERE user_id=?", (s["user_id"],))]
    log.info("analyzing session %s with %s (%d turns)", sid, ANALYSIS_MODEL, len(turns))
    rep = call_model(PROMPT.format(name=prof["name"], level=prof["level"],
                                   recurring=", ".join(prof["recurring_errors"]) or "none yet",
                                   known="; ".join(known) or "none",
                                   transcript=transcript))
    # Drop errors whose "original" isn't in the transcript: the model must not invent quotes.
    blob = " ".join(user_texts).lower()
    rep["errors"] = [e for e in rep.get("errors", []) if e["original"].lower().strip(" .") in blob]

    with db:
        for e in rep["errors"]:
            db.execute("INSERT INTO errors(session_id, kind, original, better, note) VALUES (?,?,?,?,?)",
                       (sid, e["kind"], e["original"], e["better"], e["note_tr"]))
        for c in rep.get("chunks", []):
            memory.upsert_chunk(db, s["user_id"], c["phrase"], c["meaning_tr"], c["example"])
        db.execute("UPDATE profile SET recurring_errors=?, last_summary=?, level=? WHERE user_id=?",
                   (json.dumps(rep.get("recurring_errors", [])), rep.get("summary", ""),
                    rep.get("level_estimate", prof["level"]), s["user_id"]))
        db.execute("UPDATE sessions SET analyzed_at=?, metrics=?, report=? WHERE id=?",
                   (memory.now(), json.dumps(metrics), json.dumps(rep, ensure_ascii=False), sid))
    log.info("session %s analyzed: %d errors, %d chunks", sid, len(rep["errors"]), len(rep.get("chunks", [])))


def retry_pending() -> None:
    """On startup: close stale sessions (tab closed without 'end') and analyze anything left over."""
    db = memory.connect()
    cutoff = (datetime.now() - STALE_AFTER).isoformat(timespec="seconds")
    with db:
        db.execute(
            "UPDATE sessions SET ended_at=? WHERE ended_at IS NULL AND id IN "
            "(SELECT session_id FROM turns GROUP BY session_id HAVING MAX(created_at) < ?)",
            (memory.now(), cutoff),
        )
    ids = [r["id"] for r in db.execute("SELECT id FROM sessions WHERE ended_at IS NOT NULL AND analyzed_at IS NULL")]
    if ids:
        threading.Thread(target=lambda: [analyze_session(i) for i in ids], daemon=True).start()
