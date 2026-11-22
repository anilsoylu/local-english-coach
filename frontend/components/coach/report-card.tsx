"use client";

import { motion, useReducedMotion } from "motion/react";
import { ThinkingShimmer } from "@/components/agents/loading-states/thinking-shimmer";
import type { ReportState } from "@/lib/use-coach";

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

export function ReportCard({ state }: { state: ReportState }) {
  const reduce = useReducedMotion();
  return (
    <motion.section
      aria-label="Seans raporu"
      data-testid="report"
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
      className="mt-6 flex flex-col gap-6 rounded-2xl border border-border bg-card p-5"
    >
      <h2 className="text-base font-semibold">Seans raporu</h2>
      {state.status === "waiting" && (
        <ThinkingShimmer className="text-sm">
          Analiz ediliyor, bu birkaç dakika sürebilir…
        </ThinkingShimmer>
      )}
      {state.status === "timeout" && (
        <p className="text-sm text-muted-foreground">
          Rapor hâlâ hazırlanıyor. Biraz sonra sayfayı yenile, hazır olunca
          burada görünür.
        </p>
      )}
      {state.status === "ready" && (
        <ReportBody metrics={state.metrics} report={state.report} />
      )}
    </motion.section>
  );
}

function ReportBody({
  metrics: m,
  report: r,
}: Pick<Extract<ReportState, { status: "ready" }>, "metrics" | "report">) {
  const stuck =
    (m.help_count ?? 0) + (m.turkish_turns ?? 0) + (m.mixed_turns ?? 0);
  const empty = !r.feedback_tr && !r.errors?.length;
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat value={m.user_turns} label="mesaj" />
        <Stat value={m.avg_words} label="ortalama kelime" />
        <Stat value={m.median_response_s} label="cevap süresi (sn)" />
        <Stat value={stuck} label="takılma" />
        <Stat
          value={`${m.chunks_used?.length ?? 0}/${m.chunks_offered ?? 0}`}
          label="kalıp kullanıldı"
        />
      </div>
      {r.feedback_tr && (
        <p className="text-pretty leading-relaxed">{r.feedback_tr}</p>
      )}
      {!!r.errors?.length && (
        <Section title="Düzeltmeler">
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
                <span className="text-sm text-muted-foreground">
                  {e.note_tr}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {!!r.natural?.length && (
        <Section title="Daha doğal söyleyiş">
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
        <Section title="Yeni kalıplar">
          <ul className="flex flex-col gap-3">
            {r.chunks.map((c) => (
              <li key={c.phrase} className="flex flex-col gap-0.5">
                <span>
                  <span lang="en" className="font-medium">
                    {c.phrase}
                  </span>{" "}
                  <span className="text-sm text-muted-foreground">
                    {c.meaning_tr}
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
        <p className="text-sm text-muted-foreground">
          Analiz için seans çok kısaydı.
        </p>
      )}
    </>
  );
}
