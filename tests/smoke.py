"""End-to-end API test: start a session, chat (incl. help and Turkish), end, wait for the report.

Usage: uv run tests/smoke.py
Needs Ollama running with the configured chat and analysis models. Uses a temp DB.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.harness import test_server  # noqa: E402

MESSAGES = [
    "Sorry, the demo is not ready, we have problem with payment API.",
    "I think I need two more day, maybe Monday is ok?",
    "Help.",
    "Müşteriye nasıl söylerim bilmiyorum.",
    "I wanted to give you a heads-up, I will send update tomorrow.",
]


def main() -> int:
    failures = []
    with test_server() as (base, log):
        c = httpx.Client(base_url=base, timeout=120)
        s = c.post("/api/session", json={"scenario": "upwork-delay"}).json()
        sid = s["session_id"]
        print("opening:", s["opening"], "| warm-up:", [w["phrase"] for w in s["warmup"]])
        if not s["warmup"]:
            failures.append("no warm-up phrases on the first session")
        for m in MESSAGES:
            t0 = time.perf_counter()
            reply = c.post(f"/api/session/{sid}/message", json={"text": m, "response_ms": 5000}).text
            print(f"USER: {m}\nCOACH ({time.perf_counter() - t0:.2f}s): {reply}")
            if not reply.strip() or "[error" in reply:
                failures.append(f"bad reply to {m!r}")
        c.post(f"/api/session/{sid}/end")
        rep = {"ready": False}
        for _ in range(120):
            rep = c.get(f"/api/session/{sid}/report").json()
            if rep["ready"]:
                break
            time.sleep(3)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if not rep["ready"]:
            failures.append("report not ready after 6 minutes")
        else:
            r, m = rep["report"], rep["metrics"]
            user_lines = " ".join(MESSAGES[:2] + MESSAGES[4:]).lower()
            if m["help_count"] != 1:
                failures.append(f"help_count={m['help_count']}, expected 1")
            if m["turkish_turns"] + m["mixed_turns"] != 1:
                failures.append("Turkish turn not detected")
            for e in r.get("errors", []):
                if e["original"].lower().strip(" .") not in user_lines:
                    failures.append(f"error quotes a non-English or help turn: {e['original']!r}")
        if "Traceback" in log.read_text():
            failures.append("server log has a traceback")
    print("\nFAIL:\n- " + "\n- ".join(failures) if failures else "\nPASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
