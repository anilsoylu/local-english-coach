"""Instagram import on the made-up export in examples/: parsing without a model, then a full import
with the local models into a temporary database and personal folder.

Usage: docker compose --profile test run --rm test python tests/instagram-test.py
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
TMP = Path(tempfile.mkdtemp(prefix="coach-ig-"))
ENV = {**os.environ, "COACH_DB": str(TMP / "test.db"), "COACH_PERSONAL": str(TMP / "personal"), "COACH_USER": "test"}
os.environ.update(ENV)  # before importing coach, which reads its paths at import time
shutil.copytree(ROOT / "examples" / "instagram-export", TMP / "personal" / "instagram")
sys.path.insert(0, str(ROOT))

from coach import instagram, prompts  # noqa: E402

FRIEND_THREAD = "1000000000000001"


def parsing() -> list[str]:
    failures = []
    dirs = instagram.thread_dirs()
    if len(dirs) != 2:
        failures.append(f"found {len(dirs)} threads, expected 2")
    if (me := instagram.owner_name()) != "Deniz Example":
        failures.append(f"owner detected as {me!r}")
    _, msgs = instagram.read_thread(instagram.find_thread(FRIEND_THREAD))
    texts = [t for _, t in msgs]
    if not any("Çeşme" in t for t in texts) or not any("😄" in t for t in texts):
        failures.append("Latin-1 escaped UTF-8 not decoded")
    if any("Liked a message" in t or "sent an attachment" in t or "shared a post" in t for t in texts):
        failures.append("Instagram notices or shares were kept")
    if texts[0] != "Hey! How was your week?":
        failures.append("messages not in time order")
    mine = instagram.learner_lines(msgs, "Deniz Example")
    if len(mine) != 5 or any("Hafta sonu" in t for t in mine):
        failures.append(f"learner lines wrong ({len(mine)}): Turkish and one-word lines must be skipped")
    if any(s == "Deniz Example" for s, t in msgs if t in instagram.other_lines(msgs, "Deniz Example")):
        failures.append("other_lines includes the learner")
    return failures


def full_import() -> list[str]:
    failures = []
    run = subprocess.run([sys.executable, "-m", "coach.instagram", "import", FRIEND_THREAD], cwd=ROOT, env=ENV,
                         capture_output=True, text=True, timeout=900)
    print(run.stdout, run.stderr[-2000:])
    if run.returncode:
        return [f"import exited with {run.returncode}"]
    counts = json.loads(run.stdout.strip().splitlines()[-1])
    if counts["learner_lines"] != 5 or not counts["persona"]:
        failures.append(f"unexpected counts {counts}")
    persona = (TMP / "personal" / "friend-persona.json").read_text()
    if "Example" in persona or "Friend" in json.loads(persona)["style"].split()[:1]:
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
