"""Benchmark a conversation model against fixed learner turns.

Usage: uv run bench/run.py MODEL [MODEL ...] [--runs 1]
Writes bench/results/<model>__<prompt_version>.jsonl and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from coach.prompts import PROMPT_VERSION, system_prompt  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
OPTIONS = {"num_ctx": 8192, "num_predict": 150, "temperature": 0.7}

EXPLICIT_CORRECTION = re.compile(
    r"you should say|the correct (form|way|sentence)|correct is|instead of saying|small mistake|grammar|"
    r"we say .* not |it'?s better to say|should be \"",
    re.I,
)
TURKISH = re.compile(r"[çğışöüÇĞİŞÖÜ]|\b(ve|bir|bu|çok|ama|değil|nasıl|evet|hayır)\b", re.I)
# Humanizer tells adapted for speech (spoken chunks like "The thing is" are allowed).
AI_TELLS = re.compile(
    r"great question|absolutely[!,.]|i'?d be (happy|glad) to|that'?s (amazing|fantastic|wonderful)|"
    r"\bdelve|\bcrucial\b|\bvibrant\b|\bjourney\b|\blandscape\b|\benhance|\bshowcas|\btestament\b|"
    r"not (just|only|merely) .{1,40}\bbut\b|[—–]|\*\*|^\s*[-*] |as an ai|"
    r"[\U0001F300-\U0001FAFF☀-➿]",
    re.I | re.M,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def score(case: dict, reply: str) -> dict:
    text = reply.strip()
    sentences = [s for s in SENTENCE_SPLIT.split(text) if s.strip()]
    q = text.count("?")
    checks = {
        "short": len(sentences) <= 4 and len(text.split()) <= 60,
        "one_question": q == 1 or (case["kind"] in ("turkish", "help", "unfinished") and q <= 1),
        "no_explicit_correction": not EXPLICIT_CORRECTION.search(text),
        "no_turkish": not TURKISH.search(text.replace("manti", "")),
        "no_ai_tells": not AI_TELLS.search(text),
    }
    if case.get("recast"):
        low = text.lower()
        checks["recast"] = any(r.lower() in low for r in case["recast"])
    if case["kind"] in ("help", "unfinished"):
        # A hint, not a lecture: should invite the learner to try.
        checks["hint"] = bool(re.search(r"try|start with|you could say|how about|say|\.\.\.", text, re.I))
    return checks


def vram_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:
        return None


NO_THINK_TOGGLE: set[str] = set()


def chat(client: httpx.Client, model: str, messages: list[dict]) -> dict:
    body = {"model": model, "messages": messages, "stream": True, "options": OPTIONS}
    if model not in NO_THINK_TOGGLE:
        body["think"] = False
    try:
        return _stream(client, body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 400 or "think" not in body:
            raise
        NO_THINK_TOGGLE.add(model)  # model has no thinking toggle
        body.pop("think")
        return _stream(client, body)


def _stream(client: httpx.Client, body: dict) -> dict:
    t0 = time.perf_counter()
    ttft, parts, final, thinking_chars = None, [], {}, 0
    with client.stream("POST", f"{OLLAMA}/api/chat", json=body, timeout=180) as r:
        if r.status_code >= 400:
            r.read()
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            msg = chunk.get("message", {})
            thinking_chars += len(msg.get("thinking", "") or "")
            if msg.get("content"):
                ttft = ttft or (time.perf_counter() - t0)
                parts.append(msg["content"])
            if chunk.get("done"):
                final = chunk
    return _result(parts, ttft, t0, final, thinking_chars)


def _result(parts, ttft, t0, final, thinking_chars):
    eval_s = (final.get("eval_duration") or 0) / 1e9
    return {
        "reply": "".join(parts),
        "ttft_s": round(ttft or 0, 3),
        "total_s": round(time.perf_counter() - t0, 3),
        "tok_s": round(final.get("eval_count", 0) / eval_s, 1) if eval_s else None,
        "prompt_tokens": final.get("prompt_eval_count"),
        "cached_tokens": final.get("prompt_eval_cached_count"),
        "thinking_chars": thinking_chars,
    }


def run_model(model: str, cases: list[dict], runs: int) -> list[dict]:
    sysmsg = system_prompt()
    out_dir = ROOT / "bench" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{model.replace(':', '_').replace('/', '_')}__{PROMPT_VERSION}.jsonl"
    rows = []
    with httpx.Client() as client:
        # Warm up so load time doesn't count as TTFT.
        t0 = time.perf_counter()
        client.post(f"{OLLAMA}/api/chat", json={"model": model, "messages": [], "keep_alive": -1}, timeout=600)
        load_s = round(time.perf_counter() - t0, 1)
        chat(client, model, [{"role": "system", "content": sysmsg}, {"role": "user", "content": "Hi!"}])
        vram = vram_mib()
        ps = client.get(f"{OLLAMA}/api/ps").json().get("models", [])
        gpu_share = None
        for m in ps:
            if m.get("name") == model or m.get("model") == model:
                size, size_vram = m.get("size") or 0, m.get("size_vram") or 0
                gpu_share = round(100 * size_vram / size) if size else None
        print(f"\n== {model}  load {load_s}s  VRAM {vram} MiB  on-GPU {gpu_share}%", flush=True)
        for run in range(runs):
            for case in cases:
                messages = [
                    {"role": "system", "content": sysmsg},
                    {"role": "assistant", "content": case["prev"]},
                    {"role": "user", "content": case["user"]},
                ]
                res = chat(client, model, messages)
                checks = score(case, res["reply"])
                row = {"model": model, "prompt": PROMPT_VERSION, "run": run, "id": case["id"],
                       "kind": case["kind"], "user": case["user"], **res, "checks": checks,
                       "vram_mib": vram, "gpu_share": gpu_share, "load_s": load_s}
                rows.append(row)
                fails = [k for k, v in checks.items() if not v]
                mark = "ok " if not fails else "FAIL " + ",".join(fails)
                print(f"  {case['id']:<18} {res['ttft_s']:.2f}s  {mark}\n      > {res['reply'].strip()[:200]}", flush=True)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    return rows


def summarize(model: str, rows: list[dict]) -> dict:
    checks = [c for r in rows for c in r["checks"].values()]
    per = {}
    for r in rows:
        for k, v in r["checks"].items():
            per.setdefault(k, []).append(v)
    return {
        "model": model,
        "pass_%": round(100 * sum(checks) / len(checks), 1),
        "cases_all_ok_%": round(100 * sum(all(r["checks"].values()) for r in rows) / len(rows), 1),
        "ttft_p50": round(statistics.median(r["ttft_s"] for r in rows), 3),
        "ttft_max": round(max(r["ttft_s"] for r in rows), 3),
        "tok_s": round(statistics.median(r["tok_s"] or 0 for r in rows), 1),
        "vram_mib": rows[0]["vram_mib"],
        "gpu_%": rows[0]["gpu_share"],
        "thinking_leak": sum(1 for r in rows if r["thinking_chars"]),
        **{k: round(100 * sum(v) / len(v)) for k, v in per.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()
    cases = yaml.safe_load((ROOT / "bench" / "cases.yaml").read_text())
    summaries = [summarize(m, run_model(m, cases, args.runs)) for m in args.models]
    print(f"\nprompt {PROMPT_VERSION}, {len(cases)} cases x {args.runs} run(s)")
    keys = list(summaries[0].keys())
    for s in summaries:
        for k in keys:
            s.setdefault(k, "")
    widths = {k: max(len(k), *(len(str(s[k])) for s in summaries)) for k in keys}
    print("  ".join(k.ljust(widths[k]) for k in keys))
    for s in summaries:
        print("  ".join(str(s[k]).ljust(widths[k]) for k in keys))


if __name__ == "__main__":
    main()
