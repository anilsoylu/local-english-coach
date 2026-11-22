"use client";

import { Loader2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { ComponentProps, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PickCardProps extends ComponentProps<"button"> {
  /** Position in the list, staggers the entrance. */
  index: number;
  /** Shows a spinner while the tap's work runs. */
  pending?: boolean;
}

/** One tappable card in a one-tap choice list (scenarios, languages). Render inside a `<ul>`. */
export function PickCard({
  index,
  pending = false,
  className,
  children,
  ...props
}: PickCardProps) {
  const reduce = useReducedMotion();
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.2,
        delay: reduce ? 0 : index * 0.03,
        ease: [0.23, 1, 0.32, 1],
      }}
    >
      <button
        type="button"
        aria-busy={pending || undefined}
        className={cn(
          "group flex w-full items-center gap-3 rounded-2xl border border-border bg-card p-4 text-left",
          "touch-manipulation select-none outline-none transition-[color,background-color,border-color,transform] duration-150 ease-out active:scale-[0.98]",
          "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          "[@media(hover:hover)]:hover:border-primary/40 [@media(hover:hover)]:hover:bg-muted/40",
          pending ? "border-primary" : "disabled:opacity-60",
          className,
        )}
        {...props}
      >
        {children}
        {pending && (
          <Loader2
            aria-hidden
            className="ml-auto size-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
          />
        )}
      </button>
    </motion.li>
  );
}

interface PickScreenProps {
  title: string;
  intro: ReactNode;
  error?: string | null;
  /** Shown next to the error when there is nothing to pick from; reloads the page. */
  reloadLabel?: string;
  empty?: boolean;
  /** `PickCard`s. */
  children: ReactNode;
}

/** A start screen with one tap choices: heading, intro, error and the card grid. */
export function PickScreen({
  title,
  intro,
  error,
  reloadLabel,
  empty = false,
  children,
}: PickScreenProps) {
  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-10">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight text-balance">
          {title}
        </h1>
        <p className="text-pretty text-muted-foreground">{intro}</p>
      </div>
      {error && (
        <div className="flex flex-col items-start gap-3">
          <p
            role="alert"
            className="w-full rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </p>
          {empty && reloadLabel && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => location.reload()}
            >
              {reloadLabel}
            </Button>
          )}
        </div>
      )}
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</ul>
    </section>
  );
}
