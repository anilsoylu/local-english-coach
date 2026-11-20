# English Coach

A local chat partner for practicing everyday and work English. It's built for Turkish speakers who understand English but freeze when they have to put a sentence together. The models run on your own GPU through [Ollama](https://ollama.com), and your conversations stay in a SQLite file on your machine.

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

The coach doesn't stop you to explain grammar. It says your sentence back the way a native speaker would ("we have problem" becomes "you have a problem") and keeps the conversation going. If you get stuck, you can write in Turkish or press **Takıldım** ("I'm stuck") to get the English version or the first few words. When you end the session, a second, larger model reviews the whole chat and gives you:

- the 3 or 4 mistakes that matter most, each with a one-line explanation in Turkish
- a more natural way to say some of your correct but stiff sentences
- 2 or 3 new phrases for the situations you were in

The next session starts with the phrases that are due for review (spaced repetition), and the coach steers the conversation so you get a chance to use them.

## Requirements

- Linux with an NVIDIA GPU. Tested on an RTX 3070 with 8 GB of VRAM, 32 GB of RAM, Ubuntu 26.04. Smaller cards get smaller models, but those configurations are untested.
- Docker Engine with the compose plugin. Docker Desktop doesn't work here: it runs containers in a VM, so `network_mode: host` can't reach Ollama on the host, and it only starts after you log in to the desktop. If you have both, use the Engine with `docker context use default` (or `DOCKER_CONTEXT=default`).
- About 25 GB of disk space for the models

## Install

```sh
git clone https://github.com/anilsoylu/english-coach.git
cd english-coach
sudo ./setup.sh
```

The script installs Ollama if it's missing, tunes it, picks models for your VRAM, pulls them and starts the app with Docker Compose. The app restarts on its own after a reboot. Then open http://127.0.0.1:8765.

To use it from your phone or laptop, put the machine on [Tailscale](https://tailscale.com) and run `sudo ./setup.sh --tailscale`. The app keeps listening on 127.0.0.1, and [Tailscale Serve](https://tailscale.com/kb/1312/serve) shares it with your tailnet only, at `https://<machine-name>.<tailnet>.ts.net`. HTTPS needs the tailnet's HTTPS certificates. Turn them on once in the admin console under DNS. Until you do, the script serves plain HTTP on port 8765 inside the tailnet and prints the link to turn HTTPS on.

On a Mac, open that address in Safari and choose File > Add to Dock to get a standalone app window. On a phone, the keyboard's microphone button lets you speak your answers instead of typing them. If you reload the page or the laptop sleeps, the open session comes back.

## Personalize

Copy `config.example.yaml` to `config.yaml` (setup.sh creates a blank one) and fill in your name and a sentence or two about your work. The coach uses them in scenarios and small talk. Every field is optional. Without a name the coach just says "Hi", and without an `about` line it doesn't get a profile at all.

Scenarios live in `scenarios.yaml`: the coach's role, the situation, its opening line and a few phrases to practice. The defaults are aimed at a freelance developer (client calls, price talks, reporting a delay, stand-ups, a job interview), plus small talk and travel. Add your own in the same format.

## How the models were chosen

Chat model candidates were run against 30 fixed learner messages with typical Turkish-speaker mistakes (`bench/cases.yaml`). The automatic checks cover reply length, one question per reply, no explicit correction, no Turkish in the reply, no assistant-style phrases, and whether the reply recasts the mistake. Results on the RTX 3070 with the current prompt:

| Model | Checks passed | First token | Speed | VRAM | Verdict |
|---|---|---|---|---|---|
| gemma4:e4b | 99.7% | 0.04 s | 161 tok/s | 5.1 GB | chosen |
| qwen3.5:4b | 99.4% | 0.20 s | 109 tok/s | 4.2 GB | rejected: made grammar mistakes in its own replies |
| qwen3.5:9b | 95.5% | 0.23 s | 69 tok/s | 6.7 GB | fewer recasts, skipped "try saying that" |
| ministral-3:8b | 85.3% | 0.03 s | 72 tok/s | 6.7 GB | rejected |
| lfm2.5:8b | 57.1% (first prompt) | 0.07 s | 251 tok/s | 5.6 GB | replies too long |

The prompt mattered more than the model. With the first prompt, even the best models recast only 57% of mistakes. Most of the time they reacted to the content and changed the subject. Telling them to echo the learner's sentence first raised that to 96 to 100%.

The end-of-session review runs once per session, so it can use a bigger model. Three candidates reviewed the same three transcripts (`bench/transcripts.yaml`):

| Model | Average time | Result |
|---|---|---|
| gemma4:26b-a4b | 25 s | chosen: caught the most real mistakes and explained each one correctly |
| gemma4:12b | 29 s | clean Turkish, but once praised verbs the learner had gotten wrong |
| qwen3.5:9b | 16 s | broken Turkish and invented grammar rules |

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
docker compose --profile test run --rm test python bench/run.py gemma4:e4b
docker compose --profile test run --rm test python bench/analysis.py gemma4:26b-a4b
```

[AGENTS.md](AGENTS.md) has the rules and the tuning procedure for AI coding agents. It also works as a checklist if you're moving the project to different hardware by hand.

## Limits

- Text only. A voice mode (speech-to-text and text-to-speech running locally) is planned but not built.
- The help and feedback features assume a Turkish speaker.
- The analysis model can still be wrong. The code drops quotes that aren't in your messages and phrases you already practice, but a wrong grammar explanation can slip through.
- Only tested on one machine.

## License

MIT
