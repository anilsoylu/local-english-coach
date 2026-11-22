// Client for the FastAPI backend. The app is served from the same origin, so paths stay relative.

export interface Language {
  code: string;
  /** The language's name in itself, e.g. "Türkçe". */
  name: string;
  english_name: string;
}

export interface Profile {
  /** "" until the learner picks one on the first visit. */
  native_language: string;
}

export interface Scenario {
  id: string;
  title: string;
}

export interface WarmupChunk {
  phrase: string;
  meaning: string;
}

export interface Turn {
  role: "user" | "assistant";
  content: string;
  is_help?: number;
}

export interface SessionState {
  scenario: string;
  ended: boolean;
  turns: Turn[];
}

/** One row of the home screen's past sessions. */
export interface PastSession {
  id: number;
  scenario: string;
  /** In the native language, like `Scenario.title`. */
  title: string;
  started_at: string;
  /** Learner messages. */
  messages: number;
  /** Corrections in the report; null until there is a report. */
  errors: number | null;
  /** `pending`: queued or being analyzed. `none`: never ended, or its analysis failed. */
  report: "ready" | "pending" | "none";
}

export interface Metrics {
  user_turns?: number;
  avg_words?: number;
  median_response_s?: number | null;
  help_count?: number;
  native_turns?: number;
  mixed_turns?: number;
  chunks_offered?: number;
  chunks_used?: string[];
}

export interface Report {
  feedback?: string;
  errors?: { original: string; better: string; note: string }[];
  natural?: { original: string; natural: string }[];
  chunks?: { phrase: string; meaning: string; example: string }[];
}

/** Must match ERROR_MARK in coach/server.py: the server drops the turn and sends this instead of a reply. */
export const ERROR_MARK = "\n[error: ";

/** A response outside 2xx. Network failures stay plain `TypeError`s, so callers can tell the two apart. */
export class HttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

function ok(res: Response): Response {
  if (!res.ok) throw new HttpError(res.status);
  return res;
}

async function json<T>(res: Response): Promise<T> {
  return ok(res).json() as Promise<T>;
}

const send = (method: string, path: string, body?: unknown) =>
  fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
const post = (path: string, body?: unknown) => send("POST", path, body);

export const api = {
  languages: () => fetch("api/languages").then(json<Language[]>),
  profile: () => fetch("api/profile").then(json<Profile>),
  setProfile: (profile: Profile) =>
    send("PUT", "api/profile", profile).then(json<Profile>),
  scenarios: () => fetch("api/scenarios").then(json<Scenario[]>),
  start: (scenario: string) =>
    post("api/session", { scenario }).then(
      json<{ session_id: number; opening: string; warmup: WarmupChunk[] }>,
    ),
  sessions: (offset: number) =>
    fetch(`api/sessions?offset=${offset}`).then(
      json<{ sessions: PastSession[]; more: boolean }>,
    ),
  session: (id: number) => fetch(`api/session/${id}`).then(json<SessionState>),
  /** Ends the session if needed and queues its report; safe to repeat. */
  end: (id: number) => post(`api/session/${id}/end`).then(ok),
  /** `pending` is false when nothing is preparing a report (never ended, or the analysis failed). */
  report: (id: number) =>
    fetch(`api/session/${id}/report`).then(
      json<{
        ready: boolean;
        pending?: boolean;
        metrics?: Metrics;
        report?: Report;
      }>,
    ),
  warm: () => post("api/warm").catch(() => undefined),

  /** Streams the coach's reply, calling onChunk with the text so far. Throws if the model failed. */
  async message(
    id: number,
    text: string,
    responseMs: number | null,
    onChunk: (soFar: string) => void,
  ): Promise<string> {
    const res = await post(`api/session/${id}/message`, {
      text,
      response_ms: responseMs,
    });
    const body = ok(res).body;
    if (!body) throw new Error("no body");
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let reply = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      reply += decoder.decode(value, { stream: true });
      if (!reply.includes(ERROR_MARK)) onChunk(reply);
    }
    if (reply.includes(ERROR_MARK)) throw new Error("model");
    return reply.trim();
  },
};
