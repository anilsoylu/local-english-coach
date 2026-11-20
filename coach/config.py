"""Settings from config.yaml; env vars override.

Personal data never lives in the repo. config.yaml is gitignored and optional: without it the
coach runs with neutral defaults, and an empty `about` means no profile is sent to the model.
config.example.yaml only documents the format and is never loaded.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load() -> dict:
    path = Path(os.environ.get("COACH_CONFIG", ROOT / "config.yaml"))
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


_cfg = _load()
_learner = _cfg.get("learner", {})
_models = _cfg.get("models", {})
_server = _cfg.get("server", {})

LEARNER_NAME: str = str(_learner.get("name") or "").strip()  # empty: openings drop the name
LEARNER_LEVEL: str = str(_learner.get("level") or "A2").strip()
LEARNER_ABOUT: str = " ".join(str(_learner.get("about") or "").split())  # empty: no profile in the prompt

CHAT_MODEL: str = os.environ.get("COACH_MODEL", _models.get("chat", "gemma4:e4b"))
ANALYSIS_MODEL: str = os.environ.get("COACH_ANALYSIS_MODEL", _models.get("analysis", CHAT_MODEL))
OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
USER_ID: str = os.environ.get("COACH_USER", "default")
DB_PATH = Path(os.environ.get("COACH_DB", ROOT / "data" / "coach.db"))

HOST: str = os.environ.get("COACH_HOST", _server.get("host", "127.0.0.1"))
PORT: int = int(os.environ.get("COACH_PORT", _server.get("port", 8765)))
