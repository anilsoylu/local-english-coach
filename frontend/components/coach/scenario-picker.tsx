"use client";

import { PickCard, PickScreen } from "@/components/coach/pick-list";
import { ScenarioIcon } from "@/components/coach/scenario-icon";
import type { Scenario } from "@/lib/api";
import { useMessages } from "@/lib/i18n";

const DEFAULTS = {
  title: "What shall we talk about today?",
  intro:
    "Pick a situation and write in English, or talk with your keyboard's microphone. If you get stuck, write in your own language or tap “I'm stuck”.",
  reload: "Reload",
};

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
  const t = useMessages("scenarioPicker", DEFAULTS);
  return (
    <PickScreen
      title={t("title")}
      intro={t("intro")}
      error={error}
      reloadLabel={t("reload")}
      empty={!scenarios.length}
    >
      {scenarios.map((s, i) => (
        <PickCard
          key={s.id}
          index={i}
          disabled={disabled}
          pending={disabled && s.id === selected}
          onClick={() => onPick(s.id)}
          data-scenario={s.id}
        >
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
            <ScenarioIcon id={s.id} className="size-5" />
          </span>
          <span className="text-sm font-medium leading-snug text-pretty">
            {s.title}
          </span>
        </PickCard>
      ))}
    </PickScreen>
  );
}
