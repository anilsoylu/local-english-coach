"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type Metrics,
  type Report,
  type Scenario,
  type WarmupChunk,
} from "@/lib/api";

export interface ChatMessage {
  id: number;
  from: "user" | "assistant";
  content: string;
  help?: boolean;
  streaming?: boolean;
  error?: boolean;
}

export type Phase = "idle" | "chat" | "report";

export type ReportState =
  | { status: "waiting" }
  | { status: "ready"; metrics: Metrics; report: Report }
  | { status: "timeout" };

/** localStorage can throw (private mode, blocked storage); it is a convenience, never required. */
const store = {
  get: (key: string) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set: (key: string, value: string | null) => {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {}
  },
};

const REPORT_POLL_MS = 3000;
const REPORT_POLLS = 120; // 6 minutes: the analysis model can take a while on the first run

let nextId = 1;
const msg = (m: Omit<ChatMessage, "id">): ChatMessage => ({
  id: nextId++,
  ...m,
});

export function useCoach() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenarioState] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [sid, setSid] = useState<number | null>(null);
  const [warmup, setWarmup] = useState<WarmupChunk[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [report, setReport] = useState<ReportState | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // When the coach finished its last reply: the learner's thinking time is measured from here.
  const readyAt = useRef<number | null>(null);
  // Bumped on reset/start so a poll loop from an earlier session stops writing state.
  const pollGen = useRef(0);

  const setScenario = useCallback((id: string) => {
    setScenarioState(id);
    store.set("scenario", id);
  }, []);

  const pollReport = useCallback(async (id: number) => {
    const gen = ++pollGen.current;
    setPhase("report");
    setReport({ status: "waiting" });
    for (let i = 0; i < REPORT_POLLS; i++) {
      const r = await api.report(id).catch(() => null);
      if (gen !== pollGen.current) return;
      if (r?.ready) {
        setReport({
          status: "ready",
          metrics: r.metrics ?? {},
          report: r.report ?? {},
        });
        return;
      }
      await new Promise((res) => setTimeout(res, REPORT_POLL_MS));
      if (gen !== pollGen.current) return;
    }
    setReport({ status: "timeout" });
  }, []);

  const enterChat = useCallback((id: number) => {
    setSid(id);
    store.set("sid", String(id));
    setPhase("chat");
    readyAt.current = performance.now();
  }, []);

  // First load: scenarios, then pick the session back up if a reload or sleep interrupted it.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await api.scenarios().catch(() => {
        setError("Sunucuya ulaşılamadı.");
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
      const s = await api.session(saved).catch(() => null);
      if (cancelled) return;
      if (!s) return store.set("sid", null);
      setScenarioState(s.scenario);
      setMessages(
        s.turns.map((t) =>
          msg({ from: t.role, content: t.content, help: Boolean(t.is_help) }),
        ),
      );
      if (s.ended) {
        setSid(saved);
        void pollReport(saved);
      } else enterChat(saved);
    })();
    return () => {
      cancelled = true;
    };
  }, [enterChat, pollReport]);

  // The model leaves VRAM after 15 idle minutes; load it whenever the page is opened or shown again.
  useEffect(() => {
    void api.warm();
    const onVisible = () =>
      document.visibilityState === "visible" && void api.warm();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  const start = useCallback(
    async (id: string = scenario) => {
      if (!id) return;
      pollGen.current++;
      setStarting(true);
      setError(null);
      setReport(null);
      try {
        const data = await api.start(id);
        setWarmup(data.warmup);
        setMessages([msg({ from: "assistant", content: data.opening })]);
        enterChat(data.session_id);
      } catch {
        setError("Seans başlatılamadı. Bir duruma tekrar dokun.");
      } finally {
        setStarting(false);
      }
    },
    [scenario, enterChat],
  );

  const send = useCallback(
    async (raw: string, isHelp = false) => {
      const text = raw.trim();
      if (!text || busy || sid === null) return;
      const responseMs =
        !isHelp && readyAt.current !== null
          ? Math.round(performance.now() - readyAt.current)
          : null;
      const mine = msg({ from: "user", content: text, help: isHelp });
      const reply = msg({ from: "assistant", content: "", streaming: true });
      setMessages((m) => [...m, mine, reply]);
      if (!isHelp) setDraft("");
      setBusy(true);
      const update = (patch: Partial<ChatMessage>) =>
        setMessages((m) =>
          m.map((x) => (x.id === reply.id ? { ...x, ...patch } : x)),
        );
      try {
        const full = await api.message(sid, text, responseMs, (soFar) =>
          update({ content: soFar }),
        );
        update({ content: full, streaming: false });
      } catch {
        // The server dropped this turn; take both bubbles out and give the text back for a retry.
        setMessages((m) =>
          m.filter((x) => x.id !== mine.id && x.id !== reply.id),
        );
        if (!isHelp) setDraft(text);
        setMessages((m) => [
          ...m,
          msg({
            from: "assistant",
            content: "Bağlantı hatası, mesajın kutuda. Tekrar gönder.",
            error: true,
          }),
        ]);
      } finally {
        setBusy(false);
        readyAt.current = performance.now();
      }
    },
    [busy, sid],
  );

  const end = useCallback(async () => {
    if (sid === null) return;
    const id = sid;
    await api.end(id).catch(() => undefined);
    void pollReport(id);
  }, [sid, pollReport]);

  // The session id stays stored until here, so a reload on the report screen shows the report again.
  const reset = useCallback(() => {
    pollGen.current++;
    store.set("sid", null);
    setPhase("idle");
    setSid(null);
    setMessages([]);
    setWarmup([]);
    setReport(null);
  }, []);

  return {
    scenarios,
    scenario,
    setScenario,
    phase,
    warmup,
    messages,
    busy,
    starting,
    report,
    draft,
    setDraft,
    error,
    start,
    send,
    end,
    reset,
  };
}
