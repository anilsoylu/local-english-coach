"""Text chat server. Run: python -m coach (host/port from config.yaml)"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from coach import config, memory
from coach.analyze import analyze_session, retry_pending
from coach.prompts import PROMPT_VERSION, opening, scenario_text, system_prompt

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = config.OLLAMA_URL
CHAT_MODEL = config.CHAT_MODEL
USER_ID = config.USER_ID
OPTIONS = {"num_ctx": 8192, "num_predict": 150, "temperature": 0.7}
MAX_TURNS_IN_CONTEXT = 40
SCENARIOS = {s["id"]: s for s in yaml.safe_load((ROOT / "scenarios.yaml").read_text())}

log = logging.getLogger("coach")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def warm_up() -> None:
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            await c.post(f"{OLLAMA}/api/chat", json={"model": CHAT_MODEL, "messages": [], "keep_alive": -1})
        log.info("model %s loaded", CHAT_MODEL)
    except Exception as e:  # server still starts; first message will load the model
        log.warning("warm-up failed: %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await warm_up()
    retry_pending()  # sessions that ended while the server was down
    yield


app = FastAPI(lifespan=lifespan)


class StartBody(BaseModel):
    scenario: str


class MessageBody(BaseModel):
    text: str
    response_ms: int | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return [{"id": s["id"], "title": s["title"]} for s in SCENARIOS.values()]


@app.post("/api/session")
def start(body: StartBody) -> dict:
    sc = SCENARIOS.get(body.scenario)
    if not sc:
        raise HTTPException(404, "unknown scenario")
    db = memory.connect()
    with db:
        prof = memory.get_profile(db, USER_ID, {"name": config.LEARNER_NAME, "level": config.LEARNER_LEVEL,
                                                "about": config.LEARNER_ABOUT})
        for c in sc.get("chunks", []):
            memory.upsert_chunk(db, USER_ID, c["phrase"], c.get("meaning", ""), due_in_days=0)
        due = memory.due_chunks(db, USER_ID)
        sysmsg = system_prompt(
            name=prof["name"], level=prof["level"], profile=prof["about"], scenario=scenario_text(sc, prof["name"]),
            chunks=[c["phrase"] for c in due], last_summary=prof["last_summary"],
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
        "warmup": [{"phrase": c["phrase"], "meaning": c["meaning"]} for c in due],
    }


def build_messages(db, sid: int) -> list[dict]:
    s = db.execute("SELECT system_prompt FROM sessions WHERE id=?", (sid,)).fetchone()
    turns = db.execute("SELECT role, content FROM turns WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    turns = turns[:1] + turns[1:][-MAX_TURNS_IN_CONTEXT:]  # keep the opening line, then a sliding window
    return [{"role": "system", "content": s["system_prompt"]}] + [dict(t) for t in turns]


@app.post("/api/session/{sid}/message")
async def message(sid: int, body: MessageBody) -> StreamingResponse:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty")
    db = memory.connect()
    s = db.execute("SELECT ended_at FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s or s["ended_at"]:
        raise HTTPException(409, "session not active")
    with db:
        db.execute(
            "INSERT INTO turns(session_id, role, content, lang, is_help, response_ms, created_at) VALUES (?,?,?,?,?,?,?)",
            (sid, "user", text, memory.detect_lang(text), int(memory.is_help(text)), body.response_ms, memory.now()),
        )
    messages = build_messages(db, sid)
    db.close()

    async def gen():
        parts: list[str] = []
        t0 = time.perf_counter()
        ttft = None
        final: dict = {}
        payload = {"model": CHAT_MODEL, "messages": messages, "stream": True, "think": False, "options": OPTIONS}
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                async with c.stream("POST", f"{OLLAMA}/api/chat", json=payload) as r:
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
            yield f"\n[error: {e}]"
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

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


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
