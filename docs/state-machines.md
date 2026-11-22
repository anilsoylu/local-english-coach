# State machines

The lifecycles that span more than one function. Update this file when a transition changes.

## Session in the UI

Owner: `sessionReducer` and the `Session` type in `frontend/lib/use-coach.ts`. `useCoach` runs the side effects
(API calls, the stored session id, report polling); `coach-app.tsx` renders from `session.phase`.

| State | Data | Screen |
|---|---|---|
| `idle` | `starting` while `POST /api/session` or a past session loads; `opening` is that past session | home: scenario picker and past sessions (disabled while starting) |
| `chat` | `sid`, `warmup`, `busy` while a reply streams | messages, warm-up card, input, End |
| `report` | `sid`, `report`: `waiting` (with the metrics once the server has them), `ready`, `missing` or `timeout` | report screen: report card, "Show conversation" (folded), Home, New session |

`missing` means nothing is preparing a report: the session was never ended, or its analysis failed. The report card
then offers "Generate report".

| Event | From | To | Sent by |
|---|---|---|---|
| `start` | `idle`, not starting | `idle`, starting | `start()`: a scenario tap, or New session right after `reset` |
| `open` | `idle`, not starting | `idle`, starting, `opening` | `open()`: a past session or its "Generate report" on the home screen |
| `startFailed` | `idle` | `idle` | `start()` or `open()` when a request fails (error shown on the home screen) |
| `started` | any | `chat` with the warm-up | `start()` when the session exists |
| `opened` | `idle` opening the same `sid` | `report` waiting | `open()` once the session's turns are loaded (after `POST /end` for "Generate report") |
| `restored` | `idle`, not starting | `chat` (no warm-up) or `report` waiting | first load, from the stored `sid` |
| `busy` | `chat` | `chat` | `send()` before and after the streamed reply |
| `ended` | `chat` with the same `sid` | `report` waiting | `end()` after `POST /end` succeeds; `send()` on a 409 (the server already ended it) |
| `metrics` | `report` waiting, same `sid` | `report` waiting with the metrics | the polling effect, the first time `GET /report` returns metrics before the report |
| `settled` | `report` waiting, same `sid` | `report` ready, missing or timeout | the polling effect |
| `generate` | `report` missing, same `sid` | `report` waiting | "Generate report" on the report card, after `POST /end` succeeds |
| `reset` | any | `idle` | Home (the button or the app name), and New session before its `start` |

Events from any other state are ignored. Invariants:

- `localStorage["sid"]` holds the session a reload should bring back: written when a session starts, cleared on
  `reset` or when `GET /session` answers 404. An unreachable server leaves it, so the session resumes once the
  network returns. A past session opened from home is not stored; a reload goes home.
- The first load is superseded by the learner: once `start()` or `open()` runs, the stored session that arrives
  afterwards is dropped (its messages too), and the reducer refuses `restored` unless the home screen is untouched.
- Report polling runs only in `report` waiting: an effect keyed on that `sid` polls `GET /report` every 1 s, at most
  360 times (6 minutes). `ready` settles as ready; `ready: false` with `pending: false` settles as missing; the 360th
  poll as timeout. Metrics in a pending answer are sent once as `metrics`, so the report card shows the stats grid
  above the waiting line ("about 30 seconds" and the seconds so far). Leaving the state cancels it. `timeout` is final
  until a reload.
- Ending takes two taps: `EndButton` in `coach-app.tsx` arms on the first tap and disarms after 3 s. End stays
  disabled while a reply streams and before the learner has written anything. A failed `POST /end` leaves the chat
  as it was and adds an error message; End can be tapped again.
- The app name in the header goes home on the home and report screens. In the chat it is plain text: leaving would
  abandon the session, so End is the way out.
- Messages live outside the machine (they stream in piece by piece). `start` replaces them, `restored` and `open`
  load them from the server, `reset` clears them.

## Session row on the server

Owner: the `sessions` table (`coach/memory.py`), written by `coach/server.py` and `coach/analyze.py`. The
in-process queue in `coach/analyze.py` (`queue_analysis`, `is_queued`) tracks which sessions have an analysis job.

| State | Columns, queue | API |
|---|---|---|
| active | `ended_at` null | `GET /session` `ended: false`; `POST /message` accepted; listed with report `none` |
| ended, analyzing | `ended_at` set, `analyzed_at` null, `metrics` set, queued | `/message` 409; `/report` `ready: false, pending: true` with `metrics`; listed as `pending` |
| ended, no report | `ended_at` set, `analyzed_at` null, not queued (`metrics` set if it was ever queued) | `/report` `ready: false, pending: false` (with `metrics` when set); listed as `none` |
| analyzed | `analyzed_at`, `metrics`, `report` set | `/report` `ready: true`; listed as `ready`, and by `/api/progress` |

`GET /api/sessions` lists only sessions with at least one learner turn, newest first, `limit` (1 to 50, default 10)
from `offset`.

| Transition | Where |
|---|---|
| active → analyzing | `POST /end`: ends the session and queues the analysis; `queue_analysis` stores the metrics before the job starts |
| active → analyzing | `retry_pending` at server start, when the last turn is older than `STALE_AFTER` (2 h) |
| no report → analyzing | `POST /end` again ("Generate report"), or `retry_pending` at the next start |
| analyzing → analyzed | `_analyze`: under 2 learner turns it stores the metrics and `{}` as the report without a model call |
| analyzing → no report | the model call fails; `analyze_session` logs it and leaves the queue |

`POST /end` is idempotent: on an analyzing or analyzed session it changes nothing, and on an unknown one it answers
404. Two guards keep a session from being analyzed twice. `queue_analysis` skips a session that is already queued or
running, so repeated End taps, "Generate report" and the startup retry add one job at most. `_analyze` runs under
the `analysis_slot` lock and returns at once when `analyzed_at` is set, so a job queued just as the previous one
finished does nothing. The Leitner reviews of the offered phrases are written in the same transaction as
`analyzed_at`, so a failed analysis that is retried doesn't move them twice.

`analysis_slot` runs one analysis at a time per process and loads the chat model again afterwards.
`python -m coach.chats import` is a separate process, so it doesn't wait for a running session analysis.

## Native language

Owner: `useNativeLanguage` in `frontend/lib/use-native-language.ts`. `code` is `null` while unknown (only the page
frame renders), `""` until the learner picks one (onboarding), then the code. The cached code renders at once and
the server profile wins when it differs; `applyGen` lets the newest of the two loads win.

## Known invalid transitions

None known. When one turns up, list it here with how to reach it and the fix, until it is fixed.
