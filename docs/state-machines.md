# State machines

The lifecycles that span more than one function. Update this file when a transition changes.

## Session in the UI

Owner: `sessionReducer` and the `Session` type in `frontend/lib/use-coach.ts`. `useCoach` runs the side effects
(API calls, the stored session id, report polling); `coach-app.tsx` renders from `session.phase`.

| State | Data | Screen |
|---|---|---|
| `idle` | `starting` while `POST /api/session` runs | scenario picker (disabled while starting) |
| `chat` | `sid`, `warmup`, `busy` while a reply streams | messages, warm-up card, input, End |
| `report` | `sid`, `report`: `waiting`, `ready` or `timeout` | messages, report card, New session |

| Event | From | To | Sent by |
|---|---|---|---|
| `start` | `idle` | `idle`, starting | `start()` |
| `startFailed` | `idle` | `idle` | `start()` when the request fails (error shown on the picker) |
| `started` | any | `chat` with the warm-up | `start()` when the session exists |
| `restored` | any | `chat` (no warm-up) or `report` waiting | first load, from the stored `sid` |
| `busy` | `chat` | `chat` | `send()` before and after the streamed reply |
| `ended` | `chat` with the same `sid` | `report` waiting | `end()` after `POST /end`, failed or not |
| `settled` | `report` waiting, same `sid` | `report` ready or timeout | the polling effect |
| `reset` | any | `idle` | New session |

Events from any other state are ignored. Invariants:

- A `sid` exists only in `chat` and `report`, and `localStorage["sid"]` holds it in both. It is written when a
  session starts and cleared on `reset` or when the server no longer knows it, so a reload lands in the same state.
- Report polling runs only in `report` waiting: an effect keyed on that `sid` polls `GET /report` every 3 s, at most
  120 times, then sends `timeout`. Leaving the state cancels it. `timeout` is final until a reload.
- Ending takes two taps: `EndButton` in `coach-app.tsx` arms on the first tap and disarms after 3 s. End stays
  disabled while a reply streams and before the learner has written anything.
- Messages live outside the machine (they stream in piece by piece). `start` replaces them, `restored` loads them
  from the server, `reset` clears them.

Next steps fit as new events: opening a past report from the home screen is `restored` with `ended: true`, and
showing the code metrics before the model's report is a `waiting` that carries metrics.

## Session row on the server

Owner: the `sessions` table (`coach/memory.py`), written by `coach/server.py` and `coach/analyze.py`.

| State | Columns | API |
|---|---|---|
| active | `ended_at` null | `GET /session` `ended: false`; `POST /message` accepted |
| ended | `ended_at` set, `analyzed_at` null | `ended: true`; `/message` 409; `/report` `ready: false` |
| analyzed | `analyzed_at`, `metrics`, `report` set | `/report` `ready: true`; listed by `/api/progress` |

| Transition | Where |
|---|---|
| active → ended | `POST /end` (only when still active, so repeating it is harmless), which queues the analysis |
| active → ended | `retry_pending` at server start, when the last turn is older than `STALE_AFTER` (2 h) |
| ended → analyzed | `_analyze`: under 2 learner turns it stores the metrics and `{}` as the report without a model call |
| ended → ended | `analyze_session` logs a failed analysis; `retry_pending` tries again on the next start |

`analysis_slot` runs one analysis at a time per process and loads the chat model again afterwards.
`python -m coach.chats import` is a separate process, so it doesn't wait for a running session analysis.

## Native language

Owner: `useNativeLanguage` in `frontend/lib/use-native-language.ts`. `code` is `null` while unknown (only the page
frame renders), `""` until the learner picks one (onboarding), then the code. The cached code renders at once and
the server profile wins when it differs; `applyGen` lets the newest of the two loads win.

## Known invalid transitions

Reachable today and left for their own fix, since fixing them changes behavior:

1. **A tap during the first load starts a second session.** The picker is live as soon as the scenarios arrive,
   while the stored `sid` is still being fetched. Tapping a scenario then starts a new session, and the `restored`
   that follows switches the screen to the old one and loads its messages. Fix: accept `restored` only in `idle`
   when not starting, and keep messages from being replaced after that.
2. **A message to a session the server ended shows "Connection error".** `POST /message` answers 409 once
   `retry_pending` closed a stale session (laptop asleep over a server restart), and `send()` treats that like a
   network error, so every retry fails the same way. Fix: on 409, go to `report` waiting.
3. **An unreachable server on reload forgets the session.** The first load clears the stored `sid` when
   `GET /session` fails for any reason, not only 404, so the open session can't be resumed after the network returns.
   Fix: clear it only on 404.
4. **A failed `POST /end` waits six minutes for a report that never comes.** `end()` ignores the error and the
   session stays active on the server. After the timeout, a reload goes back to the chat.
