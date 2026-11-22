"""Chat import on the made-up exports in examples/chats/: parsing every format without a model, then a full
import with the local models into a temporary database and personal folder.

Usage: docker compose --profile test run --rm test python tests/chats-test.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="coach-chats-"))
ENV = {**os.environ, "COACH_DB": str(TMP / "test.db"), "COACH_PERSONAL": str(TMP / "personal"), "COACH_USER": "test"}
os.environ.update(ENV)  # before importing coach, which reads its paths at import time
shutil.copytree(ROOT / "examples" / "chats", TMP / "personal" / "chats")
sys.path.insert(0, str(ROOT))

from coach import chats, memory, prompts  # noqa: E402

ME = "Deniz Example"
NATIVE = "tr"  # the example exports mix English with Turkish
# id -> (kind, messages kept, learner lines) for each example file
EXPECTED = {
    "1000000000000001": ("instagram", 11, 5),
    "1000000000000002": ("instagram", 2, 1),
    "4000000001": ("telegram", 3, 1),
}
BY_KIND = {"whatsapp": [(5, 2), (3, 1)], "text": [(3, 1)]}  # file-based ids are hashes of the path


def parsing() -> list[str]:
    failures = []
    found = chats.find_chats()
    if chats.owner_name(found) != ME:
        failures.append(f"owner detected as {chats.owner_name(found)!r}")
    for c in found:
        parts, msgs = c.read()
        texts = [t for _, t in msgs]
        got = (c.kind, len(msgs), len(chats.learner_lines(msgs, ME, NATIVE)))
        want = EXPECTED.get(c.id)
        if want is None:
            want = (c.kind, *BY_KIND[c.kind].pop(0)) if BY_KIND.get(c.kind) else None
        if got != want:
            failures.append(f"{c.kind} {c.id}: (kind, messages, learner lines) = {got}, expected {want}")
        if any(chats.SYSTEM_TEXT.match(t) for t in texts) or any("omitted" in t or "encrypted" in t for t in texts):
            failures.append(f"{c.kind} {c.id}: app notices kept")
        if any("Hafta sonu" in t or t.startswith("Tamam") for t in chats.learner_lines(msgs, ME, NATIVE)):
            failures.append(f"{c.kind} {c.id}: Turkish line counted as English")
    ig = chats.find_chat("1000000000000001", found).read()[1]
    if not any("Çeşme" in t for _, t in ig) or not any("😄" in t for _, t in ig):
        failures.append("Instagram Latin-1 escaped UTF-8 not decoded")
    if ig[0][1] != "Hey! How was your week?":
        failures.append("Instagram messages not in time order")
    wa = next(c for c in found if c.kind == "whatsapp" and len(c.read()[1]) == 5).read()[1]
    if not any("\n" in t and "very good coffee" in t for _, t in wa):
        failures.append("WhatsApp multi-line message not joined")
    tg = chats.find_chat("4000000001", found).read()[1]
    if ("Deniz Example", "It is good but very stressful, I have many meeting every day.") not in tg:
        failures.append("Telegram text entities not joined")
    return failures


def full_import() -> list[str]:
    failures = []
    db = memory.connect()  # the learner picked Turkish in the UI
    memory.get_profile(db, "test", {})
    with db:
        db.execute("UPDATE profile SET native_language=? WHERE user_id='test'", (NATIVE,))
    run = subprocess.run([sys.executable, "-m", "coach.chats", "import", "1000000000000001"], cwd=ROOT, env=ENV,
                         capture_output=True, text=True, timeout=900)
    print(run.stdout, run.stderr[-2000:])
    if run.returncode:
        return [f"import exited with {run.returncode}"]
    counts = json.loads(run.stdout.strip().splitlines()[-1])
    if counts["learner_lines"] != 5 or not counts["persona"]:
        failures.append(f"unexpected counts {counts}")
    if "Example" in (TMP / "personal" / "friend-persona.json").read_text():
        failures.append("persona mentions the person's name")
    db = sqlite3.connect(TMP / "test.db")
    if db.execute("SELECT count(*) FROM chunks WHERE user_id='test'").fetchone()[0] != counts["chunks"]:
        failures.append("chunks not stored")
    if counts["errors"] == 0:
        failures.append("no errors found in lines with obvious mistakes")
    if "Chat the way this friend does" not in prompts.scenario_text(
            {"role": "a friend", "setting": "Chat.", "persona": True}, "Deniz"):
        failures.append("friend-chat scenario ignores the persona")
    return failures


def main() -> int:
    failures = parsing()
    print("parsing:", "ok" if not failures else failures)
    failures += full_import()
    print("\nFAIL:\n- " + "\n- ".join(failures) if failures else "\nPASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
