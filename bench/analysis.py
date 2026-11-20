"""Compare end-of-session analysis models on fixed transcripts.

Usage: uv run bench/analysis.py MODEL [MODEL ...]
Prints timing, rule checks and the full reports (read the Turkish notes yourself: the
automatic checks can't tell whether a grammar explanation is right).
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from coach import config  # noqa: E402
from coach.analyze import PROMPT, call_model, clean_report  # noqa: E402
from coach.memory import detect_lang  # noqa: E402

PRAISE = re.compile(r"harika|mükemmel|muhteşem|!", re.I)


def to_turns(raw: list) -> list[dict]:
    out = []
    for item in raw:
        role, text, *flag = item
        out.append({"role": "user" if role == "user" else "assistant", "content": text,
                    "is_help": int(flag == ["help"]),
                    "lang": "tr" if flag == ["tr"] else (detect_lang(text) if role == "user" else None)})
    return out


def transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        if t["role"] != "user":
            lines.append(f"COACH: {t['content']}")
        else:
            tag = " [asked for help]" if t["is_help"] else " [Turkish]" if t["lang"] in ("tr", "mixed") else ""
            lines.append(f"USER{tag}: {t['content']}")
    return "\n".join(lines)


def main() -> None:
    sessions = yaml.safe_load((ROOT / "bench" / "transcripts.yaml").read_text())
    known = ["I wanted to give you a heads-up about ...", "I'll keep you posted."]
    out_dir = ROOT / "bench" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for model in sys.argv[1:]:
        t0 = time.perf_counter()
        httpx.post(f"{config.OLLAMA_URL}/api/chat", json={"model": model, "messages": []}, timeout=900)
        load_s = time.perf_counter() - t0
        ps = httpx.get(f"{config.OLLAMA_URL}/api/ps").json().get("models", [])
        gpu = next((round(100 * m["size_vram"] / m["size"]) for m in ps if m.get("name") == model and m.get("size")), None)
        times, raw_err, kept_err, praise, reports = [], 0, 0, 0, {}
        for s in sessions:
            turns = to_turns(s["turns"])
            prompt = PROMPT.format(name="Deniz", level="A2+", recurring="none yet", known="; ".join(known),
                                   transcript=transcript(turns))
            t1 = time.perf_counter()
            try:
                rep = call_model(prompt, model=model)
            except Exception as e:  # invalid JSON or timeout counts as a failure
                rep = {"error": str(e)}
            times.append(time.perf_counter() - t1)
            raw_err += len(rep.get("errors", []))
            if "error" not in rep:
                clean_report(rep, turns, known)
            kept_err += len(rep.get("errors", []))
            praise += bool(PRAISE.search(rep.get("feedback_tr", "")))
            reports[s["id"]] = rep
        (out_dir / f"analysis__{model.replace(':', '_')}.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))
        summary.append({"model": model, "load_s": round(load_s, 1), "gpu_%": gpu,
                        "avg_s": round(sum(times) / len(times), 1), "max_s": round(max(times), 1),
                        "errors_raw": raw_err, "errors_kept": kept_err, "praise_in_feedback": praise,
                        "failed": sum("error" in r for r in reports.values())})
        print(f"\n######## {model}")
        print(json.dumps(reports, ensure_ascii=False, indent=1))
    print()
    for row in summary:
        print(row)


if __name__ == "__main__":
    main()
