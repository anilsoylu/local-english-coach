// Client for the FastAPI backend. The app is served from the same origin, so paths stay relative.

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

export interface Metrics {
  user_turns?: number;
  avg_words?: number;
  median_response_s?: number | null;
  help_count?: number;
  turkish_turns?: number;
  mixed_turns?: number;
  chunks_offered?: number;
  chunks_used?: string[];
}

export interface Report {
  feedback_tr?: string;
  errors?: { original: string; better: string; note_tr: string }[];
  natural?: { original: string; natural: string }[];
  chunks?: { phrase: string; meaning_tr: string; example: string }[];
}

/** Must match ERROR_MARK in coach/server.py: the server drops the turn and sends this instead of a reply. */
export const ERROR_MARK = "\n[error: ";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

const post = (path: string, body?: unknown) =>
  fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

export const api = {
  scenarios: () => fetch("api/scenarios").then(json<Scenario[]>),
  start: (scenario: string) =>
    post("api/session", { scenario }).then(
      json<{ session_id: number; opening: string; warmup: WarmupChunk[] }>,
    ),
  session: (id: number) => fetch(`api/session/${id}`).then(json<SessionState>),
  end: (id: number) => post(`api/session/${id}/end`),
  report: (id: number) =>
    fetch(`api/session/${id}/report`).then(
      json<{ ready: boolean; metrics?: Metrics; report?: Report }>,
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
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
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
