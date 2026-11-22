"use client";

import { Loader2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { ScenarioIcon } from "@/components/coach/scenario-icon";
import { Button } from "@/components/ui/button";
import type { Scenario } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ScenarioPickerProps {
  scenarios: Scenario[];
  selected: string;
  disabled: boolean;
  error: string | null;
  onPick: (id: string) => void;
}

/** Start screen: one tap picks a scenario and starts the session. */
export function ScenarioPicker({
  scenarios,
  selected,
  disabled,
  error,
  onPick,
}: ScenarioPickerProps) {
  const reduce = useReducedMotion();
  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-10">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight text-balance">
          Bugün ne konuşalım?
        </h1>
        <p className="text-pretty text-muted-foreground">
          Bir durum seç ve İngilizce yaz ya da klavyenin mikrofonuyla konuş.
          Takılırsan Türkçe yaz veya “Takıldım”a bas.
        </p>
      </div>
      {error && (
        <div className="flex flex-col items-start gap-3">
          <p
            role="alert"
            className="w-full rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </p>
          {!scenarios.length && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => location.reload()}
            >
              Yenile
            </Button>
          )}
        </div>
      )}
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {scenarios.map((s, i) => {
          const pending = disabled && s.id === selected;
          return (
            <motion.li
              key={s.id}
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                duration: 0.2,
                delay: reduce ? 0 : i * 0.03,
                ease: [0.23, 1, 0.32, 1],
              }}
            >
              <button
                type="button"
                disabled={disabled}
                aria-busy={pending || undefined}
                onClick={() => onPick(s.id)}
                data-scenario={s.id}
                className={cn(
                  "group flex w-full items-center gap-3 rounded-2xl border border-border bg-card p-4 text-left",
                  "touch-manipulation select-none outline-none transition-[color,background-color,border-color,transform] duration-150 ease-out active:scale-[0.98]",
                  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                  "[@media(hover:hover)]:hover:border-primary/40 [@media(hover:hover)]:hover:bg-muted/40",
                  pending ? "border-primary" : "disabled:opacity-60",
                )}
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <ScenarioIcon id={s.id} className="size-5" />
                </span>
                <span className="text-sm font-medium leading-snug text-pretty">
                  {s.title}
                </span>
                {pending && (
                  <Loader2
                    aria-hidden
                    className="ml-auto size-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
                  />
                )}
              </button>
            </motion.li>
          );
        })}
      </ul>
    </section>
  );
}
