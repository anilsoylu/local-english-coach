# English Coach web UI

The browser interface for English Coach: a Next.js app built as a static export. `bun run build` writes plain HTML, JS
and CSS to `out/`, and the FastAPI app (`coach/server.py`) serves that folder next to `/api` on the same origin. The
Docker image runs the build itself, so a normal install doesn't need Bun on the host.

```sh
bun install        # dependencies, from bun.lock
bun run dev        # dev server on http://localhost:3000
bun run build      # static export to out/
bun run lint       # Biome checks (bun run format applies the fixes)
```

The UI calls the API with relative paths (`api/...` in `lib/api.ts`), and `next.config.ts` has no proxy, because
rewrites don't work in a static export. That means the dev server on port 3000 renders the pages but its API calls
fail. To work against the real API, build and let FastAPI serve the result on one origin:

```sh
bun run build
cd .. && uv run python -m coach   # http://127.0.0.1:8765
```

`COACH_WEB` points the server at a different build folder (default `frontend/out`).

## Translations

UI strings live in `locales/<code>.json`, one file per native language, with codes from `coach/languages.py`.
English has no file: the English text is the default inside each component, and any key missing from a locale file
falls back to it. To add a language, copy `locales/tr.json` and translate the values. The full steps are in the
"Add a language" section of the main [README](../README.md).
