# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, opencode and others) working on this repo. Humans: see README.md.

English Coach is a local text chat for people practicing spoken-style English, with feedback in their native language (see `GLOSSARY.md`). One install serves one learner. A small model on the GPU chats, a larger model reviews each session afterwards, and SQLite keeps the learner's mistakes and phrases between sessions. Everything runs on the user's machine through Ollama.

## Rules

- **No personal data in git.** Learner details live in `config.yaml`, sessions in `data/`. Both are gitignored. Any future feature that reads personal material (writing samples, chat exports, character analysis) follows the same pattern: a gitignored file or folder, a committed `*.example` that shows the format, and code that treats a missing or empty file as "feature off". Never fall back to example data, and never put real names, places or messages in fixtures, tests or docs.
- **Local models only.** Don't use Ollama `:cloud` models. They don't support structured outputs (`format`), which the session analysis depends on, and the user's conversations would leave the machine.
- **Measure before and after.** Any change to `coach/prompts.py` bumps `PROMPT_VERSION` and gets a bench run (below). Any model change gets a bench run on the target machine.
- **Keep the system prompt fixed within a session.** It is built once in `POST /api/session` and stored. Changing it mid-session breaks Ollama's prompt cache: today about 97% of each turn's prompt comes from cache.
- **The coach always answers in English and never explains grammar during the chat.** The learner may write in their native language when stuck; the coach gives the English sentence back. Otherwise it repeats the learner's sentence correctly (a recast) and asks one question. Corrections and explanations in the native language belong to the end-of-session report.
- **Adding a language** follows the "Add a language" section of README.md: one line in `coach/languages.py`, then optional locale file, scenario translations and a bench case. Never hardcode a language elsewhere; Arabic and other RTL languages aren't supported yet.
- **Keep autocorrect off in the UI** (`spellcheck="false" autocorrect="off"`). With it on, the phone fixes mistakes before the coach sees them.
- **Read the docs before adding or changing a stack.** Check the tool's official docs or `llms.txt` and use what they recommend for this setup. A default install isn't enough. Note the source in a comment where a setting comes from (see `Dockerfile`, `deploy/ollama.override.conf`).
- **Style:** DRY and KISS. File names are kebab-case, except Python modules that get imported (those can't contain hyphens). Code, comments and docs are in English.
- **Tests run in the test container** (`docker compose --profile test ...`) with a temporary database, never against `data/coach.db`. Browsers run headless.
- **Changes go through a pull request.** No direct pushes to `master`.

## Install

The README's "Install with an AI agent" prompt sends agents here. Follow these steps in order.

1. **Check the hardware.** Stop and tell the user what's missing; don't install drivers or Docker on your own.
   - Linux with an NVIDIA GPU: `nvidia-smi` lists it with its VRAM.
   - Docker Engine with the compose plugin: `docker compose version` works. Not Docker Desktop, whose VM can't reach the host's Ollama through `network_mode: host`. With both installed, `docker context use default` (or `DOCKER_CONTEXT=default`) selects the Engine.
   - About 25 GB free disk for the models: `df -h .`
2. **Ask the user** for their name, their English level (a rough CEFR guess such as A2 or B1 is fine; A2 if they don't know) and a sentence or two about their work. Every answer is optional. Don't ask for their native language: they pick it in the UI on first open.
3. **Write `config.yaml`** with only the `learner:` block (`name`, `level`, `about`; format in `config.example.yaml`). If the file already exists, edit that block and leave the rest. Do this before `setup.sh`: the app stores `level` once, on its first request, and `setup.sh` makes that request. `setup.sh` fills in the models for this GPU and the server settings.
4. **Run `setup.sh`.** It needs sudo: show the user the exact command and wait for their go-ahead, or ask them to run it in their own terminal.
   ```sh
   sudo ./setup.sh --tailscale   # or: sudo ./setup.sh  (localhost only), --host IP --port N
   ```
5. **Verify.** `setup.sh` ends with `Done: <url>`. Check that `curl -sf <url>/api/languages` returns JSON and `<url>/` returns the page. Then give the user the URL and tell them to open it and pick their native language.

`--tailscale` keeps the app on 127.0.0.1 and shares it through Tailscale Serve (HTTPS when the tailnet has certificates, otherwise HTTP on the app port). Don't bind the app to the Tailscale IP: if Docker starts before `tailscaled` at boot, the bind fails.

`setup.sh` installs Ollama natively if it's missing and applies `deploy/ollama.override.conf`. It then picks models for the VRAM it finds, writes `config.yaml` if there isn't one (or adds the `models:` and `server:` values an existing one leaves out or leaves empty, keeping everything else), pulls the models, starts the app with `docker compose up -d --build` (restart policy `unless-stopped`, so it comes back after a reboot) and adds a daily backup cron job. It is safe to run again. After editing `config.yaml` later, run `docker compose restart coach`.

Without Docker: `cd frontend && bun install && bun run build`, then `uv sync && uv run python -m coach`.

## Verify

On the GPU machine, after `setup.sh`:

```sh
docker compose --profile test run --rm test                          # API: session, chat, help, native-language turns, report
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
   uv run bench/analysis.py qwen3.5:9b gemma4:26b-a4b --native es
   ```
   Read the `note`, `meaning` and `feedback` fields. They must be correct in the target native language and teach the right rule. This was the deciding factor between models on the reference machine (with Turkish). The transcripts' native-language lines are Turkish, so other `--native` values test only the language of the explanations.
4. Put the winners in `config.yaml` under `models:` and restart: `docker compose up -d`.

Ollama settings (`deploy/ollama.override.conf`, see https://docs.ollama.com/faq.md):

| Setting | Why |
|---|---|
| `OLLAMA_FLASH_ATTENTION=1` | Needed for the quantized KV cache |
| `OLLAMA_KV_CACHE_TYPE=q8_0` | Halves KV cache memory |
| `OLLAMA_KEEP_ALIVE=15m` | Frees the VRAM 15 minutes after the last request. The page calls `POST /api/warm` when it opens or comes back into view, so the model is loaded again before the first message. The app sends the same value per request (`COACH_KEEP_ALIVE`). |
| `OLLAMA_NUM_PARALLEL=1` | One user, so one KV cache allocation |
| `OLLAMA_MAX_LOADED_MODELS=1` | The analysis model replaces the chat model while it runs. The app reloads the chat model afterwards. |
| `OLLAMA_CONTEXT_LENGTH=8192` | A 30-minute session fits. The request also sets `num_ctx`. |

Requests send `"think": false`. Reasoning adds latency and doesn't help a 1 to 3 sentence reply.

## Layout

```
coach/server.py     FastAPI: sessions, streaming chat, report and progress endpoints
coach/prompts.py    system prompt (PROMPT_VERSION), spoken-style rules
coach/analyze.py    end-of-session analysis (JSON schema) and the code-side clean-up of its output
coach/memory.py     SQLite schema, language detection (lingua: en/native/mixed), help detection, Leitner spaced repetition
coach/languages.py  the native languages the learner can pick; scenario text lookup with English fallback
coach/config.py     config.yaml + env vars (COACH_MODEL, COACH_ANALYSIS_MODEL, COACH_DB, COACH_USER, COACH_HOST, COACH_PORT)
coach/chats.py      chat export import (Instagram/Messenger, WhatsApp, Telegram, plain text) from data/personal/chats/; local models only, prints ids and counts only
frontend/           Next.js static export (bun); `bun run build` writes frontend/out, which FastAPI serves. See frontend/README.md
frontend/locales/   UI strings per native language (<code>.json); English is the components' defaults, missing keys fall back to it
frontend/public/    manifest and icons for "Add to Dock" / home screen
scenarios.yaml      roles, openings and seed phrases; {name} is the learner's name; titles and meanings map by language code
bench/              chat bench (cases.yaml, `native` per case) and analysis bench (transcripts.yaml, `--native`)
examples/           made-up personal-data formats (chat exports, friend persona); tests use them
tests/              smoke and UI tests
deploy/             Ollama override, backup script
```
