"use client";

import { Check } from "lucide-react";
import { useState } from "react";
import { PickCard, PickScreen } from "@/components/coach/pick-list";
import type { Language } from "@/lib/api";
import { useMessages } from "@/lib/i18n";

const DEFAULTS = {
  welcome: "Welcome to English Coach",
  title: "Your native language",
  intro:
    "Pick the language you know best. Menus and your session reports will be in it.",
  unreachable: "Could not reach the server.",
  saveFailed: "Could not save your choice. Try again.",
  reload: "Reload",
};

interface LanguagePickerProps {
  /** null while the list loads. */
  languages: Language[] | null;
  /** The current native language, "" on the first visit. */
  current: string;
  onPick: (code: string) => Promise<void>;
}

/** First-visit onboarding, and later the screen to change the native language. One tap saves. */
export function LanguagePicker({
  languages,
  current,
  onPick,
}: LanguagePickerProps) {
  const t = useMessages("languagePicker", DEFAULTS);
  const [pending, setPending] = useState("");
  const [failed, setFailed] = useState(false);

  const pick = async (code: string) => {
    setPending(code);
    setFailed(false);
    try {
      await onPick(code);
    } catch {
      setFailed(true);
    } finally {
      setPending("");
    }
  };

  const unreachable = languages?.length === 0;
  return (
    <PickScreen
      title={t(current ? "title" : "welcome")}
      intro={t("intro")}
      error={unreachable ? t("unreachable") : failed ? t("saveFailed") : null}
      reloadLabel={t("reload")}
      empty={unreachable}
    >
      {languages?.map((l, i) => (
        <PickCard
          key={l.code}
          index={i}
          disabled={Boolean(pending)}
          pending={pending === l.code}
          aria-current={l.code === current || undefined}
          onClick={() => pick(l.code)}
          data-language={l.code}
        >
          {/* lang="en": the page's uppercasing rules would turn "it" into "İT" under Turkish. */}
          <span
            aria-hidden
            lang="en"
            className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-[11px] font-semibold uppercase text-primary"
          >
            {l.code}
          </span>
          <span className="flex min-w-0 flex-col">
            <span lang={l.code} className="font-medium leading-snug">
              {l.name}
            </span>
            {l.english_name !== l.name && (
              <span lang="en" className="text-sm text-muted-foreground">
                {l.english_name}
              </span>
            )}
          </span>
          {l.code === current && !pending && (
            <Check
              aria-hidden
              className="ml-auto size-4 shrink-0 text-primary"
            />
          )}
        </PickCard>
      ))}
    </PickScreen>
  );
}
