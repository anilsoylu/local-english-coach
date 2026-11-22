"""End-of-session analysis: metrics in code, errors/chunks/summary from the larger model (JSON schema)."""

from __future__ import annotations

import json
import logging
import statistics
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import httpx

from coach import config, languages, memory

OLLAMA = config.OLLAMA_URL
ANALYSIS_MODEL = config.ANALYSIS_MODEL
CHAT_MODEL = config.CHAT_MODEL
STALE_AFTER = timedelta(hours=2)
NUM_CTX = 16384  # a long session's transcript plus the report

log = logging.getLogger("coach.analyze")
_lock = threading.Lock()  # one analysis at a time: GPU holds one model
# Sessions waiting for or in their analysis. queue_analysis adds a session before starting its job and the job removes
# it when done, so asking again (End twice, "Generate report", the startup retry) never queues a second job for it.
_queued: set[int] = set()
_queued_lock = threading.Lock()

# One error and one chunk, as clean_report and the database expect them.
ERROR_ITEM = {"type": "object", "properties": {
    "kind": {"type": "string"},
    "original": {"type": "string"},
    "better": {"type": "string"},
    "note": {"type": "string"},
}, "required": ["kind", "original", "better", "note"]}
CHUNK_ITEM = {"type": "object", "properties": {
    "phrase": {"type": "string"},
    "meaning": {"type": "string"},
    "example": {"type": "string"},
}, "required": ["phrase", "meaning", "example"]}

SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {"type": "array", "maxItems": 4, "items": ERROR_ITEM},
        "natural": {
            "type": "array", "maxItems": 3,
            "items": {"type": "object", "properties": {
                "original": {"type": "string"},
                "natural": {"type": "string"},
            }, "required": ["original", "natural"]},
        },
        "chunks": {"type": "array", "maxItems": 3, "items": CHUNK_ITEM},
        "recurring_errors": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "level_estimate": {"type": "string", "enum": ["A2", "A2+", "B1", "B1+", "B2"]},
        "summary": {"type": "string"},
        "feedback": {"type": "string"},
    },
    "required": ["errors", "natural", "chunks", "recurring_errors", "level_estimate", "summary", "feedback"],
}

PROMPT = """\
You are reviewing an English speaking-practice chat between a coach and {name}, {speaker} (about {level}). \
The goal is fluent everyday and work English, not perfect grammar.

Previously known recurring errors: {recurring}
Phrases {name} is already practicing (don't suggest these as new chunks): {known}
Lines marked [asked for help] mean {name} was stuck and asked for a hint. The word "help" there is not part of the sentence.
{native_lines}
Transcript ({name}'s lines are marked USER):
{transcript}

Return JSON with:
- errors: the 3-4 most important mistakes in USER lines, the ones that hurt understanding or repeat. Quote the original exactly, give the corrected sentence, and a one-sentence explanation in simple {language} (note). Skip tiny slips. If a USER line is correct, don't invent errors.
- natural: up to 3 USER sentences that are correct but sound unnatural, with how a native speaker would say it in conversation.
- chunks: 2-3 useful spoken phrases for situations in this chat that {name} didn't know (not single words). Meaning in simple {language}, example in English.
- recurring_errors: updated short list (English, max 5) of error patterns that keep coming back, merging the old list with what you saw.
- level_estimate: from the USER lines.
- summary: 1 sentence in English for the coach to read next time: what {name} talked about and what to practice.
- feedback: 2 short sentences in {language}, speaking directly to {name}: \
one concrete thing that went well and one thing to focus on. Only praise what the USER lines actually show. \
Plain and specific. No praise words like "great" or "perfect", no exclamation marks, no lists, no dashes.

Only judge USER lines. Use only things that appear in the transcript. \
In every {language} field, address {name} informally in the second person, the way a friend would in {language}."""

NATIVE_LINES = "Lines marked [{language}] were written in {language} on purpose to get the English version. Don't list them as errors.\n"


def transcript(turns: list[dict], native: str) -> str:
    """USER lines carry [asked for help] or the native language's tag ("[Turkish]"), which the prompt explains."""
    native_tag = f" [{languages.english_name(native)}]"

    def line(t: dict) -> str:
        if t["role"] != "user":
            return f"COACH: {t['content']}"
        mark = " [asked for help]" if t["is_help"] else native_tag if t["lang"] in ("native", "mixed") else ""
        return f"USER{mark}: {t['content']}"

    return "\n".join(line(t) for t in turns)


def analysis_prompt(turns: list[dict], native: str, name: str, level: str, recurring: list[str],
                    known: list[str]) -> str:
    language = languages.english_name(native)
    english = languages.resolve(native) == languages.DEFAULT
    return PROMPT.format(name=name or "the learner", speaker=languages.speaker(native), level=level, language=language,
                         recurring=", ".join(recurring) or "none yet", known="; ".join(known) or "none",
                         native_lines="" if english else NATIVE_LINES.format(language=language),
                         transcript=transcript(turns, native))


def text_metrics(turns: list[dict]) -> dict:
    user = [t for t in turns if t["role"] == "user"]
    words = [len(t["content"].split()) for t in user if not t["is_help"]]
    times = [t["response_ms"] for t in user if t["response_ms"]]
    return {
        "user_turns": len(user),
        "avg_words": round(statistics.mean(words), 1) if words else 0,
        "long_turn_pct": round(100 * sum(w >= 12 for w in words) / len(words)) if words else 0,
        "median_response_s": round(statistics.median(times) / 1000, 1) if times else None,
        "native_turns": sum(t["lang"] == "native" for t in user),
        "mixed_turns": sum(t["lang"] == "mixed" for t in user),
        "help_count": sum(t["is_help"] for t in user),
    }


COMPACT = "\n\nAnswer with compact JSON on a single line, no indentation."


def call_model(prompt: str, model: str = ANALYSIS_MODEL, schema: dict = SCHEMA, stats: dict | None = None) -> dict:
    """`stats`, when given, receives Ollama's token counts and durations (bench/analysis.py prints them)."""
    body = {
        "model": model, "stream": False, "think": False, "format": schema,
        # `format` enforces the schema, so the prompt doesn't repeat it. Compact JSON: indentation was about a third of
        # the generated tokens, and generation is most of the report's wait (bench/analysis.py).
        "messages": [{"role": "user", "content": prompt + COMPACT}],
        "options": {"temperature": 0, "num_ctx": NUM_CTX}, "keep_alive": config.KEEP_ALIVE,
    }
    r = httpx.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    data = r.json()
    if stats is not None:
        stats.update({k: data.get(k) for k in ("prompt_eval_count", "eval_count", "load_duration", "total_duration")})
    return json.loads(data["message"]["content"])


def clean_report(rep: dict, turns: list[dict], known: list[str]) -> None:
    """The model doesn't reliably follow the prompt, so enforce the rules in code:
    quotes must come from normal English USER turns (not help or native-language turns, not the coach),
    no duplicates, and no 'new' chunks the learner already practices."""
    eligible = [memory.normalize(t["content"]) for t in turns
                if t["role"] == "user" and not t["is_help"] and t["lang"] == "en"]

    def from_user(quote: str) -> bool:
        q = memory.normalize(quote)
        return bool(q) and any(q in u for u in eligible)

    def dedupe(items: list[dict], key: str) -> list[dict]:
        seen, out = set(), []
        for it in items:
            k = memory.normalize(it.get(key, ""))
            if k not in seen:
                seen.add(k)
                out.append(it)
        return out

    rep["errors"] = dedupe([e for e in rep.get("errors", []) if from_user(e["original"])], "original")
    rep["natural"] = dedupe([n for n in rep.get("natural", []) if from_user(n["original"])
                             and memory.normalize(n["natural"]) != memory.normalize(n["original"])], "original")
    known_n = [memory.normalize(k) for k in known]

    def is_known(phrase: str) -> bool:  # "give you a heads-up" matches "I wanted to give you a heads-up about ..."
        p = memory.normalize(phrase)
        return any(p in k or k in p for k in known_n)

    rep["chunks"] = dedupe([c for c in rep.get("chunks", []) if not is_known(c["phrase"])], "phrase")


@contextmanager
def analysis_slot():
    """One analysis job at a time (the GPU holds one model), then the chat model is loaded again
    so the next session starts fast."""
    with _lock:
        try:
            yield
        finally:
            if ANALYSIS_MODEL != CHAT_MODEL:
                try:
                    httpx.post(f"{OLLAMA}/api/chat", json={"model": CHAT_MODEL, "messages": [],
                                                            "keep_alive": config.KEEP_ALIVE}, timeout=300)
                except Exception:
                    pass


def queue_analysis(ids: list[int]) -> None:
    """Analyzes the sessions one after another in a background thread, skipping any that already have a job queued
    or running. Jobs from different calls wait for each other on the analysis slot."""
    with _queued_lock:
        ids = [i for i in ids if i not in _queued]
        _queued.update(ids)
    if ids:
        threading.Thread(target=lambda: [analyze_session(i) for i in ids], daemon=True).start()


def is_queued(sid: int) -> bool:
    return sid in _queued


def analyze_session(sid: int) -> None:
    """One job from queue_analysis. _analyze checks analyzed_at under the slot's lock, so a session is never analyzed
    twice even when a new job is queued just after the previous one finished."""
    try:
        with analysis_slot():
            try:
                _analyze(sid)
            except Exception:
                log.exception("analysis failed for session %s (the report screen offers a retry)", sid)
    finally:
        with _queued_lock:
            _queued.discard(sid)


def _analyze(sid: int) -> None:
    db = memory.connect()
    s = dict(db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    if s["analyzed_at"]:
        return
    turns = [dict(t) for t in db.execute("SELECT * FROM turns WHERE session_id=? ORDER BY id", (sid,))]
    user_texts = [t["content"] for t in turns if t["role"] == "user"]
    metrics = text_metrics(turns)

    offered = json.loads(s["offered_chunks"])
    # Leitner reviews are written in the same transaction as analyzed_at, so a failed model call followed by a retry
    # doesn't move the phrases twice.
    reviews = []
    for cid in offered:
        row = db.execute("SELECT phrase FROM chunks WHERE id=?", (cid,)).fetchone()
        if row:
            reviews.append((cid, row["phrase"], memory.phrase_used(row["phrase"], user_texts)))
    metrics["chunks_offered"] = len(offered)
    metrics["chunks_used"] = [phrase for _, phrase, ok in reviews if ok]

    def review_chunks() -> None:
        for cid, _, ok in reviews:
            memory.review_chunk(db, cid, ok)

    if metrics["user_turns"] < 2:
        with db:
            review_chunks()
            db.execute("UPDATE sessions SET analyzed_at=?, metrics=?, report=? WHERE id=?",
                       (memory.now(), json.dumps(metrics), json.dumps({}), sid))
        return

    prof = memory.get_profile(db, s["user_id"])
    known = [r["phrase"] for r in db.execute("SELECT phrase FROM chunks WHERE user_id=?", (s["user_id"],))]
    log.info("analyzing session %s with %s (%d turns)", sid, ANALYSIS_MODEL, len(turns))
    rep = call_model(analysis_prompt(turns, prof["native_language"], prof["name"], prof["level"],
                                     prof["recurring_errors"], known))
    clean_report(rep, turns, known)

    with db:
        review_chunks()
        for e in rep["errors"]:
            db.execute("INSERT INTO errors(session_id, kind, original, better, note) VALUES (?,?,?,?,?)",
                       (sid, e["kind"], e["original"], e["better"], e["note"]))
        for c in rep.get("chunks", []):
            memory.upsert_chunk(db, s["user_id"], c["phrase"], c["meaning"], c["example"])
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
    ids = db.execute("SELECT id FROM sessions WHERE ended_at IS NOT NULL AND analyzed_at IS NULL").fetchall()
    queue_analysis([r["id"] for r in ids])
