"""Learn from real chat exports, using local models only.

    python -m coach.chats threads            # list conversations: id, format, message count
    python -m coach.chats import ID          # analyze one of them (--me NAME if you aren't detected)

Put exports anywhere under data/personal/chats/ (gitignored). examples/chats/ shows each format with
made-up messages:
  instagram   Instagram or Facebook Messenger "Download your information", Messages, JSON
  whatsapp    WhatsApp "Export chat" _chat.txt (iPhone or Android layout)
  telegram    Telegram Desktop "Export chat history", JSON (one chat or all chats)
  text        any .txt with one "Name: message" per line
Nothing here runs unless that folder exists. From the learner's own English messages it adds recurring errors
to the profile and useful phrases to spaced repetition. From the other person's messages it writes a short style
note (no names or identifying details) that the friend-chat scenario uses. Message text never leaves the
machine and is never printed; the commands print ids and counts only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from coach import config, languages, memory
from coach.analyze import analysis_slot, call_model, clean_report

CHATS_DIR = config.PERSONAL_DIR / "chats"
BATCH = 60  # learner lines per analysis call; fits the 16k context with room for the answer
# Each batch takes ~25 s on the reference GPU, so a long chat is sampled instead of read in full:
# 1200 lines = 20 batches, enough for the errors that repeat.
LEARNER_SAMPLE = 1200
STYLE_SAMPLE = 300  # the other person's lines used for the style note

# Notices the apps write themselves, not something a person typed.
SYSTEM_TEXT = re.compile(
    r"^(liked a message|reacted .{1,8} to your message|.{0,60}sent an attachment\.|.{0,60}sent a voice message\.|"
    r".{0,60}started a video chat\.?|.{0,60}video chat ended\.?|.{0,60}unsent a message\.?|"
    r"<media omitted>|(image|video|audio|sticker|gif|document) omitted|<attached: .*>|this message was deleted\.?|"
    r"you deleted this message\.?|null|<this message was edited>|messages and calls are end-to-end encrypted.*|"
    r"missed (voice|video) call.*)$",
    re.I,
)
# WhatsApp: "[20.11.26, 14:03:12] Name: text" (iPhone) or "20/11/2026, 14:03 - Name: text" (Android).
WHATSAPP_LINE = re.compile(
    r"^\[?(\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),? (\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s?[APap]\.?[Mm]\.?)?)\]?(?: -)? "
    r"([^:]{1,60}): (.*)$"
)
PLAIN_LINE = re.compile(r"^([^:\[\]]{1,60}): (.+)$")
INVISIBLE = re.compile(r"[\u200e\u200f\u202a-\u202e\ufeff]")

Messages = list[tuple[str, str]]  # (sender, text) in time order


LEARNER_SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array", "maxItems": 6,
            "items": {"type": "object", "properties": {
                "kind": {"type": "string"}, "original": {"type": "string"},
                "better": {"type": "string"}, "note": {"type": "string"},
            }, "required": ["kind", "original", "better", "note"]},
        },
        "chunks": {
            "type": "array", "maxItems": 5,
            "items": {"type": "object", "properties": {
                "phrase": {"type": "string"}, "meaning": {"type": "string"}, "example": {"type": "string"},
            }, "required": ["phrase", "meaning", "example"]},
        },
        "recurring_errors": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
    },
    "required": ["errors", "chunks", "recurring_errors"],
}

LEARNER_PROMPT = """\
These are English chat messages that {name}, {speaker} (about {level}), wrote to a friend on Instagram. \
Only {name}'s lines are shown, one per line.

Previously known recurring errors: {recurring}
Phrases {name} already practices (don't suggest these): {known}

Messages:
{lines}

Return JSON with:
- errors: up to 6 mistakes that repeat or hurt understanding. Quote the original exactly, give the corrected \
sentence and one short sentence in simple {language} saying what to say instead ("say Y instead of X"), without \
grammar terms, addressing {name} informally in the second person.
- chunks: up to 5 natural spoken phrases {name} needed in these chats but didn't use. Meaning in simple {language}, \
example in English.
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
    """Instagram and Messenger write UTF-8 bytes as Latin-1 escapes ("Ã§" for "ç"). Undo it; leave clean text alone."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def keep(text: str) -> bool:
    return bool(text) and not SYSTEM_TEXT.match(text)


@dataclass
class Chat:
    id: str
    kind: str
    read: callable  # () -> (participants, messages)


def read_meta_folder(folder: Path) -> tuple[list[str], Messages]:
    """Instagram / Messenger: message_1.json, message_2.json ... newest first, media and shares as extra keys."""
    participants: list[str] = []
    rows: list[tuple[int, str, str]] = []
    for f in sorted(folder.glob("message_*.json")):
        data = json.loads(f.read_text())
        participants = participants or [fix_text(p["name"]) for p in data.get("participants", [])]
        for m in data.get("messages", []):
            text = fix_text(m.get("content") or "").strip()
            if keep(text) and not any(k in m for k in ("share", "photos", "videos", "audio_files", "gifs", "sticker")):
                rows.append((m.get("timestamp_ms", 0), fix_text(m.get("sender_name", "")), text))
    rows.sort()
    return participants, [(s, t) for _, s, t in rows]


def read_telegram_chat(chat: dict) -> tuple[list[str], Messages]:
    """Telegram: "text" is a string or a list of strings and {"type", "text"} entities."""
    msgs = []
    for m in chat.get("messages", []):
        if m.get("type") != "message" or not m.get("from") or "media_type" in m or "photo" in m:
            continue
        raw = m.get("text", "")
        text = (raw if isinstance(raw, str) else "".join(x if isinstance(x, str) else x.get("text", "") for x in raw)).strip()
        if keep(text):
            msgs.append((m["from"], text))
    return sorted({s for s, _ in msgs}), msgs


def read_lines(path: Path, pattern: re.Pattern, sender_group: int) -> tuple[list[str], Messages]:
    """WhatsApp and plain text: a line matching the pattern starts a message, other lines continue it."""
    msgs: list[list[str]] = []
    for line in INVISIBLE.sub("", path.read_text(errors="replace")).splitlines():
        if m := pattern.match(line):
            msgs.append([m.group(sender_group).strip(), m.group(sender_group + 1).strip()])
        elif msgs and line.strip():
            msgs[-1][1] += "\n" + line.strip()
    out = [(s, t) for s, t in msgs if keep(t)]
    return sorted({s for s, _ in out}), out


def short_id(path: Path, root: Path) -> str:
    return hashlib.sha1(str(path.relative_to(root)).encode()).hexdigest()[:8]


def find_chats(root: Path = CHATS_DIR) -> list[Chat]:
    """Every conversation under root, whatever app exported it. Ids avoid names: folder and file names hold them."""
    chats = []
    for folder in sorted({p.parent for p in root.glob("**/message_*.json")}):
        m = re.search(r"_(\d+)$", folder.name)
        chats.append(Chat(m.group(1) if m else short_id(folder, root), "instagram",
                          lambda f=folder: read_meta_folder(f)))
    for f in sorted(root.glob("**/result.json")):
        data = json.loads(f.read_text())
        for chat in data.get("chats", {}).get("list", []) or [data]:
            if isinstance(chat.get("messages"), list):
                chats.append(Chat(str(chat.get("id") or short_id(f, root)), "telegram",
                                  lambda c=chat: read_telegram_chat(c)))
    for f in sorted(root.glob("**/*.txt")):
        head = INVISIBLE.sub("", f.read_text(errors="replace")[:4000]).splitlines()
        whatsapp = any(WHATSAPP_LINE.match(line) for line in head)
        pattern, group = (WHATSAPP_LINE, 3) if whatsapp else (PLAIN_LINE, 1)
        chats.append(Chat(short_id(f, root), "whatsapp" if whatsapp else "text",
                          lambda f=f, p=pattern, g=group: read_lines(f, p, g)))
    return chats


def owner_name(chats: list[Chat]) -> str | None:
    """The learner is the one participant present in more conversations than anyone else."""
    counts = Counter(p for c in chats for p in set(c.read()[0]))
    if not counts:
        return None
    (top, n), *rest = counts.most_common()
    return top if not rest or rest[0][1] < n else None


def find_chat(key: str, chats: list[Chat]) -> Chat:
    matches = [c for c in chats if c.id == key]
    if len(matches) != 1:
        sys.exit(f"{len(matches)} conversations match {key!r}; run `python -m coach.chats threads`")
    return matches[0]


def spread(lines: list[str], n: int) -> list[str]:
    """At most n lines, taken evenly from the whole conversation rather than just its start."""
    return lines if len(lines) <= n else [lines[i * len(lines) // n] for i in range(n)]


def learner_lines(messages: list[tuple[str, str]], me: str, native: str) -> list[str]:
    """The learner's English messages with at least three words; native-language lines teach nothing here."""
    return spread([t for s, t in messages if s == me and len(t.split()) >= 3 and memory.detect_lang(t, native) == "en"],
                  LEARNER_SAMPLE)


def other_lines(messages: list[tuple[str, str]], me: str) -> list[str]:
    return spread([t for s, t in messages if s != me and len(t.split()) >= 2], STYLE_SAMPLE)


def import_chat(chat: Chat, me: str) -> dict:
    """Run both analyses and store the results. Returns counts only."""
    db = memory.connect()
    prof = memory.get_profile(db, config.USER_ID, {"name": config.LEARNER_NAME, "level": config.LEARNER_LEVEL,
                                                   "about": config.LEARNER_ABOUT})
    native = prof["native_language"]
    _, messages = chat.read()
    mine, theirs = learner_lines(messages, me, native), other_lines(messages, me)
    known = [r["phrase"] for r in db.execute("SELECT phrase FROM chunks WHERE user_id=?", (config.USER_ID,))]
    recurring, errors, chunks = prof["recurring_errors"], [], []
    with analysis_slot():
        for i in range(0, len(mine), BATCH):
            batch = mine[i:i + BATCH]
            rep = call_model(LEARNER_PROMPT.format(
                name=prof["name"] or "the learner", speaker=languages.speaker(native),
                language=languages.english_name(native), level=prof["level"],
                recurring=", ".join(recurring) or "none yet",
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
            memory.upsert_chunk(db, config.USER_ID, c["phrase"], c["meaning"], c["example"], due_in_days=0)
        db.execute("UPDATE profile SET recurring_errors=? WHERE user_id=?", (json.dumps(recurring), config.USER_ID))
    config.PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    (config.PERSONAL_DIR / f"findings-{chat.id}.json").write_text(json.dumps(errors, ensure_ascii=False, indent=1))
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
    imp.add_argument("id")
    imp.add_argument("--me", help="your name as it appears in the export (detected when omitted)")
    args = ap.parse_args()
    chats = find_chats() if CHATS_DIR.exists() else []
    if not chats:
        sys.exit(f"no chat exports in {CHATS_DIR}")
    if args.cmd == "threads":
        for c in chats:
            print(c.id, c.kind, len(c.read()[1]))
        return
    me = args.me or owner_name(chats)
    if not me:
        sys.exit("couldn't tell which participant is you; pass --me")
    print(json.dumps(import_chat(find_chat(args.id, chats), me)))


if __name__ == "__main__":
    main()
