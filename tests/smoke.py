"""End-to-end API test: native language profile, start a session, chat (incl. help and Turkish), end, wait for the
report; then a Spanish turn, a database from before native languages, Ollama down, and the past sessions list with
"Generate report" (no model: a fake Ollama that answers slowly with an error).

Usage: uv run tests/smoke.py
Needs Ollama running with the configured chat and analysis models. Uses a temp DB.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach import memory  # noqa: E402
from tests.harness import test_server  # noqa: E402

LAUNCH_LANGUAGES = {"en", "tr", "es", "pt-BR", "de", "fr", "it", "pl", "ru", "ja", "ko", "zh"}

MESSAGES = [
    "Sorry, the demo is not ready, we have problem with payment API.",
    "I think I need two more day, maybe Monday is ok?",
    "Help.",
    "Müşteriye nasıl söylerim bilmiyorum.",
    "I wanted to give you a heads-up, I will send update tomorrow.",
]


def ollama_down() -> list[str]:
    """Ollama unreachable: the server still starts at once, a failed reply leaves no dangling user turn, and a session
    the learner never wrote in still ends and gets its metrics without a model."""
    failures = []
    t0 = time.perf_counter()
    with test_server(port=8798, OLLAMA_URL="http://127.0.0.1:9") as (base, _):
        if (ready := time.perf_counter() - t0) > 10:
            failures.append(f"server took {ready:.1f}s to start with Ollama down")
        c = httpx.Client(base_url=base, timeout=30)
        sid = c.post("/api/session", json={"scenario": "smalltalk"}).json()["session_id"]
        if c.post(f"/api/session/{sid}/message", json={"text": "x" * 2001}).status_code != 422:
            failures.append("message over 2000 chars accepted")
        reply = c.post(f"/api/session/{sid}/message", json={"text": "I go to beach."}).text
        if "[error: " not in reply:
            failures.append(f"no error marker with Ollama down: {reply!r}")
        if [t["role"] for t in c.get(f"/api/session/{sid}").json()["turns"]] != ["assistant"]:
            failures.append("failed turn was kept")
        c.post(f"/api/session/{sid}/end")
        if c.post(f"/api/session/{sid}/end").json() != {"ok": True}:
            failures.append("ending an ended session failed")
        if c.post(f"/api/session/{sid}/message", json={"text": "Hello."}).status_code != 409:
            failures.append("ended session accepted a message")
        rep = wait_report(c, sid, tries=20, wait=0.5)
        if not rep["ready"] or rep["report"] != {} or rep["metrics"]["user_turns"] != 0:
            failures.append(f"session without learner turns not analyzed in code: {rep}")
    print("ollama-down checks:", "ok" if not failures else failures)
    return failures


def wait_report(c: httpx.Client, sid: int, tries: int = 120, wait: float = 3) -> dict:
    """Polls for up to 6 minutes by default, like the UI."""
    rep = {"ready": False}
    for _ in range(tries):
        rep = c.get(f"/api/session/{sid}/report").json()
        if rep["ready"]:
            break
        time.sleep(wait)
    return rep


def stale_session() -> list[str]:
    """A session left open (tab closed without End) whose last turn is older than two hours: the next server start
    ends it and analyzes it."""
    failures = []
    db_path = Path(tempfile.mkdtemp(prefix="coach-stale-db-")) / "stale.db"
    db = sqlite3.connect(db_path)
    db.executescript(memory.SCHEMA)
    db.execute("INSERT INTO profile(user_id, name, level, about, native_language) VALUES ('test', '', 'A2', '', 'en')")
    db.execute("INSERT INTO sessions(id, user_id, scenario, model, prompt_version, system_prompt, started_at)"
               " VALUES (1, 'test', 'smalltalk', 'm', 'v5', '', '2020-01-01T10:00:00')")
    db.execute("INSERT INTO turns(session_id, role, content, created_at) VALUES (1, 'assistant', 'Hi', '2020-01-01T10:00:00')")
    db.commit()
    db.close()
    with test_server(port=8796, OLLAMA_URL="http://127.0.0.1:9", COACH_DB=str(db_path)) as (base, _):
        c = httpx.Client(base_url=base, timeout=30)
        if not c.get("/api/session/1").json()["ended"]:
            failures.append("stale session not ended on start")
        metrics = {"user_turns": 0, "avg_words": 0, "long_turn_pct": 0, "median_response_s": None, "native_turns": 0,
                   "mixed_turns": 0, "help_count": 0, "chunks_offered": 0, "chunks_used": []}
        if (rep := wait_report(c, 1, tries=20, wait=0.5)) != {"ready": True, "metrics": metrics, "report": {}}:
            failures.append(f"stale session not analyzed on start: {rep}")
    print("stale-session checks:", "ok" if not failures else failures)
    return failures


def new_db(prefix: str) -> tuple[Path, sqlite3.Connection]:
    """A database built with the app's schema before the server starts, for states the API can't create quickly."""
    db_path = Path(tempfile.mkdtemp(prefix=prefix)) / "test.db"
    db = sqlite3.connect(db_path)
    db.executescript(memory.SCHEMA)
    return db_path, db


@contextmanager
def slow_ollama(delay: float = 5):
    """Answers every request with a 500 after `delay` seconds, so an analysis stays running long enough to be asked
    for again, then fails without a model."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            time.sleep(delay)
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def past_sessions() -> list[str]:
    """GET /api/sessions (paging, order, empty sessions left out, titles in the native language, counts) and
    "Generate report" through POST /end: never two jobs for one session, never a second analysis of an analyzed one,
    and a failed analysis can be asked for again."""
    failures = []
    db_path, db = new_db("coach-history-")
    db.execute("INSERT INTO profile(user_id, name, level, about, native_language) VALUES ('test', '', 'A2', '', 'tr')")
    recent = datetime.now().isoformat(timespec="seconds")

    def session(sid: int, user_turns: int, ended: bool = True, report: dict | None = None, at: str = recent) -> None:
        db.execute("INSERT INTO sessions(id, user_id, scenario, model, prompt_version, system_prompt, started_at,"
                   " ended_at, analyzed_at, metrics, report)"
                   " VALUES (?, 'test', 'smalltalk', 'm', 'v', '', ?, ?, ?, ?, ?)",
                   (sid, f"2026-01-{sid:02d}T10:00:00", at if ended else None, at if report is not None else None,
                    "{}" if report is not None else None, json.dumps(report) if report is not None else None))
        turn = "INSERT INTO turns(session_id, role, content, lang, created_at) VALUES (?, ?, ?, 'en', ?)"
        db.execute(turn, (sid, "assistant", "Hi", at))
        for _ in range(user_turns):
            db.execute(turn, (sid, "user", "I go.", at))

    for sid in range(1, 13):  # analyzed, sid % 3 errors each
        session(sid, user_turns=2, report={"errors": [{"original": "I go."}] * (sid % 3)})
    session(13, user_turns=0, report={})  # no learner turns: not listed
    session(14, user_turns=3)  # ended, analysis failed earlier: retried at server start
    session(15, user_turns=1, ended=False)  # abandoned, too short for the model
    session(16, user_turns=2, ended=False)  # abandoned, needs the model
    # 16 was offered a phrase the learner used and one that was deleted since: both count as offered, one as used.
    db.execute("INSERT INTO chunks(id, user_id, phrase, due_date) VALUES (1, 'test', 'I go.', '2026-01-01')")
    db.execute("UPDATE sessions SET offered_chunks='[1, 999]' WHERE id=16")
    db.commit()
    db.close()

    with slow_ollama() as ollama, test_server(port=8795, OLLAMA_URL=ollama, COACH_DB=str(db_path)) as (base, log):
        c = httpx.Client(base_url=base, timeout=30)
        page1 = c.get("/api/sessions").json()
        page2 = c.get("/api/sessions", params={"offset": 10}).json()
        ids = [r["id"] for r in page1["sessions"] + page2["sessions"]]
        if ids != [16, 15, 14, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1] or not page1["more"] or page2["more"]:
            failures.append(f"paging or order wrong: {ids}, more={page1['more']}/{page2['more']}")
        rows = {r["id"]: r for r in page1["sessions"] + page2["sessions"]}
        if rows[12]["title"] != "Sohbet (hafta sonu, yemek, planlar)" or rows[12]["scenario"] != "smalltalk":
            failures.append(f"title not in the native language: {rows[12]}")
        if not re.search(r"(Z|[+-]\d\d:\d\d)$", rows[12]["started_at"]):
            failures.append(f"started_at has no UTC offset: {rows[12]['started_at']}")
        want = {12: (2, 0, "ready"), 11: (2, 2, "ready"), 14: (3, None, "pending"), 15: (1, None, "none"),
                16: (2, None, "none")}
        got = {sid: (rows[sid]["messages"], rows[sid]["errors"], rows[sid]["report"]) for sid in want}
        if got != want:
            failures.append(f"row counts or report states wrong: {got}")
        for params in ({"limit": 0}, {"limit": 51}, {"offset": -1}, {"offset": "x"}):
            if c.get("/api/sessions", params=params).status_code != 422:
                failures.append(f"paging params accepted: {params}")
        if c.post("/api/session/999/end").status_code != 404:
            failures.append("ending an unknown session did not 404")
        if c.get("/api/session/16/report").json() != {"ready": False, "pending": False}:
            failures.append("an abandoned session reports a pending analysis")

        # 14 is being analyzed (startup retry); 16 is asked for three times in a row.
        for sid in (14, 16, 16, 16):
            if c.post(f"/api/session/{sid}/end").json() != {"ok": True}:
                failures.append(f"POST /end {sid} failed")
        rep16 = c.get("/api/session/16/report").json()
        if not rep16["pending"]:
            failures.append("Generate report did not queue the analysis")
        # The metrics need no model: they are there while the analysis is still running.
        m = rep16.get("metrics") or {}
        if rep16["ready"] or (m.get("user_turns"), m.get("chunks_offered"), m.get("chunks_used")) != (2, 2, ["I go."]):
            failures.append(f"metrics not returned while the report is pending: {rep16}")
        if (c.get("/api/session/14/report").json().get("metrics") or {}).get("user_turns") != 3:
            failures.append("the startup retry did not store the metrics")
        for _ in range(80):  # two failed jobs, each a slow analysis call plus a slow chat-model reload
            if not c.get("/api/session/16/report").json()["pending"]:
                break
            time.sleep(0.5)
        text = log.read_text()
        for sid in (14, 16):
            if (n := text.count(f"analyzing session {sid} ")) != 1:
                failures.append(f"session {sid} analyzed {n} times at once, expected 1")
        rows = {r["id"]: r for r in c.get("/api/sessions").json()["sessions"]}
        if (rows[14]["report"], rows[16]["report"]) != ("none", "none"):
            failures.append(f"failed analyses don't offer a retry: {rows[14]['report']}, {rows[16]['report']}")
        c.post("/api/session/16/end")  # a retry after a failure runs again
        time.sleep(0.5)
        if log.read_text().count("analyzing session 16 ") != 2:
            failures.append("a failed analysis could not be asked for again")

        # 15 has one learner turn: ended and analyzed in code. Asking again changes nothing.
        c.post("/api/session/15/end")
        if not (rep := wait_report(c, 15, tries=40, wait=0.5))["ready"] or rep["report"] != {}:
            failures.append(f"Generate report on an abandoned session gave no report: {rep}")
        def analyzed_at() -> list:
            return sqlite3.connect(db_path).execute("SELECT analyzed_at FROM sessions WHERE id IN (1, 15)").fetchall()

        before = analyzed_at()
        c.post("/api/session/15/end")
        c.post("/api/session/1/end")
        if c.get("/api/session/1/report").json().get("pending") is not None:
            failures.append("an analyzed session reports pending")
        time.sleep(1)
        if analyzed_at() != before:
            failures.append("an analyzed session was analyzed again")
        if c.post("/api/session/15/message", json={"text": "Hello."}).status_code != 409:
            failures.append("a session ended by Generate report accepted a message")
    print("past-sessions checks:", "ok" if not failures else failures)
    return failures


def native_language(c: httpx.Client) -> list[str]:
    """Languages list, profile GET/PUT, and scenario titles that follow the profile with English as the fallback."""
    failures = []
    langs = c.get("/api/languages").json()
    if langs[0]["code"] != "en" or {lang["code"] for lang in langs} != LAUNCH_LANGUAGES:
        failures.append(f"languages list wrong: {[lang['code'] for lang in langs]}")
    if any(not lang["name"] or not lang["english_name"] for lang in langs):
        failures.append("a language has no name")

    def title() -> str:
        return next(s["title"] for s in c.get("/api/scenarios").json() if s["id"] == "smalltalk")

    if c.get("/api/profile").json() != {"native_language": ""}:
        failures.append("new profile has a native language")
    if title() != "Small talk (weekend, food, plans)":
        failures.append(f"title without a native language is not English: {title()!r}")
    if c.put("/api/profile", json={"native_language": "xx"}).status_code != 400:
        failures.append("unknown native language accepted")
    if c.put("/api/profile", json={"native_language": "es"}).json() != {"native_language": "es"}:
        failures.append("PUT /api/profile did not return the profile")
    if title() != "Charla informal (fin de semana, comida, planes)":
        failures.append(f"title not in Spanish: {title()!r}")
    c.put("/api/profile", json={"native_language": "tr"})
    if c.get("/api/profile").json() != {"native_language": "tr"}:
        failures.append("native language not stored")
    if title() != "Sohbet (hafta sonu, yemek, planlar)":
        failures.append(f"title not in Turkish: {title()!r}")
    print("native-language checks:", "ok" if not failures else failures)
    return failures


def spanish_turn(c: httpx.Client, db: Path) -> list[str]:
    """A Spanish learner stuck mid-chat: the turn is stored as native, warm-up meanings are in Spanish."""
    failures = []
    c.put("/api/profile", json={"native_language": "es"})
    s = c.post("/api/session", json={"scenario": "smalltalk"}).json()
    meanings = {w["phrase"]: w["meaning"] for w in s["warmup"]}
    if meanings.get("To be honest, ...", "Sinceramente, ...") != "Sinceramente, ...":
        failures.append(f"warm-up meaning not in Spanish: {meanings}")
    reply = c.post(f"/api/session/{s['session_id']}/message", json={"text": "No sé cómo decirlo en inglés."}).text
    print(f"USER (es): No sé cómo decirlo en inglés.\nCOACH: {reply}")
    lang = sqlite3.connect(db).execute("SELECT lang FROM turns WHERE session_id=? AND role='user'",
                                       (s["session_id"],)).fetchone()
    if lang != ("native",):
        failures.append(f"Spanish turn stored as {lang}")
    c.post(f"/api/session/{s['session_id']}/end")
    print("spanish-turn checks:", "ok" if not failures else failures)
    return failures


def old_database() -> list[str]:
    """A database from before native languages: the learner keeps Turkish, Turkish turns become native, and stored
    reports come back with the new key names. A migration that fails partway (a report with invalid JSON) leaves the
    database untouched, so the next start migrates it fully."""
    failures = []
    db_path = Path(tempfile.mkdtemp(prefix="coach-old-db-")) / "old.db"
    db = sqlite3.connect(db_path)
    db.executescript(memory.SCHEMA.replace(",\n  native_language TEXT NOT NULL DEFAULT ''", ""))
    old_report = {"errors": [{"kind": "tense", "original": "I go", "better": "I went", "note_tr": "x"}],
                  "chunks": [{"phrase": "p", "meaning_tr": "m", "example": "e"}], "feedback_tr": "f"}
    db.execute("INSERT INTO profile(user_id, name, level, about) VALUES ('test', '', 'A2', '')")
    db.execute("INSERT INTO sessions(id, user_id, scenario, model, prompt_version, system_prompt, started_at, ended_at,"
               " analyzed_at, metrics, report) VALUES (1, 'test', 'smalltalk', 'm', 'v3', '', 'x', 'x', 'x', ?, ?)",
               (json.dumps({"turkish_turns": 1}), "{not json"))
    db.execute("INSERT INTO turns(session_id, role, content, lang, created_at) VALUES (1, 'user', 'Merhaba', 'tr', 'x')")
    db.commit()
    db.row_factory = sqlite3.Row
    try:
        memory._migrate(db)
        failures.append("migration did not fail on an invalid report")
    except json.JSONDecodeError:
        pass
    if any(c["name"] == "native_language" for c in db.execute("PRAGMA table_info(profile)")):
        failures.append("failed migration left the native_language column behind")
    if db.execute("SELECT lang FROM turns").fetchone()["lang"] != "tr":
        failures.append("failed migration changed turns")
    db.execute("UPDATE sessions SET report=? WHERE id=1", (json.dumps(old_report),))
    db.commit()
    db.close()
    with test_server(port=8797, OLLAMA_URL="http://127.0.0.1:9", COACH_DB=str(db_path)) as (base, _):
        c = httpx.Client(base_url=base, timeout=30)
        rep = c.get("/api/session/1/report").json()
        want = {"errors": [{"kind": "tense", "original": "I go", "better": "I went", "note": "x"}],
                "chunks": [{"phrase": "p", "meaning": "m", "example": "e"}], "feedback": "f"}
        if rep.get("report") != want or rep.get("metrics") != {"native_turns": 1}:
            failures.append(f"old report not renamed: {rep}")
        if c.get("/api/profile").json() != {"native_language": "tr"}:
            failures.append("existing learner did not keep Turkish")
    if sqlite3.connect(db_path).execute("SELECT lang FROM turns").fetchone() != ("native",):
        failures.append("old Turkish turn not migrated")
    print("old-database checks:", "ok" if not failures else failures)
    return failures


def main() -> int:
    failures = []
    with test_server() as (base, log):
        print("temp DB:", log.parent / "test.db")
        c = httpx.Client(base_url=base, timeout=120)
        failures += native_language(c)
        s = c.post("/api/session", json={"scenario": "upwork-delay"}).json()
        sid = s["session_id"]
        print("opening:", s["opening"], "| warm-up:", [w["phrase"] for w in s["warmup"]])
        if not s["warmup"]:
            failures.append("no warm-up phrases on the first session")
        elif {"phrase": "I'll keep you posted.", "meaning": "Seni gelişmelerden haberdar ederim."} not in s["warmup"]:
            failures.append(f"warm-up meanings not in Turkish: {s['warmup']}")
        for m in MESSAGES:
            t0 = time.perf_counter()
            reply = c.post(f"/api/session/{sid}/message", json={"text": m, "response_ms": 5000}).text
            print(f"USER: {m}\nCOACH ({time.perf_counter() - t0:.2f}s): {reply}")
            if not reply.strip() or "[error" in reply:
                failures.append(f"bad reply to {m!r}")
        with c.stream("POST", f"/api/session/{sid}/message", json={"text": "Tell me more about it."}) as r:
            r.read()
            if "no-transform" not in r.headers.get("cache-control", "") or "text/plain" in r.headers["content-type"]:
                failures.append(f"stream headers let proxies buffer it: {dict(r.headers)}")
        state = c.get(f"/api/session/{sid}").json()
        if len(state["turns"]) != 3 + 2 * len(MESSAGES) or state["ended"]:
            failures.append(f"resume state wrong: {len(state['turns'])} turns, ended={state['ended']}")
        c.post(f"/api/session/{sid}/end")
        if (first := c.get(f"/api/session/{sid}/report").json())["ready"] or first["metrics"]["help_count"] != 1:
            failures.append(f"metrics not available as soon as the session ended: {first}")
        if not c.get(f"/api/session/{sid}").json()["ended"]:
            failures.append("session not marked ended")
        if c.get("/").headers.get("cache-control") != "no-cache":
            failures.append("index.html can be served stale from the browser cache")
        if c.post("/api/warm").json() != {"ok": True}:
            failures.append("warm endpoint failed")
        mf = c.get("/manifest.webmanifest")
        if mf.status_code != 200 or "manifest+json" not in mf.headers["content-type"]:
            failures.append(f"manifest not served: {mf.status_code} {mf.headers.get('content-type')}")
        rep = wait_report(c, sid)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if not rep["ready"]:
            failures.append("report not ready after 6 minutes")
        else:
            r, m = rep["report"], rep["metrics"]
            user_lines = " ".join(MESSAGES[:2] + MESSAGES[4:]).lower()
            if m["help_count"] != 1:
                failures.append(f"help_count={m['help_count']}, expected 1")
            if m["native_turns"] + m["mixed_turns"] != 1:
                failures.append("Turkish turn not detected")
            if "feedback" not in r or '_tr"' in json.dumps(r):
                failures.append("report still uses the *_tr key names")
            for e in r.get("errors", []):
                if e["original"].lower().strip(" .") not in user_lines:
                    failures.append(f"error quotes a non-English or help turn: {e['original']!r}")
        failures += spanish_turn(c, log.parent / "test.db")
        if "Traceback" in log.read_text():
            failures.append("server log has a traceback")
    failures += old_database()
    failures += ollama_down()
    failures += stale_session()
    failures += past_sessions()
    print("\nFAIL:\n- " + "\n- ".join(failures) if failures else "\nPASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
