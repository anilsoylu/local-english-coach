# Pattern from https://docs.astral.sh/uv/guides/integration/docker/
FROM python:3.12-slim-trixie AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first so code changes don't reinstall them. Voice extras are not installed.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY coach ./coach
COPY web ./web
COPY scenarios.yaml ./
ENV PATH="/app/.venv/bin:$PATH"

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request as u; from coach import config as c; u.urlopen(f'http://{c.HOST}:{c.PORT}/api/scenarios', timeout=4)"

CMD ["python", "-m", "coach"]

# Test image: same app plus tests, bench and headless Chromium. Never used in production.
# Run: docker compose --profile test run --rm test
FROM app AS test
# libatomic1: needed by the Node driver bundled with Playwright, missing from slim images.
RUN --mount=type=cache,target=/root/.cache/uv \
    apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && uv pip install --python /app/.venv/bin/python playwright \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/*
COPY tests ./tests
COPY bench ./bench
COPY examples ./examples
CMD ["python", "tests/smoke.py"]
