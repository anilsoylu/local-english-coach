# English Coach

A local chat partner for practicing everyday and work English, for people who understand English but freeze when they have to put a sentence together. Feedback comes in your own language: you pick it when you first open the app (English, Turkish, Spanish, Brazilian Portuguese, German, French, Italian, Polish, Russian, Japanese, Korean or Simplified Chinese). The models run on your own GPU through [Ollama](https://ollama.com), and your conversations stay in a SQLite file on your machine. One install serves one learner.

Here is a Turkish speaker using it:

```
Coach: Hi, quick check-in. Are we still on track for Friday's demo?
You:   Sorry, the demo is not ready, we have problem with payment API.
Coach: Right, the demo isn't ready because you have a problem with the payment API.
       I see. What is the new plan for the demo?
You:   I think I need two more day, maybe Monday is ok?
Coach: You think you need two more days, and maybe Monday is okay. Hmm. What part
       of the API is giving you trouble?
You:   Müşteriye nasıl söylerim bilmiyorum.
Coach: I think I need two more days because the payment API has some issues.
       Try saying that.
```

(A real exchange from the browser test, with `gemma4:e4b`.)

The coach doesn't stop you to explain grammar. It says your sentence back the way a native speaker would ("we have problem" becomes "you have a problem") and keeps the conversation going. If you get stuck, you can write in your own language or press the **I'm stuck** button to get the English version or the first few words. The coach always answers in English. When you end the session, a second, larger model reviews the whole chat and gives you, in your language:

- the 3 or 4 mistakes that matter most, each with a one-line explanation
- a more natural way to say some of your correct but stiff sentences
- 2 or 3 new phrases for the situations you were in, with their meaning

The next session starts with the phrases that are due for review (spaced repetition), and the coach steers the conversation so you get a chance to use them.

## Install with an AI agent

If you use a coding agent (Claude Code, Codex, opencode or similar), open it in the folder where you keep projects and paste this prompt. The steps it follows are in the Install section of [AGENTS.md](AGENTS.md).

```text
Install English Coach on this machine for me.

1. Clone https://github.com/anilsoylu/local-english-coach.git and cd into it.
2. Read AGENTS.md and follow its Install section in order. That section is the
   source of truth; don't skip or reorder its steps.
3. Check the hardware requirements it lists first (Linux, NVIDIA GPU, Docker
   Engine rather than Docker Desktop, disk space). If one is missing, stop and
   tell me what to install.
4. Ask me for my name, my English level and a sentence about my work, then
   write config.yaml as AGENTS.md describes.
5. Run setup.sh. Before running anything with sudo, show me the exact command
   and wait for my answer.
6. Check that the app answers on the URL setup.sh prints, then give me that URL
   and tell me to open it and pick my native language.
```

## Requirements

- Linux with an NVIDIA GPU. Tested on an RTX 3070 with 8 GB of VRAM, 32 GB of RAM, Ubuntu 26.04. Smaller cards get smaller models, but those configurations are untested.
- Docker Engine with the compose plugin. Docker Desktop doesn't work here: it runs containers in a VM, so `network_mode: host` can't reach Ollama on the host, and it only starts after you log in to the desktop. If you have both, use the Engine with `docker context use default` (or `DOCKER_CONTEXT=default`).
- About 25 GB of disk space for the models

## Install

```sh
git clone https://github.com/anilsoylu/local-english-coach.git
cd local-english-coach
sudo ./setup.sh
```

The script installs Ollama if it's missing, tunes it, picks models for your VRAM, pulls them and starts the app with Docker Compose. The app restarts on its own after a reboot. Then open http://127.0.0.1:8765 and pick your native language. You can change it later from the button on the scenario screen.

To use it from your phone or laptop, put the machine on [Tailscale](https://tailscale.com) and run `sudo ./setup.sh --tailscale`. The app keeps listening on 127.0.0.1, and [Tailscale Serve](https://tailscale.com/kb/1312/serve) shares it with your tailnet only, at `https://<machine-name>.<tailnet>.ts.net`. HTTPS needs the tailnet's HTTPS certificates. Turn them on once in the admin console under DNS. Until you do, the script serves plain HTTP on port 8765 inside the tailnet and prints the link to turn HTTPS on.

On a Mac, open that address in Safari and choose File > Add to Dock to get a standalone app window. On a phone, the keyboard's microphone button lets you speak your answers instead of typing them. If you reload the page or the laptop sleeps, the open session comes back.

## Personalize

Fill in the `learner:` block of `config.yaml` (setup.sh creates one with empty fields; `config.example.yaml` shows every option) with your name and a sentence or two about your work, then run `docker compose restart coach`. The coach uses them in scenarios and small talk. Every field is optional. Without a name the coach just says "Hi", and without an `about` line it doesn't get a profile at all. The `level` is read only once, the first time the app opens; after that, each session's review updates it. To set it from the start, create `config.yaml` with just the `learner:` block before running setup.sh, which adds the models and server settings.

Scenarios live in `scenarios.yaml`: the coach's role, the situation, its opening line and a few phrases to practice. The defaults are aimed at a freelance developer (client calls, price talks, reporting a delay, stand-ups, a job interview), plus small talk and travel. Add your own in the same format.

## Learn from your real chats

If you chat in English with someone (and they're fine with it), the coach can learn from those chats. Everything runs on the local models, and the messages never leave the machine.

1. Export the chat from the app and put it anywhere under `data/personal/chats/` (gitignored):
   - Instagram or Facebook Messenger: Accounts Center > Your information and permissions > Export your information. Pick Messages only, All time, JSON, then unzip it.
   - WhatsApp: open the chat > More > Export chat > Without media. You get `_chat.txt` (iPhone and Android layouts both work).
   - Telegram Desktop: Settings > Advanced > Export Telegram data, or Export chat history on one chat, in JSON format.
   - Anything else: a `.txt` with one `Name: message` per line.

   `examples/chats/` has each format with made-up messages.
2. `docker compose exec coach python -m coach.chats threads` lists every conversation by id, format and message count. Names aren't shown because folder and file names contain them.
3. `docker compose exec coach python -m coach.chats import <id>`. Add `--me "Your Name"` if it can't tell which participant you are. Detection works when you appear in more conversations than anyone else.

Your own English messages, an even sample of up to 1200, go through the analysis model. Mistakes you repeat go into your profile, and phrases you were missing go into spaced repetition, due right away. The other person's messages become a short note on how they chat (tone, humor, favorite topics), with no names or identifying details. The "Chat with a friend from abroad" scenario uses that note (format: `examples/friend-persona.example.json`). The coach copies the manner, not their English mistakes. Without the folder, none of this runs.

## How the models were chosen

Chat model candidates were run against fixed learner messages (`bench/cases.yaml`). The automatic checks cover reply length, one question per reply, no explicit correction, no native-language text in the reply, no assistant-style phrases, and whether the reply recasts the mistake.

The bench has 42 cases. In 16 of them a stuck learner writes in their native language, and together they cover all 11 non-English launch languages. For those, the `first_person` check requires the English sentence the coach offers to be in the learner's own words ("I", "my") rather than echoed back as "you", so the learner can say it as is. Two of them are multi-turn: the learner writes "I don't know how to say it" in Turkish or Spanish right after a help hint, and the `no_reuse` check fails the reply if it repeats that hint.

All numbers were measured on the RTX 3070. The gemma4:e4b row is prompt v5 on the current bench, averaged over 3 runs: 95.2% of cases passed every check, `first_person` 100%, `no_reuse` 100%. On the same bench, prompt v4 scored 97.0% of checks, `first_person` 69% and `no_reuse` 17%. The other models were not re-run; their rows come from an earlier prompt and the first version of the bench, which had 30 messages from Turkish learners.

| Model | Bench | Checks passed | First token | Speed | VRAM | Verdict |
|---|---|---|---|---|---|---|
| gemma4:e4b | current, prompt v5 | 99.3% | 0.04 s | 165 tok/s | 5.1 GB | chosen |
| qwen3.5:4b | Turkish only | 99.4% | 0.20 s | 109 tok/s | 4.2 GB | rejected: made grammar mistakes in its own replies |
| qwen3.5:9b | Turkish only | 95.5% | 0.23 s | 69 tok/s | 6.7 GB | fewer recasts, skipped "try saying that" |
| ministral-3:8b | Turkish only | 85.3% | 0.03 s | 72 tok/s | 6.7 GB | rejected |
| lfm2.5:8b | Turkish only | 57.1% (first prompt) | 0.07 s | 251 tok/s | 5.6 GB | replies too long |

The prompt mattered more than the model. With the first prompt, even the best models recast only 57% of mistakes. Most of the time they reacted to the content and changed the subject. Telling them to echo the learner's sentence first raised that to 96 to 100%.

The end-of-session review runs once per session, so it can use a bigger model. Three candidates reviewed the same three transcripts (`bench/transcripts.yaml`) and wrote their explanations in Turkish:

| Model | Average time | Result |
|---|---|---|
| gemma4:26b-a4b | 25 s | chosen: caught the most real mistakes and explained each one correctly |
| gemma4:12b | 29 s | clean Turkish, but once praised verbs the learner had gotten wrong |
| qwen3.5:9b | 16 s | broken Turkish and invented grammar rules |

A later run of `gemma4:26b-a4b` with `--native tr` and `--native es` took 19.7 s and 21.5 s on average. In both languages the explanations were correct and addressed the learner informally, in the second person.

`gemma4:26b-a4b` is an 18 GB mixture-of-experts model. About a quarter of it sits in system RAM on an 8 GB card, but it only activates 4B parameters per token, so it still finishes faster than the 12B model that fits entirely on the GPU.

Prompt caching does the rest. The system prompt stays the same for the whole session, so Ollama reuses about 97% of each turn's prompt from cache and processes only the new message.

## Use the models from your other computers

Ollama has no authentication, so don't bind it to `0.0.0.0` on a home network. With Tailscale, forward the port to your tailnet only:

```sh
sudo tailscale serve --bg --tcp=11434 tcp://localhost:11434
```

Then, on another device in the tailnet: `OLLAMA_HOST=http://<machine-name>:11434 ollama run gemma4:e4b`. The Ollama desktop app's chat window still uses its own local server.

## Development

Tests run in their own container with a temporary database, so they never touch your sessions:

```sh
docker compose --profile test run --rm test                          # API: session, chat, help, report
docker compose --profile test run --rm test python tests/ui-test.py  # headless browser, phone and desktop
docker compose --profile test run --rm test python tests/chats-test.py  # chat import on the made-up exports
docker compose --profile test run --rm test python bench/run.py gemma4:e4b
docker compose --profile test run --rm test python bench/analysis.py gemma4:26b-a4b
```

The web UI is a Next.js static export in `frontend/`; see [frontend/README.md](frontend/README.md).

[AGENTS.md](AGENTS.md) has the rules and the tuning procedure for AI coding agents. It also works as a checklist if you're moving the project to different hardware by hand.

## Add a language

1. Add one line to `LANGUAGES` in `coach/languages.py`: the code, the English name and the name in that language. The part of the code before `-` must be an ISO 639-1 code that [lingua](https://github.com/pemistahl/lingua-py) supports, because language detection uses it.
2. Optional: copy `frontend/locales/tr.json` to `frontend/locales/<code>.json` and translate the values. Missing keys show in English.
3. Optional: add the translations for scenario titles and phrase meanings in `scenarios.yaml`. Each one is a map by language code and falls back to `en`.
4. Add a stuck case in the new language to `bench/cases.yaml` (`kind: native`, `native: <code>`) and run the bench (see [AGENTS.md](AGENTS.md)).

Pull requests that add a language or fix a translation are welcome. Translations other than Turkish were machine-written, so a native speaker's review helps.

## Limits

- Text only. A voice mode (speech-to-text and text-to-speech running locally) is planned but not built.
- Only the Turkish interface and feedback were checked by a native speaker. The other languages are machine-translated, and the quality of their feedback depends on how well the analysis model writes that language.
- Right-to-left languages (Arabic, Hebrew, Persian) aren't supported yet.
- The analysis model can still be wrong. The code drops quotes that aren't in your messages and phrases you already practice, but a wrong grammar explanation can slip through.
- Only tested on one machine.

## License

MIT
