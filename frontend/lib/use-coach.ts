"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  api,
  HttpError,
  type Metrics,
  type Report,
  type Scenario,
  type SessionState,
  type WarmupChunk,
} from "@/lib/api";
import { useMessages } from "@/lib/i18n";
import { store } from "@/lib/store";

export interface ChatMessage {
  id: number;
  from: "user" | "assistant";
  content: string;
  help?: boolean;
  streaming?: boolean;
  error?: boolean;
}

/** `missing`: nothing is preparing a report (the session was never ended, or its analysis failed).
 * `waiting` carries the code metrics once the server has them, before the model's report. */
export type ReportState =
  | { status: "waiting"; metrics?: Metrics }
  | { status: "ready"; metrics: Metrics; report: Report }
  | { status: "missing" }
  | { status: "timeout" };

/** The session lifecycle. Transitions are in `sessionReducer`; docs/state-machines.md has the table. */
export type Session =
  /** `starting` while a new session or a past one (`opening`) loads; the home screen is disabled meanwhile. */
  | { phase: "idle"; starting: boolean; opening: number | null }
  | { phase: "chat"; sid: number; warmup: WarmupChunk[]; busy: boolean }
  | { phase: "report"; sid: number; report: ReportState };

export type SessionEvent =
  | { type: "start" }
  | { type: "open"; sid: number }
  | { type: "startFailed" }
  | { type: "started"; sid: number; warmup: WarmupChunk[] }
  | { type: "opened"; sid: number }
  | { type: "restored"; sid: number; ended: boolean }
  | { type: "busy"; busy: boolean }
  | { type: "ended"; sid: number }
  | { type: "metrics"; sid: number; metrics: Metrics }
  | {
      type: "settled";
      sid: number;
      report: Exclude<ReportState, { status: "waiting" }>;
    }
  | { type: "generate"; sid: number }
  | { type: "reset" };

export const IDLE: Session = { phase: "idle", starting: false, opening: null };

const awaitReport = (sid: number): Session => ({
  phase: "report",
  sid,
  report: { status: "waiting" },
});

/** Events that don't apply to the current state leave it unchanged. */
export function sessionReducer(s: Session, e: SessionEvent): Session {
  switch (e.type) {
    case "start":
      return s.phase === "idle" && !s.starting
        ? { phase: "idle", starting: true, opening: null }
        : s;
    case "open":
      return s.phase === "idle" && !s.starting
        ? { phase: "idle", starting: true, opening: e.sid }
        : s;
    case "startFailed":
      return s.phase === "idle" ? IDLE : s;
    case "started":
      return { phase: "chat", sid: e.sid, warmup: e.warmup, busy: false };
    case "opened":
      return s.phase === "idle" && s.opening === e.sid ? awaitReport(e.sid) : s;
    // Only onto an untouched home screen: a tap during the first load wins over the stored session.
    case "restored":
      if (s.phase !== "idle" || s.starting) return s;
      return e.ended
        ? awaitReport(e.sid)
        : { phase: "chat", sid: e.sid, warmup: [], busy: false };
    case "busy":
      return s.phase === "chat" ? { ...s, busy: e.busy } : s;
    case "ended":
      return s.phase === "chat" && s.sid === e.sid ? awaitReport(e.sid) : s;
    case "metrics":
      return s.phase === "report" &&
        s.sid === e.sid &&
        s.report.status === "waiting"
        ? { ...s, report: { status: "waiting", metrics: e.metrics } }
        : s;
    case "settled":
      return s.phase === "report" &&
        s.sid === e.sid &&
        s.report.status === "waiting"
        ? { ...s, report: e.report }
        : s;
    case "generate":
      return s.phase === "report" &&
        s.sid === e.sid &&
        s.report.status === "missing"
        ? awaitReport(e.sid)
        : s;
    case "reset":
      return IDLE;
  }
}

const REPORT_POLL_MS = 1000;
const REPORT_POLLS = 360; // 6 minutes: the analysis model can take a while on the first run

let nextId = 1;
const msg = (m: Omit<ChatMessage, "id">): ChatMessage => ({
  id: nextId++,
  ...m,
});

const DEFAULTS = {
  unreachable: "Could not reach the server.",
  startFailed: "Could not start the session. Tap a situation again.",
  sendFailed: "Connection error, your message is in the box. Send it again.",
  endFailed:
    "Could not end the session. Check your connection and tap End again.",
  openFailed: "Could not open that session. Try again.",
  generateFailed:
    "Could not ask for the report. Check your connection and try again.",
};

const toMessages = (s: SessionState) =>
  s.turns.map((t) =>
    msg({ from: t.role, content: t.content, help: Boolean(t.is_help) }),
  );

/** Sent by the "I'm stuck" button; the server counts it as a help turn. */
export const HELP_TEXT = "help";

export function useCoach() {
  const t = useMessages("session", DEFAULTS);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenarioState] = useState("");
  const [session, dispatch] = useReducer(sessionReducer, IDLE);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // When the coach finished its last reply: the learner's thinking time is measured from here.
  const readyAt = useRef<number | null>(null);
  // Set by the first start or open, so a stored session that loads after the tap doesn't replace its messages.
  const acted = useRef(false);

  const setScenario = useCallback((id: string) => {
    setScenarioState(id);
    store.set("scenario", id);
  }, []);

  // First load: scenarios, then pick the session back up if a reload or sleep interrupted it.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await api.scenarios().catch(() => {
        setError(t("unreachable"));
        return [];
      });
      if (cancelled) return;
      setScenarios(list);
      const last = store.get("scenario");
      setScenarioState(
        list.some((s) => s.id === last)
          ? (last as string)
          : (list[0]?.id ?? ""),
      );
      const saved = Number(store.get("sid"));
      if (!saved) return;
      let s: SessionState;
      try {
        s = await api.session(saved);
      } catch (e) {
        // Forget the session only when the server doesn't know it; an unreachable server keeps it for the next load.
        if (
          !cancelled &&
          !acted.current &&
          e instanceof HttpError &&
          e.status === 404
        )
          store.set("sid", null);
        return;
      }
      if (cancelled || acted.current) return;
      setScenarioState(s.scenario);
      setMessages(toMessages(s));
      if (!s.ended) readyAt.current = performance.now();
      dispatch({ type: "restored", sid: saved, ended: s.ended });
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  // The model leaves VRAM after 15 idle minutes; load it whenever the page is opened or shown again.
  useEffect(() => {
    void api.warm();
    const onVisible = () =>
      document.visibilityState === "visible" && void api.warm();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  const awaiting =
    session.phase === "report" && session.report.status === "waiting"
      ? session.sid
      : null;
  useEffect(() => {
    if (awaiting === null) return;
    const sid = awaiting;
    let cancelled = false;
    (async () => {
      let metricsShown = false;
      for (let i = 0; i < REPORT_POLLS; i++) {
        const r = await api.report(sid).catch(() => null);
        if (cancelled) return;
        if (r?.ready) {
          dispatch({
            type: "settled",
            sid,
            report: {
              status: "ready",
              metrics: r.metrics ?? {},
              report: r.report ?? {},
            },
          });
          return;
        }
        if (r && !r.pending) {
          dispatch({ type: "settled", sid, report: { status: "missing" } });
          return;
        }
        if (r?.metrics && !metricsShown) {
          metricsShown = true;
          dispatch({ type: "metrics", sid, metrics: r.metrics });
        }
        await new Promise((res) => setTimeout(res, REPORT_POLL_MS));
        if (cancelled) return;
      }
      dispatch({ type: "settled", sid, report: { status: "timeout" } });
    })();
    return () => {
      cancelled = true;
    };
  }, [awaiting]);

  const start = useCallback(
    async (id: string = scenario) => {
      if (!id) return;
      acted.current = true;
      dispatch({ type: "start" });
      setError(null);
      try {
        const data = await api.start(id);
        setMessages([msg({ from: "assistant", content: data.opening })]);
        store.set("sid", String(data.session_id));
        readyAt.current = performance.now();
        dispatch({
          type: "started",
          sid: data.session_id,
          warmup: data.warmup,
        });
      } catch {
        setError(t("startFailed"));
        dispatch({ type: "startFailed" });
      }
    },
    [scenario, t],
  );

  const chatSid = session.phase === "chat" ? session.sid : null;
  const busy = session.phase === "chat" && session.busy;

  const send = useCallback(
    async (raw: string, isHelp = false) => {
      const text = raw.trim();
      if (!text || busy || chatSid === null) return;
      const responseMs =
        !isHelp && readyAt.current !== null
          ? Math.round(performance.now() - readyAt.current)
          : null;
      const mine = msg({ from: "user", content: text, help: isHelp });
      const reply = msg({ from: "assistant", content: "", streaming: true });
      setMessages((m) => [...m, mine, reply]);
      if (!isHelp) setDraft("");
      dispatch({ type: "busy", busy: true });
      const update = (patch: Partial<ChatMessage>) =>
        setMessages((m) =>
          m.map((x) => (x.id === reply.id ? { ...x, ...patch } : x)),
        );
      try {
        const full = await api.message(chatSid, text, responseMs, (soFar) =>
          update({ content: soFar }),
        );
        update({ content: full, streaming: false });
      } catch (e) {
        // The server dropped this turn; take both bubbles out and give the text back for a retry.
        setMessages((m) =>
          m.filter((x) => x.id !== mine.id && x.id !== reply.id),
        );
        // 409: the server already ended the session (closed as stale while the laptop slept), so a retry can't work.
        if (e instanceof HttpError && e.status === 409) {
          dispatch({ type: "ended", sid: chatSid });
          return;
        }
        if (!isHelp) setDraft(text);
        setMessages((m) => [
          ...m,
          msg({
            from: "assistant",
            content: t("sendFailed"),
            error: true,
          }),
        ]);
      } finally {
        dispatch({ type: "busy", busy: false });
        readyAt.current = performance.now();
      }
    },
    [busy, chatSid, t],
  );

  // Stays in the chat when the request fails: the session is still open on the server.
  const end = useCallback(async () => {
    if (chatSid === null) return;
    try {
      await api.end(chatSid);
      dispatch({ type: "ended", sid: chatSid });
    } catch {
      setMessages((m) => [
        ...m,
        msg({ from: "assistant", content: t("endFailed"), error: true }),
      ]);
    }
  }, [chatSid, t]);

  /** A past session from the home screen, on the report screen. With `generate`, its report is asked for first.
   * Not stored as `sid`: a reload goes back home. */
  const open = useCallback(
    async (sid: number, generate = false) => {
      acted.current = true;
      dispatch({ type: "open", sid });
      setError(null);
      try {
        if (generate) await api.end(sid);
        const s = await api.session(sid);
        setScenarioState(s.scenario);
        setMessages(toMessages(s));
        dispatch({ type: "opened", sid });
      } catch {
        setError(t(generate ? "generateFailed" : "openFailed"));
        dispatch({ type: "startFailed" });
      }
    },
    [t],
  );

  const missingSid =
    session.phase === "report" && session.report.status === "missing"
      ? session.sid
      : null;

  /** "Generate report" on the report screen. */
  const generate = useCallback(async () => {
    if (missingSid === null) return;
    setError(null);
    try {
      await api.end(missingSid);
      dispatch({ type: "generate", sid: missingSid });
    } catch {
      setError(t("generateFailed"));
    }
  }, [missingSid, t]);

  // The session id stays stored until here, so a reload on the report screen shows the report again.
  const reset = useCallback(() => {
    store.set("sid", null);
    setMessages([]);
    setError(null);
    dispatch({ type: "reset" });
  }, []);

  /** "New session" on the report screen: the same scenario again, right away. */
  const restart = useCallback(() => {
    reset();
    void start();
  }, [reset, start]);

  return {
    scenarios,
    scenario,
    setScenario,
    session,
    messages,
    draft,
    setDraft,
    error,
    start,
    send,
    end,
    open,
    generate,
    reset,
    restart,
  };
}
