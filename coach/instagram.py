"""Learn from a real Instagram conversation, using local models only.

    python -m coach.instagram threads              # list conversations: thread id and message count
    python -m coach.instagram import THREAD_ID     # the id from `threads` (or the folder name)

The export ("Download your information", Messages, JSON) goes in data/personal/instagram/
(examples/instagram-export/ shows the layout with made-up messages). Nothing here
runs unless that folder exists. From the learner's own English messages it adds recurring errors to the
profile and useful phrases to spaced repetition. From the other person's messages it writes a short style
note (no names or identifying details) that the friend-chat scenario uses. Message text never leaves the
machine and is never printed; the command only prints counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from coach import config, memory
from coach.analyze import analysis_slot, call_model, clean_report

EXPORT_DIR = config.PERSONAL_DIR / "instagram"
BATCH = 60  # learner lines per analysis call; fits the 16k context with room for the answer
# Each batch takes ~25 s on the reference GPU, so a long chat is sampled instead of read in full:
# 1200 lines = 20 batches, enough for the errors that repeat.
LEARNER_SAMPLE = 1200
STYLE_SAMPLE = 300  # the other person's lines used for the style note

# Instagram's own notices, not something a person typed.
SYSTEM_TEXT = re.compile(
    r"^(liked a message|reacted .{1,8} to your message|.{0,60}sent an attachment\.|.{0,60}sent a voice message\.|"
    r".{0,60}started a video chat\.?|.{0,60}video chat ended\.?|.{0,60}unsent a message\.?)$",
    re.I,
)

LEARNER_SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array", "maxItems": 6,
            "items": {"type": "object", "properties": {
                "kind": {"type": "string"}, "original": {"type": "string"},
                "better": {"type": "string"}, "note_tr": {"type": "string"},
            }, "required": ["kind", "original", "better", "note_tr"]},
        },
        "chunks": {
            "type": "array", "maxItems": 5,
            "items": {"type": "object", "properties": {
                "phrase": {"type": "string"}, "meaning_tr": {"type": "string"}, "example": {"type": "string"},
            }, "required": ["phrase", "meaning_tr", "example"]},
        },
        "recurring_errors": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    },
    "required": ["errors", "chunks", "recurring_errors"],
}

LEARNER_PROMPT = """\
These are English chat messages that {name}, a Turkish speaker (about {level}), wrote to a friend on Instagram. \
Only {name}'s lines are shown, one per line.

Previously known recurring errors: {recurring}
Phrases {name} already practices (don't suggest these): {known}

Messages:
{lines}

Return JSON with:
- errors: up to 6 mistakes that repeat or hurt understanding. Quote the original exactly, give the corrected \
sentence and one short sentence in simple Turkish saying what to say instead ("X yerine Y de"), without grammar terms.
- chunks: up to 5 natural spoken phrases {name} needed in these chats but didn't use. Meaning in Turkish, example in English.
- recurring_errors: updated short list (English, max 5) of error patterns, merging the old list with what you saw.
Skip typos and missing capital letters. Don't invent errors in correct lines."""

STYLE_SCHEMA = {
    "type": "object",
    "properties": {
        "style": {"type": "string"},
        "topics": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
    },
    "required": ["style", "topics"],
}

STYLE_PROMPT = """\
Below are chat messages one person wrote to a friend. An English tutor will play a friend with a similar \
way of chatting, so describe how this person chats, not who they are.

Messages:
{lines}

Return JSON with:
- style: at most 80 words, English, second person ("You ..."): tone, humor, how you react, what kind of \
questions you ask, message length. Describe the manner only. Never copy their spelling or grammar mistakes.
- topics: up to 8 everyday topics this person likes to talk about, 1 to 4 words each.
Never include names, usernames, ages, cities, schools, workplaces, phone numbers or anything else that could \
identify a real person."""


def fix_text(s: str) -> str:
    """Instagram writes UTF-8 bytes as Latin-1 escapes ("Ã§" for "ç"). Undo it; leave clean text alone."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def thread_dirs(root: Path = EXPORT_DIR) -> list[Path]:
    """Folders holding message_*.json, wherever the export put them (older and newer layouts differ)."""
    return sorted({p.parent for p in root.glob("**/messages/inbox/*/message_*.json")})


def read_thread(folder: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """(participants, [(sender, text), ...]) in time order, with media, shares and notices dropped."""
    participants: list[str] = []
    rows: list[tuple[int, str, str]] = []
    for f in sorted(folder.glob("message_*.json")):
        data = json.loads(f.read_text())
        participants = participants or [fix_text(p["name"]) for p in data.get("participants", [])]
        for m in data.get("messages", []):
            text = fix_text(m.get("content") or "").strip()
            if not text or SYSTEM_TEXT.match(text) or any(k in m for k in ("share", "photos", "videos", "audio_files")):
                continue
            rows.append((m.get("timestamp_ms", 0), fix_text(m.get("sender_name", "")), text))
    rows.sort()
    return participants, [(s, t) for _, s, t in rows]


def owner_name(root: Path = EXPORT_DIR) -> str | None:
    """The account owner is the one participant present in every conversation of the export."""
    counts = Counter(p for d in thread_dirs(root) for p in set(read_thread(d)[0]))
    if not counts:
        return None
    (top, n), *rest = counts.most_common()
    return top if not rest or rest[0][1] < n else None


def find_thread(key: str, root: Path = EXPORT_DIR) -> Path:
    matches = [d for d in thread_dirs(root) if d.name == key or d.name.endswith("_" + key)]
    if len(matches) != 1:
        sys.exit(f"{len(matches)} conversations match {key!r}; run `python -m coach.instagram threads`")
    return matches[0]


def spread(lines: list[str], n: int) -> list[str]:
    """At most n lines, taken evenly from the whole conversation rather than just its start."""
    return lines if len(lines) <= n else [lines[i * len(lines) // n] for i in range(n)]


def learner_lines(messages: list[tuple[str, str]], me: str) -> list[str]:
    """The learner's English messages with at least three words; Turkish lines teach nothing here."""
    return spread([t for s, t in messages if s == me and memory.detect_lang(t) == "en" and len(t.split()) >= 3],
                  LEARNER_SAMPLE)


def other_lines(messages: list[tuple[str, str]], me: str) -> list[str]:
    return spread([t for s, t in messages if s != me and len(t.split()) >= 2], STYLE_SAMPLE)


def import_thread(folder: Path, me: str) -> dict:
    """Run both analyses and store the results. Returns counts only."""
    _, messages = read_thread(folder)
    mine, theirs = learner_lines(messages, me), other_lines(messages, me)
    db = memory.connect()
    prof = memory.get_profile(db, config.USER_ID, {"name": config.LEARNER_NAME, "level": config.LEARNER_LEVEL,
                                                   "about": config.LEARNER_ABOUT})
    known = [r["phrase"] for r in db.execute("SELECT phrase FROM chunks WHERE user_id=?", (config.USER_ID,))]
    recurring, errors, chunks = prof["recurring_errors"], [], []
    with analysis_slot():
        for i in range(0, len(mine), BATCH):
            batch = mine[i:i + BATCH]
            rep = call_model(LEARNER_PROMPT.format(
                name=prof["name"] or "the learner", level=prof["level"], recurring=", ".join(recurring) or "none yet",
                known="; ".join(known + [c["phrase"] for c in chunks]) or "none", lines="\n".join(batch)),
                schema=LEARNER_SCHEMA)
            rep["natural"] = []
            # Same rules as the session report: quotes must be the learner's own lines, no known phrases.
            clean_report(rep, [{"role": "user", "content": t, "is_help": 0, "lang": "en"} for t in batch],
                         known + [c["phrase"] for c in chunks])
            errors += rep["errors"]
            chunks += rep["chunks"]
            recurring = rep.get("recurring_errors") or recurring
        persona = call_model(STYLE_PROMPT.format(lines="\n".join(theirs)), schema=STYLE_SCHEMA) if theirs else None
    with db:
        for c in chunks:
            memory.upsert_chunk(db, config.USER_ID, c["phrase"], c["meaning_tr"], c["example"], due_in_days=0)
        db.execute("UPDATE profile SET recurring_errors=? WHERE user_id=?", (json.dumps(recurring), config.USER_ID))
    config.PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    (config.PERSONAL_DIR / "instagram-findings.json").write_text(json.dumps(errors, ensure_ascii=False, indent=1))
    if persona:
        style = persona["style"].strip()
        persona["style"] = style[:style.rfind(".") + 1] or style  # the model sometimes stops mid-sentence
        config.PERSONA_PATH.write_text(json.dumps(persona, ensure_ascii=False, indent=1))
    return {"messages": len(messages), "learner_lines": len(mine), "other_lines": len(theirs),
            "errors": len(errors), "chunks": len(chunks), "recurring_errors": len(recurring),
            "persona": bool(persona)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("threads")
    imp = sub.add_parser("import")
    imp.add_argument("thread")
    imp.add_argument("--me", help="your name as it appears in the export (detected when omitted)")
    args = ap.parse_args()
    if not EXPORT_DIR.exists():
        sys.exit(f"no export in {EXPORT_DIR}")
    if args.cmd == "threads":
        for d in thread_dirs():
            print(d.name.rsplit("_", 1)[-1], len(read_thread(d)[1]))  # folder names hold usernames: id only
        return
    me = args.me or owner_name()
    if not me:
        sys.exit("couldn't tell which participant is you; pass --me")
    print(json.dumps(import_thread(find_thread(args.thread), me)))


if __name__ == "__main__":
    main()
