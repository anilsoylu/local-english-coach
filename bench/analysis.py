"""Compare end-of-session analysis models on fixed transcripts.

Usage: uv run bench/analysis.py MODEL [MODEL ...] [--native tr]
Prints timing, rule checks and the full reports (read the notes and feedback in the native language yourself: the
automatic checks can't tell whether a grammar explanation is right). The transcripts' native-language lines are
Turkish, so other --native values test only the language of the explanations.
"""

from __future__ import annotations

import argparse
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
from coach.analyze import analysis_prompt, call_model, clean_report  # noqa: E402
from coach.memory import detect_lang  # noqa: E402

PRAISE = re.compile(r"harika|mükemmel|muhteşem|!", re.I)  # Turkish words plus "!", which no language needs here


def to_turns(raw: list, native: str) -> list[dict]:
    out = []
    for item in raw:
        role, text, *flag = item
        lang = "native" if flag == ["native"] else detect_lang(text, native) if role == "user" else None
        out.append({"role": "user" if role == "user" else "assistant", "content": text,
                    "is_help": int(flag == ["help"]), "lang": lang})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--native", default="tr", help="the learner's native language code (coach/languages.py)")
    args = ap.parse_args()
    sessions = yaml.safe_load((ROOT / "bench" / "transcripts.yaml").read_text())
    known = ["I wanted to give you a heads-up about ...", "I'll keep you posted."]
    out_dir = ROOT / "bench" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for model in args.models:
        t0 = time.perf_counter()
        httpx.post(f"{config.OLLAMA_URL}/api/chat", json={"model": model, "messages": []}, timeout=900)
        load_s = time.perf_counter() - t0
        ps = httpx.get(f"{config.OLLAMA_URL}/api/ps").json().get("models", [])
        gpu = next((round(100 * m["size_vram"] / m["size"]) for m in ps if m.get("name") == model and m.get("size")), None)
        times, raw_err, kept_err, praise, reports = [], 0, 0, 0, {}
        for s in sessions:
            turns = to_turns(s["turns"], args.native)
            prompt = analysis_prompt(turns, args.native, "Deniz", "A2+", [], known)
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
            praise += bool(PRAISE.search(rep.get("feedback", "")))
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
