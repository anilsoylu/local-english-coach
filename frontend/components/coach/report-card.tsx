"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { ThinkingShimmer } from "@/components/agents/loading-states/thinking-shimmer";
import { ErrorNote } from "@/components/coach/pick-list";
import { Button } from "@/components/ui/button";
import type { Metrics } from "@/lib/api";
import { useMessages } from "@/lib/i18n";
import { COARSE_BUTTON } from "@/lib/touch";
import type { ReportState } from "@/lib/use-coach";

const DEFAULTS = {
  title: "Session report",
  waiting: "Analyzing, about 30 seconds…",
  elapsed: "{seconds} s",
  timeout:
    "The report is still being prepared. Reload the page in a little while, it shows up here when ready.",
  messages: "messages",
  avgWords: "average words",
  responseTime: "response time (s)",
  stuck: "times stuck",
  chunksUsed: "phrases used",
  corrections: "Corrections",
  natural: "More natural wording",
  newChunks: "New phrases",
  tooShort: "The session was too short to analyze.",
  missing: "This session has no report yet.",
  generate: "Generate report",
};

function Stat({
  value,
  label,
}: {
  value: string | number | null | undefined;
  label: string;
}) {
  if (value === null || value === undefined) return null;
  return (
    <div className="rounded-xl bg-muted/60 px-3 py-2.5">
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

interface ReportCardProps {
  state: ReportState;
  /** "Generate report", shown while the report is missing. */
  onGenerate: () => void;
  error: string | null;
}

export function ReportCard({ state, onGenerate, error }: ReportCardProps) {
  const reduce = useReducedMotion();
  const t = useMessages("reportCard", DEFAULTS);
  return (
    <motion.section
      aria-label={t("title")}
      data-testid="report"
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
      className="flex flex-col gap-6 rounded-2xl border border-border bg-card p-5"
    >
      <h2 className="text-base font-semibold">{t("title")}</h2>
      {state.status === "waiting" && (
        <>
          {state.metrics && <Stats metrics={state.metrics} />}
          <Waiting />
        </>
      )}
      {state.status === "timeout" && (
        <p className="text-sm text-muted-foreground">{t("timeout")}</p>
      )}
      {state.status === "missing" && (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted-foreground">{t("missing")}</p>
          <Button
            size="sm"
            onClick={onGenerate}
            data-testid="generate"
            className={COARSE_BUTTON}
          >
            {t("generate")}
          </Button>
        </div>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      {state.status === "ready" && (
        <ReportBody metrics={state.metrics} report={state.report} />
      )}
    </motion.section>
  );
}

/** The model's part of the report is on its way: the expected wait and the seconds so far. */
function Waiting() {
  const t = useMessages("reportCard", DEFAULTS);
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="flex items-baseline gap-3 text-sm" data-testid="waiting">
      <ThinkingShimmer>{t("waiting")}</ThinkingShimmer>
      <span
        className="tabular-nums text-muted-foreground"
        data-testid="elapsed"
      >
        {t("elapsed", { seconds })}
      </span>
    </div>
  );
}

/** Computed in code, so they show while the model still works on the rest. */
function Stats({ metrics: m }: { metrics: Metrics }) {
  const t = useMessages("reportCard", DEFAULTS);
  const stuck =
    (m.help_count ?? 0) + (m.native_turns ?? 0) + (m.mixed_turns ?? 0);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" data-testid="stats">
      <Stat value={m.user_turns} label={t("messages")} />
      <Stat value={m.avg_words} label={t("avgWords")} />
      <Stat value={m.median_response_s} label={t("responseTime")} />
      <Stat value={stuck} label={t("stuck")} />
      <Stat
        value={`${m.chunks_used?.length ?? 0}/${m.chunks_offered ?? 0}`}
        label={t("chunksUsed")}
      />
    </div>
  );
}

function ReportBody({
  metrics,
  report: r,
}: Pick<Extract<ReportState, { status: "ready" }>, "metrics" | "report">) {
  const t = useMessages("reportCard", DEFAULTS);
  const empty = !r.feedback && !r.errors?.length;
  return (
    <>
      <Stats metrics={metrics} />
      {r.feedback && (
        <p className="text-pretty leading-relaxed">{r.feedback}</p>
      )}
      {!!r.errors?.length && (
        <Section title={t("corrections")}>
          <ul className="flex flex-col gap-4">
            {r.errors.map((e) => (
              <li key={e.original} className="flex flex-col gap-1">
                <span
                  lang="en"
                  className="text-sm text-muted-foreground line-through decoration-destructive/60"
                >
                  {e.original}
                </span>
                <span lang="en" className="font-medium text-primary">
                  {e.better}
                </span>
                <span className="text-sm text-muted-foreground">{e.note}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {!!r.natural?.length && (
        <Section title={t("natural")}>
          <ul className="flex flex-col gap-3">
            {r.natural.map((n) => (
              <li key={n.original} className="flex flex-col gap-1">
                <span lang="en" className="text-sm text-muted-foreground">
                  {n.original}
                </span>
                <span lang="en" className="font-medium">
                  {n.natural}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {!!r.chunks?.length && (
        <Section title={t("newChunks")}>
          <ul className="flex flex-col gap-3">
            {r.chunks.map((c) => (
              <li key={c.phrase} className="flex flex-col gap-0.5">
                <span>
                  <span lang="en" className="font-medium">
                    {c.phrase}
                  </span>{" "}
                  <span className="text-sm text-muted-foreground">
                    {c.meaning}
                  </span>
                </span>
                <span
                  lang="en"
                  className="text-sm italic text-muted-foreground"
                >
                  {c.example}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {empty && (
        <p className="text-sm text-muted-foreground">{t("tooShort")}</p>
      )}
    </>
  );
}
