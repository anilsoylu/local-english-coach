# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, opencode and others) working on this repo. Humans: see README.md.

English Coach is a local text chat for Turkish speakers practicing spoken-style English. A small model on the GPU chats, a larger model reviews each session afterwards, and SQLite keeps the learner's mistakes and phrases between sessions. Everything runs on the user's machine through Ollama.

## Rules

- **No personal data in git.** Learner details live in `config.yaml`, sessions in `data/`. Both are gitignored. Any future feature that reads personal material (writing samples, chat exports, character analysis) follows the same pattern: a gitignored file or folder, a committed `*.example` that shows the format, and code that treats a missing or empty file as "feature off". Never fall back to example data, and never put real names, places or messages in fixtures, tests or docs.
- **Local models only.** Don't use Ollama `:cloud` models. They don't support structured outputs (`format`), which the session analysis depends on, and the user's conversations would leave the machine.
- **Measure before and after.** Any change to `coach/prompts.py` bumps `PROMPT_VERSION` and gets a bench run (below). Any model change gets a bench run on the target machine.
- **Keep the system prompt fixed within a session.** It is built once in `POST /api/session` and stored. Changing it mid-session breaks Ollama's prompt cache: today about 97% of each turn's prompt comes from cache.
- **The coach never answers in Turkish and never explains grammar during the chat.** It repeats the learner's sentence correctly (a recast) and asks one question. Corrections and Turkish explanations belong to the end-of-session report.
- **Keep autocorrect off in the UI** (`spellcheck="false" autocorrect="off"`). With it on, the phone fixes mistakes before the coach sees them.
- **Read the docs before adding or changing a stack.** Check the tool's official docs or `llms.txt` and use what they recommend for this setup. A default install isn't enough. Note the source in a comment where a setting comes from (see `Dockerfile`, `deploy/ollama.override.conf`).
- **Style:** DRY and KISS. File names are kebab-case, except Python modules that get imported (those can't contain hyphens). Code, comments and docs are in English.
- **Tests run in the test container** (`docker compose --profile test ...`) with a temporary database, never against `data/coach.db`. Browsers run headless.
- **Changes go through a pull request.** No direct pushes to `master`.

## Install

Linux with an NVIDIA GPU and Docker Engine (not Docker Desktop, whose VM can't reach the host's Ollama through `network_mode: host`; with both installed, run compose with `DOCKER_CONTEXT=default`):

```sh
sudo ./setup.sh --tailscale   # or: sudo ./setup.sh  (localhost only), --host IP --port N
```

`--tailscale` keeps the app on 127.0.0.1 and shares it through Tailscale Serve (HTTPS when the tailnet has certificates, otherwise HTTP on the app port). Don't bind the app to the Tailscale IP: if Docker starts before `tailscaled` at boot, the bind fails.

`setup.sh` installs Ollama natively if it's missing and applies `deploy/ollama.override.conf`. It then picks models for the VRAM it finds, writes `config.yaml` if there isn't one, pulls the models, starts the app with `docker compose up -d --build` (restart policy `unless-stopped`, so it comes back after a reboot) and adds a daily backup cron job. It is safe to run again.

Without Docker: `uv sync && uv run python -m coach`.

## Verify

On the GPU machine, after `setup.sh`:

```sh
docker compose --profile test run --rm test                          # API: session, chat, help, Turkish turn, report
docker compose --profile test run --rm test python tests/ui-test.py  # headless Chromium, phone + desktop
docker compose --profile test run --rm test python tests/chats-test.py  # chat import on the made-up exports
```

The test image is the app image plus tests, bench and headless Chromium. Each test starts its own server on a temporary database inside the container. Look at the screenshots in `tests/screenshots/`: the JSON output only catches console errors and overflow, not a broken layout.

## Optimize for a different machine

1. Check the GPU: `nvidia-smi`. After a model loads, `ollama ps` must show `100% GPU`. A CPU/GPU split makes chat replies several times slower.
2. Chat model: pick candidates that fit in VRAM minus about 1.5 GB (KV cache and desktop). Run them on the fixed learner turns:
   ```sh
   uv run bench/run.py gemma4:e4b qwen3.5:4b   # writes bench/results/*.jsonl, prints a table
   uv run bench/run.py MODEL --rescore         # re-score saved replies after changing checks
   ```
   (Or inside the test container: `docker compose --profile test run --rm test python bench/run.py MODEL`.)
   Aim for 95%+ pass with `recast` near 100. Then read the replies in `bench/results/`. The checks don't catch a coach that makes grammar mistakes itself. On the reference machine, `qwen3.5:4b` scored 99.4% but said "you are a developer for five years", so it was rejected.
3. Analysis model: it runs once per session, so a larger or partly CPU-offloaded model is fine:
   ```sh
   uv run bench/analysis.py qwen3.5:9b gemma4:26b-a4b
   ```
   Read the `note_tr` and `feedback_tr` fields. They must be correct Turkish and teach the right rule. This was the deciding factor between models on the reference machine.
4. Put the winners in `config.yaml` under `models:` and restart: `docker compose up -d`.

Ollama settings (`deploy/ollama.override.conf`, see https://docs.ollama.com/faq.md):

| Setting | Why |
|---|---|
| `OLLAMA_FLASH_ATTENTION=1` | Needed for the quantized KV cache |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | Halves KV cache memory |
| `OLLAMA_KEEP_ALIVE=-1` | Chat model stays loaded, no cold start |
| `OLLAMA_NUM_PARALLEL=1` | One user, so one KV cache allocation |
| `OLLAMA_MAX_LOADED_MODELS=1` | The analysis model replaces the chat model while it runs. The app reloads the chat model afterwards. |
| `OLLAMA_CONTEXT_LENGTH=8192` | A 30-minute session fits. The request also sets `num_ctx`. |

Requests send `"think": false`. Reasoning adds latency and doesn't help a 1 to 3 sentence reply.

## Layout

```
coach/server.py     FastAPI: sessions, streaming chat, report and progress endpoints
coach/prompts.py    system prompt (PROMPT_VERSION), spoken-style rules
coach/analyze.py    end-of-session analysis (JSON schema) and the code-side clean-up of its output
coach/memory.py     SQLite schema, Turkish/help detection, Leitner spaced repetition
coach/config.py     config.yaml + env vars (COACH_MODEL, COACH_ANALYSIS_MODEL, COACH_DB, COACH_USER, COACH_HOST, COACH_PORT)
coach/chats.py      chat export import (Instagram/Messenger, WhatsApp, Telegram, plain text) from data/personal/chats/; local models only, prints ids and counts only
web/index.html      the whole UI, no build step
web/static/         manifest and icons for "Add to Dock" / home screen
scenarios.yaml      roles, openings and seed phrases; {name} is the learner's name
bench/              chat bench (cases.yaml) and analysis bench (transcripts.yaml)
examples/           made-up personal-data formats (chat exports, friend persona); tests use them
tests/              smoke and UI tests
deploy/             Ollama override, backup script
```
