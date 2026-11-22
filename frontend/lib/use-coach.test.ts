import { describe, expect, test } from "bun:test";
import {
  IDLE,
  type Session,
  type SessionEvent,
  sessionReducer,
} from "@/lib/use-coach";

const run = (events: SessionEvent[], from: Session = IDLE) =>
  events.reduce(sessionReducer, from);

const warmup = [{ phrase: "To be honest, ...", meaning: "" }];
const ready = {
  status: "ready" as const,
  metrics: { user_turns: 2 },
  report: { feedback: "ok" },
};

describe("session lifecycle", () => {
  test("a full session: start, chat, end, report, reset", () => {
    let s = run([{ type: "start" }]);
    expect(s).toEqual({ phase: "idle", starting: true });
    s = run([{ type: "started", sid: 7, warmup }], s);
    expect(s).toEqual({ phase: "chat", sid: 7, warmup, busy: false });
    s = run([{ type: "busy", busy: true }], s);
    expect(s).toMatchObject({ phase: "chat", busy: true });
    s = run(
      [
        { type: "busy", busy: false },
        { type: "ended", sid: 7 },
      ],
      s,
    );
    expect(s).toEqual({
      phase: "report",
      sid: 7,
      report: { status: "waiting" },
    });
    s = run([{ type: "settled", sid: 7, report: ready }], s);
    expect(s).toEqual({ phase: "report", sid: 7, report: ready });
    expect(run([{ type: "reset" }], s)).toEqual(IDLE);
  });

  test("a failed start goes back to the picker", () => {
    expect(run([{ type: "start" }, { type: "startFailed" }])).toEqual(IDLE);
  });

  test("a reload resumes an open session in chat without warm-up", () => {
    expect(run([{ type: "restored", sid: 3, ended: false }])).toEqual({
      phase: "chat",
      sid: 3,
      warmup: [],
      busy: false,
    });
  });

  test("a reload of an ended session waits for its report", () => {
    expect(run([{ type: "restored", sid: 3, ended: true }])).toEqual({
      phase: "report",
      sid: 3,
      report: { status: "waiting" },
    });
  });

  test("polling gives up with a timeout, which is final", () => {
    const s = run([
      { type: "restored", sid: 3, ended: true },
      { type: "settled", sid: 3, report: { status: "timeout" } },
      { type: "settled", sid: 3, report: ready },
    ]);
    expect(s).toMatchObject({ report: { status: "timeout" } });
  });

  test("a report for another session is ignored", () => {
    const s = run([
      { type: "restored", sid: 3, ended: true },
      { type: "settled", sid: 4, report: ready },
    ]);
    expect(s).toMatchObject({ sid: 3, report: { status: "waiting" } });
  });

  test("a reply finishing after the session ended doesn't touch the report", () => {
    const s = run([
      { type: "started", sid: 7, warmup },
      { type: "ended", sid: 7 },
      { type: "busy", busy: false },
    ]);
    expect(s).toEqual({
      phase: "report",
      sid: 7,
      report: { status: "waiting" },
    });
  });

  test("events from other phases leave the state alone", () => {
    expect(run([{ type: "ended", sid: 1 }])).toBe(IDLE);
    expect(run([{ type: "busy", busy: true }])).toBe(IDLE);
    expect(run([{ type: "settled", sid: 1, report: ready }])).toBe(IDLE);
  });
});
