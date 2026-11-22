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
    expect(s).toEqual({ phase: "idle", starting: true, opening: null });
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
    expect(run([{ type: "opened", sid: 1 }])).toBe(IDLE);
    expect(run([{ type: "generate", sid: 1 }])).toBe(IDLE);
  });

  test("a second tap while starting doesn't start again", () => {
    const starting = run([{ type: "start" }]);
    expect(run([{ type: "start" }], starting)).toBe(starting);
    expect(run([{ type: "open", sid: 4 }], starting)).toBe(starting);
  });
});

describe("report screen and past sessions", () => {
  test("opening a past session shows its report screen", () => {
    let s = run([{ type: "open", sid: 4 }]);
    expect(s).toEqual({ phase: "idle", starting: true, opening: 4 });
    s = run([{ type: "opened", sid: 4 }], s);
    expect(s).toEqual({
      phase: "report",
      sid: 4,
      report: { status: "waiting" },
    });
  });

  test("a failed open goes back home", () => {
    expect(run([{ type: "open", sid: 4 }, { type: "startFailed" }])).toEqual(
      IDLE,
    );
  });

  test("only the session being opened lands on the report screen", () => {
    const s = run([
      { type: "open", sid: 4 },
      { type: "opened", sid: 5 },
    ]);
    expect(s).toMatchObject({ phase: "idle", opening: 4 });
  });

  test("a session without a report offers Generate report, which waits again", () => {
    let s = run([
      { type: "restored", sid: 3, ended: true },
      { type: "settled", sid: 3, report: { status: "missing" } },
    ]);
    expect(s).toMatchObject({ report: { status: "missing" } });
    s = run([{ type: "generate", sid: 3 }], s);
    expect(s).toEqual({
      phase: "report",
      sid: 3,
      report: { status: "waiting" },
    });
    s = run([{ type: "settled", sid: 3, report: ready }], s);
    expect(s).toEqual({ phase: "report", sid: 3, report: ready });
  });

  test("generate applies only to a missing report of the same session", () => {
    const missing = run([
      { type: "restored", sid: 3, ended: true },
      { type: "settled", sid: 3, report: { status: "missing" } },
    ]);
    expect(run([{ type: "generate", sid: 9 }], missing)).toBe(missing);
    const waiting = run([{ type: "restored", sid: 3, ended: true }]);
    expect(run([{ type: "generate", sid: 3 }], waiting)).toBe(waiting);
  });

  test("New session from the report screen: reset, then start", () => {
    const s = run([
      { type: "restored", sid: 3, ended: true },
      { type: "settled", sid: 3, report: ready },
      { type: "reset" },
      { type: "start" },
    ]);
    expect(s).toEqual({ phase: "idle", starting: true, opening: null });
  });
});

describe("known gaps, fixed", () => {
  test("a tap during the first load wins over the stored session", () => {
    // Tapped while restoring: the session that arrives later is ignored, before and after the new one exists.
    const starting = run([{ type: "start" }]);
    expect(run([{ type: "restored", sid: 3, ended: false }], starting)).toBe(
      starting,
    );
    const chat = run([{ type: "started", sid: 8, warmup }], starting);
    expect(run([{ type: "restored", sid: 3, ended: false }], chat)).toBe(chat);
  });

  test("a message to a session the server ended goes to the report", () => {
    // send() turns a 409 into `ended`.
    expect(
      run([
        { type: "restored", sid: 3, ended: false },
        { type: "ended", sid: 3 },
      ]),
    ).toEqual({ phase: "report", sid: 3, report: { status: "waiting" } });
  });
});
