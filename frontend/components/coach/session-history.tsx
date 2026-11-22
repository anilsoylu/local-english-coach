"use client";

import { ChevronRight, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ErrorNote } from "@/components/coach/pick-list";
import { ScenarioIcon } from "@/components/coach/scenario-icon";
import { Button } from "@/components/ui/button";
import { api, type PastSession } from "@/lib/api";
import { useLocale, useMessages } from "@/lib/i18n";
import { COARSE_BUTTON } from "@/lib/touch";
import { cn } from "@/lib/utils";

const DEFAULTS = {
  title: "Past sessions",
  messages: "Messages: {count}",
  errors: "Corrections: {count}",
  preparing: "Report in progress",
  generate: "Generate report",
  more: "Show more",
  loadFailed: "Could not load your past sessions.",
};

interface SessionHistoryProps {
  /** While a session starts or opens. */
  disabled: boolean;
  /** The session being opened, which shows a spinner. */
  opening: number | null;
  onOpen: (sid: number, generate: boolean) => void;
}

/** The home screen's past sessions, 10 at a time. Hidden until there is one. */
export function SessionHistory({
  disabled,
  opening,
  onOpen,
}: SessionHistoryProps) {
  const t = useMessages("sessionHistory", DEFAULTS);
  const { locale } = useLocale();
  const [rows, setRows] = useState<PastSession[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const date = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }),
    [locale],
  );

  const load = useCallback(async (offset: number) => {
    setLoading(true);
    setFailed(false);
    try {
      const page = await api.sessions(offset);
      setRows((r) => (offset ? [...r, ...page.sessions] : page.sessions));
      setMore(page.more);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(0);
  }, [load]);

  if (!rows.length && !failed) return null;
  return (
    <section
      aria-labelledby="past-sessions"
      data-testid="history"
      className="mt-4 flex flex-col gap-3"
    >
      <h2 id="past-sessions" className="text-base font-semibold">
        {t("title")}
      </h2>
      {failed && <ErrorNote>{t("loadFailed")}</ErrorNote>}
      {!!rows.length && (
        <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
          {rows.map((r) => (
            <li
              key={r.id}
              data-session={r.id}
              className={cn(
                "flex items-center gap-2",
                r.report === "none" && "pr-3",
              )}
            >
              <button
                type="button"
                disabled={disabled}
                aria-busy={opening === r.id || undefined}
                onClick={() => onOpen(r.id, false)}
                className={cn(
                  "group flex min-w-0 flex-1 items-center gap-3 py-3 pr-3 pl-4 text-left outline-none",
                  "touch-manipulation select-none transition-colors duration-150 ease-out [@media(hover:hover)]:hover:bg-muted/40 [@media(hover:hover)]:hover:transition-none",
                  "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                  "disabled:opacity-60",
                )}
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <ScenarioIcon id={r.scenario} className="size-4" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="text-sm font-medium leading-snug text-pretty">
                    {r.title}
                  </span>
                  <span className="flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
                    <time dateTime={r.started_at}>
                      {date.format(new Date(r.started_at))}
                    </time>
                    <span>{t("messages", { count: r.messages })}</span>
                    {r.errors !== null && (
                      <span>{t("errors", { count: r.errors })}</span>
                    )}
                    {r.report === "pending" && <span>{t("preparing")}</span>}
                  </span>
                </span>
                {opening === r.id ? (
                  <Loader2
                    aria-hidden
                    className="size-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
                  />
                ) : (
                  r.report !== "none" && (
                    <ChevronRight
                      aria-hidden
                      className="size-4 shrink-0 text-muted-foreground"
                    />
                  )
                )}
              </button>
              {r.report === "none" && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={() => onOpen(r.id, true)}
                  data-testid="generate"
                  className={COARSE_BUTTON}
                >
                  {t("generate")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {more && (
        <Button
          variant="outline"
          size="sm"
          disabled={loading}
          onClick={() => load(rows.length)}
          data-testid="more"
          className={cn("self-start", COARSE_BUTTON)}
        >
          {t("more")}
        </Button>
      )}
    </section>
  );
}
