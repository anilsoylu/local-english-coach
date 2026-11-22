"""Text chat server. Run: python -m coach (host/port from config.yaml)"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from coach import config, languages, memory
from coach.analyze import analyze_session, retry_pending
from coach.prompts import PROMPT_VERSION, opening, scenario_text, system_prompt

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = config.OLLAMA_URL
CHAT_MODEL = config.CHAT_MODEL
USER_ID = config.USER_ID
OPTIONS = {"num_ctx": 8192, "num_predict": 150, "temperature": 0.7}
MAX_TURNS_IN_CONTEXT = 40
ERROR_MARK = "\n[error: "  # the UI looks for this in the stream
SCENARIOS = {s["id"]: s for s in yaml.safe_load((ROOT / "scenarios.yaml").read_text())}
# Seed phrase -> its meanings by language, so warm-up shows a seed in the current native language even when it was
# stored under another one.
SEED_MEANINGS = {c["phrase"]: c.get("meaning", "") for s in SCENARIOS.values() for c in s.get("chunks", [])}

log = logging.getLogger("coach")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def warm_up(http: httpx.AsyncClient) -> None:
    """Load the chat model, retrying until Ollama answers (it can still be starting after a reboot).
    An empty chat request loads the model: https://docs.ollama.com/faq.md"""
    delay = 1
    while True:
        try:
            r = await http.post(f"{OLLAMA}/api/chat",
                                json={"model": CHAT_MODEL, "messages": [], "keep_alive": config.KEEP_ALIVE}, timeout=300)
            r.raise_for_status()
            log.info("model %s loaded", CHAT_MODEL)
            return
        except Exception as e:
            log.warning("warm-up failed (%s), retrying in %ss", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One client for the app's lifetime so connections to Ollama are reused: https://www.python-httpx.org/async/
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5)) as http:
        app.state.http = http
        app.state.warming = None
        retry_pending()  # sessions that ended while the server was down
        yield
        if app.state.warming:
            app.state.warming.cancel()


app = FastAPI(lifespan=lifespan)


class StartBody(BaseModel):
    scenario: str


class ProfileBody(BaseModel):
    native_language: str


class MessageBody(BaseModel):
    text: str = Field(max_length=2000)
    response_ms: int | None = None


@app.post("/api/warm")
async def warm(request: Request) -> dict:
    """Called when the page opens or comes back into view, so the model is in VRAM before the first message.
    One load at a time; the request returns at once."""
    state = request.app.state
    if not state.warming or state.warming.done():
        state.warming = asyncio.create_task(warm_up(state.http))
    return {"ok": True}


@app.get("/api/languages")
def native_languages() -> list[dict]:
    return languages.listing()


@app.get("/api/profile")
def profile() -> dict:
    """native_language is '' until the learner picks one; the UI shows onboarding then."""
    return {"native_language": memory.get_profile(memory.connect(), USER_ID)["native_language"]}


@app.put("/api/profile")
def set_profile(body: ProfileBody) -> dict:
    if body.native_language not in languages.LANGUAGES:
        raise HTTPException(400, "unknown language")
    db = memory.connect()
    memory.get_profile(db, USER_ID)  # creates the row on first use
    with db:
        db.execute("UPDATE profile SET native_language=? WHERE user_id=?", (body.native_language, USER_ID))
    return {"native_language": body.native_language}


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    native = memory.get_profile(memory.connect(), USER_ID)["native_language"]
    return [{"id": s["id"], "title": languages.pick(s["title"], native)} for s in SCENARIOS.values()]


@app.post("/api/session")
def start(body: StartBody) -> dict:
    sc = SCENARIOS.get(body.scenario)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    db = memory.connect()
    with db:
        prof = memory.get_profile(db, USER_ID)
        native = prof["native_language"]
        for c in sc.get("chunks", []):
            memory.upsert_chunk(db, USER_ID, c["phrase"], languages.pick(c.get("meaning", ""), native), due_in_days=0)
        due = memory.due_chunks(db, USER_ID)
        sysmsg = system_prompt(
            name=prof["name"], level=prof["level"], profile=prof["about"], scenario=scenario_text(sc, prof["name"]),
            chunks=[c["phrase"] for c in due], last_summary=prof["last_summary"], native=native,
        )
        cur = db.execute(
            "INSERT INTO sessions(user_id, scenario, model, prompt_version, system_prompt, offered_chunks, started_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (USER_ID, sc["id"], CHAT_MODEL, PROMPT_VERSION, sysmsg, json.dumps([c["id"] for c in due]), memory.now()),
        )
        sid = cur.lastrowid
        db.execute("INSERT INTO turns(session_id, role, content, created_at) VALUES (?,?,?,?)",
                   (sid, "assistant", opening(sc, prof["name"]), memory.now()))
    return {
        "session_id": sid,
        "opening": opening(sc, prof["name"]),
        "warmup": [{"phrase": c["phrase"],
                    "meaning": languages.pick(SEED_MEANINGS.get(c["phrase"], c["meaning"]), native)} for c in due],
    }


def build_messages(db, sid: int) -> list[dict]:
    s = db.execute("SELECT system_prompt FROM sessions WHERE id=?", (sid,)).fetchone()
    turns = db.execute("SELECT role, content FROM turns WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    turns = turns[:1] + turns[1:][-MAX_TURNS_IN_CONTEXT:]  # keep the opening line, then a sliding window
    return [{"role": "system", "content": s["system_prompt"]}] + [dict(t) for t in turns]


@app.get("/api/session/{sid}")
def session(sid: int) -> dict:
    """Everything the UI needs to pick a session up again after a reload or a laptop sleep."""
    db = memory.connect()
    s = db.execute("SELECT scenario, ended_at FROM sessions WHERE id=? AND user_id=?", (sid, USER_ID)).fetchone()
    if not s:
        raise HTTPException(404)
    turns = db.execute("SELECT role, content, is_help FROM turns WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return {"scenario": s["scenario"], "ended": bool(s["ended_at"]), "turns": [dict(t) for t in turns]}


@app.post("/api/session/{sid}/message")
async def message(sid: int, body: MessageBody, request: Request) -> StreamingResponse:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty")
    db = memory.connect()
    s = db.execute("SELECT ended_at FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s or s["ended_at"]:
        raise HTTPException(409, "session not active")
    lang = memory.detect_lang(text, memory.get_profile(db, USER_ID)["native_language"])
    with db:
        turn_id = db.execute(
            "INSERT INTO turns(session_id, role, content, lang, is_help, response_ms, created_at) VALUES (?,?,?,?,?,?,?)",
            (sid, "user", text, lang, int(memory.is_help(text)), body.response_ms, memory.now()),
        ).lastrowid
    messages = build_messages(db, sid)
    db.close()
    http: httpx.AsyncClient = request.app.state.http

    async def gen():
        parts: list[str] = []
        t0 = time.perf_counter()
        ttft = None
        final: dict = {}
        payload = {"model": CHAT_MODEL, "messages": messages, "stream": True, "think": False, "options": OPTIONS,
                   "keep_alive": config.KEEP_ALIVE}
        try:
            async with http.stream("POST", f"{OLLAMA}/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        ttft = ttft or time.perf_counter() - t0
                        parts.append(piece)
                        yield piece
                    if chunk.get("done"):
                        final = chunk
        except Exception as e:
            log.exception("ollama error")
            # Drop the learner's turn too, so a retry doesn't leave two user turns in a row in the context.
            db2 = memory.connect()
            with db2:
                db2.execute("DELETE FROM turns WHERE id=?", (turn_id,))
            db2.close()
            yield f"{ERROR_MARK}{e}]"
            return
        reply = "".join(parts).strip()
        db2 = memory.connect()
        with db2:
            db2.execute("INSERT INTO turns(session_id, role, content, created_at) VALUES (?,?,?,?)",
                        (sid, "assistant", reply, memory.now()))
        db2.close()
        log.info("turn sid=%s ttft=%.2fs total=%.2fs prompt=%s cached=%s out=%s",
                 sid, ttft or 0, time.perf_counter() - t0, final.get("prompt_eval_count"),
                 final.get("prompt_eval_cached_count"), final.get("eval_count"))

    # Not text/plain, plus no-transform: Cloudflare can buffer or compress plain-text streams, which would hold
    # the reply back until it is complete. https://developers.cloudflare.com/rules/configuration-rules/response-body-inspection/
    return StreamingResponse(gen(), media_type="application/octet-stream",
                             headers={"Cache-Control": "no-cache, no-transform"})


@app.post("/api/session/{sid}/end")
def end(sid: int, tasks: BackgroundTasks) -> dict:
    db = memory.connect()
    with db:
        n = db.execute("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL", (memory.now(), sid)).rowcount
    if n:
        tasks.add_task(analyze_session, sid)
    return {"ok": True}


@app.get("/api/session/{sid}/report")
def report(sid: int) -> dict:
    db = memory.connect()
    s = db.execute("SELECT analyzed_at, metrics, report FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        raise HTTPException(404)
    if not s["analyzed_at"]:
        return {"ready": False}
    return {"ready": True, "metrics": json.loads(s["metrics"] or "{}"), "report": json.loads(s["report"] or "{}")}


@app.get("/api/progress")
def progress() -> list[dict]:
    db = memory.connect()
    rows = db.execute(
        "SELECT id, scenario, started_at, metrics FROM sessions WHERE user_id=? AND analyzed_at IS NOT NULL ORDER BY id",
        (USER_ID,),
    ).fetchall()
    return [{"id": r["id"], "scenario": r["scenario"], "date": r["started_at"][:10], **json.loads(r["metrics"] or "{}")}
            for r in rows]


class WebFiles(StaticFiles):
    """The Next.js static export. Hashed files under _next/static never change, so browsers keep them for a
    year; HTML and everything else revalidates on each load (a cheap 304 via ETag) so a deploy shows up at once.
    https://nextjs.org/docs/app/guides/static-exports"""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        res = super().file_response(full_path, stat_result, scope, status_code)
        immutable = scope["path"].startswith("/_next/static/")
        res.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return res


# Mounted last so every /api route above wins. Without a build (python -m coach during API work) the API still runs.
if config.WEB_DIR.is_dir():
    app.mount("/", WebFiles(directory=config.WEB_DIR, html=True), name="web")
else:
    log.warning("no web build in %s: run `bun run build` in frontend/", config.WEB_DIR)
