"use client";

import { Sparkles } from "lucide-react";
import type { WarmupChunk } from "@/lib/api";
import { useMessages } from "@/lib/i18n";

const DEFAULTS = { title: "Try to use today" };

/** Phrases due for review; the coach steers the chat so they fit naturally. */
export function WarmupCard({ chunks }: { chunks: WarmupChunk[] }) {
  const t = useMessages("warmupCard", DEFAULTS);
  if (!chunks.length) return null;
  return (
    <section
      aria-label={t("title")}
      className="mb-6 rounded-2xl border border-border bg-card p-4"
    >
      <h2 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        <Sparkles aria-hidden className="size-3.5 text-primary" />
        {t("title")}
      </h2>
      <ul className="flex flex-col gap-2">
        {chunks.map((c) => (
          <li
            key={c.phrase}
            className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2"
          >
            <span lang="en" className="font-medium">
              {c.phrase}
            </span>
            {c.meaning && (
              <span className="text-sm text-muted-foreground">{c.meaning}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
