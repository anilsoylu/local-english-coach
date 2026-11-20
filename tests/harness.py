"""Start a throwaway server (temp DB, own port) so tests never touch real data."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def test_server(port: int = 8799, **env_overrides: str):
    tmp = tempfile.mkdtemp(prefix="coach-test-")
    env = {**os.environ, "COACH_DB": f"{tmp}/test.db", "COACH_USER": "test",
           "COACH_HOST": "127.0.0.1", "COACH_PORT": str(port), **env_overrides}
    proc = subprocess.Popen([sys.executable, "-m", "coach"], cwd=ROOT, env=env,
                            stdout=open(f"{tmp}/server.log", "w"), stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                httpx.get(f"{base}/api/scenarios", timeout=2).raise_for_status()
                break
            except Exception:
                if proc.poll() is not None:
                    raise RuntimeError(Path(f"{tmp}/server.log").read_text())
                time.sleep(1)
        yield base, Path(f"{tmp}/server.log")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
