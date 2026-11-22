"use client";

import {
  ArrowLeft,
  Languages,
  LifeBuoy,
  RotateCcw,
  Square,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { ThinkingShimmer } from "@/components/agents/loading-states/thinking-shimmer";
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageGroup,
} from "@/components/agents/message";
import {
  MessageBubble,
  MessageBubbleContent,
} from "@/components/agents/message-bubble";
import { MessageScroller } from "@/components/agents/message-scroller";
import { PromptInput } from "@/components/agents/prompt-input";
import { StreamingResponse } from "@/components/agents/streaming-response";
import { LanguagePicker } from "@/components/coach/language-picker";
import { ReportCard } from "@/components/coach/report-card";
import { ScenarioIcon } from "@/components/coach/scenario-icon";
import { ScenarioPicker } from "@/components/coach/scenario-picker";
import { WarmupCard } from "@/components/coach/warmup-card";
import { Button } from "@/components/ui/button";
import { LocaleProvider, useMessages } from "@/lib/i18n";
import { type ChatMessage, HELP_TEXT, useCoach } from "@/lib/use-coach";
import { SOURCE_LANGUAGE, useNativeLanguage } from "@/lib/use-native-language";
import { cn } from "@/lib/utils";

const DEFAULTS = {
  thinking: "Sam is thinking…",
  end: "End",
  confirmEnd: "Sure?",
  newSession: "New session",
  back: "Back",
  language: "Language",
  chat: "Chat",
  message: "Your message",
  send: "Send",
  wait: "Wait",
  stuck: "I'm stuck",
};

function CoachBubble({ m }: { m: ChatMessage }) {
  const t = useMessages("coachApp", DEFAULTS);
  if (m.streaming && !m.content) {
    return (
      <ThinkingShimmer className="px-1 py-2 text-sm">
        {t("thinking")}
      </ThinkingShimmer>
    );
  }
  return (
    <MessageBubble variant={m.error ? "danger" : "soft"}>
      <MessageBubbleContent>
        <StreamingResponse
          status={m.streaming ? "streaming" : "complete"}
          showActions={false}
          announce={false}
          contentClassName="whitespace-pre-wrap text-[15px] leading-relaxed"
        >
          {m.content}
        </StreamingResponse>
      </MessageBubbleContent>
    </MessageBubble>
  );
}

// Phones need 40px targets; the desktop keeps the compact size.
const COARSE_BUTTON =
  "pointer-coarse:h-10 pointer-coarse:px-3.5 pointer-coarse:text-sm";
const CONFIRM_MS = 3000;

/** Ending is final, so the first tap only arms the button; a second tap within 3 s ends the session. */
function EndButton({
  disabled,
  onEnd,
}: {
  disabled: boolean;
  onEnd: () => void;
}) {
  const t = useMessages("coachApp", DEFAULTS);
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const onClick = () => {
    clearTimeout(timer.current);
    if (armed) {
      setArmed(false);
      onEnd();
      return;
    }
    setArmed(true);
    timer.current = setTimeout(() => setArmed(false), CONFIRM_MS);
  };

  return (
    <Button
      variant={armed ? "destructive" : "outline"}
      size="sm"
      onClick={onClick}
      disabled={disabled}
      data-testid="end"
      className={COARSE_BUTTON}
    >
      <Square aria-hidden />
      {t(armed ? "confirmEnd" : "end")}
    </Button>
  );
}

interface FrameProps {
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}

/** The page shell: header with the app name, an optional subtitle and actions, then the content. */
function Frame({ subtitle, actions, children }: FrameProps) {
  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="border-b border-border/70 bg-background pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex h-14 w-full max-w-2xl items-center gap-3 px-4">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">
            EC
          </span>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="text-sm font-semibold leading-tight">
              English Coach
            </span>
            {subtitle}
          </div>
          {actions}
        </div>
      </header>
      {children}
    </div>
  );
}

export function CoachApp() {
  const lang = useNativeLanguage();
  return (
    <LocaleProvider
      locale={lang.code || SOURCE_LANGUAGE}
      messages={lang.messages}
    >
      <App lang={lang} />
    </LocaleProvider>
  );
}

/** Onboarding until the native language is known, then the coach. */
function App({ lang }: { lang: ReturnType<typeof useNativeLanguage> }) {
  const t = useMessages("coachApp", DEFAULTS);
  const [picking, setPicking] = useState(false);
  // Nothing but the shell until the language is known, so no text renders in the wrong language.
  if (lang.code === null) return <Frame />;
  if (!lang.code || picking) {
    return (
      <Frame
        actions={
          picking && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPicking(false)}
              className={COARSE_BUTTON}
            >
              <ArrowLeft aria-hidden />
              {t("back")}
            </Button>
          )
        }
      >
        <main className="flex-1 overflow-y-auto">
          <LanguagePicker
            languages={lang.languages}
            current={lang.code}
            onPick={async (code) => {
              await lang.choose(code);
              setPicking(false);
            }}
          />
        </main>
      </Frame>
    );
  }
  const name = lang.languages?.find((l) => l.code === lang.code)?.name;
  return (
    // Scenario titles come in the native language: a new language starts a fresh coach.
    <Coach
      key={lang.code}
      languageName={name}
      onChangeLanguage={() => setPicking(true)}
    />
  );
}

function Coach({
  languageName,
  onChangeLanguage,
}: {
  languageName?: string;
  onChangeLanguage: () => void;
}) {
  const t = useMessages("coachApp", DEFAULTS);
  const c = useCoach();
  const current = c.scenarios.find((s) => s.id === c.scenario);

  return (
    <Frame
      subtitle={
        c.phase !== "idle" &&
        current && (
          <span className="flex items-center gap-1 truncate text-xs text-muted-foreground">
            <ScenarioIcon id={current.id} className="size-3" />
            <span className="truncate">{current.title}</span>
          </span>
        )
      }
      actions={
        <>
          {c.phase === "idle" && (
            <Button
              variant="outline"
              size="sm"
              onClick={onChangeLanguage}
              aria-label={
                languageName
                  ? `${t("language")}: ${languageName}`
                  : t("language")
              }
              data-testid="language"
              className={COARSE_BUTTON}
            >
              <Languages aria-hidden />
              {languageName ?? t("language")}
            </Button>
          )}
          {c.phase === "chat" && (
            <EndButton
              disabled={c.busy || !c.messages.some((m) => m.from === "user")}
              onEnd={c.end}
            />
          )}
          {c.phase === "report" && (
            <Button
              variant="outline"
              size="sm"
              onClick={c.reset}
              data-testid="new"
              className={COARSE_BUTTON}
            >
              <RotateCcw aria-hidden />
              {t("newSession")}
            </Button>
          )}
        </>
      }
    >
      {c.phase === "idle" ? (
        <main className="flex-1 overflow-y-auto">
          <ScenarioPicker
            scenarios={c.scenarios}
            selected={c.scenario}
            disabled={c.starting}
            error={c.error}
            onPick={(id) => {
              c.setScenario(id);
              void c.start(id);
            }}
          />
        </main>
      ) : (
        <MessageScroller
          className="min-h-0 flex-1"
          viewportClassName="py-6 [scrollbar-gutter:stable_both-edges]"
          contentClassName="mx-auto w-full max-w-2xl px-4"
          busy={c.busy}
          smooth={!c.busy}
          labels={{ label: t("chat") }}
        >
          {c.phase === "chat" && <WarmupCard chunks={c.warmup} />}
          <MessageGroup spacing="default" lang="en">
            {c.messages.map((m) => (
              <Message
                key={m.id}
                from={m.from}
                animateIn
                data-help={m.help || undefined}
              >
                {m.from === "assistant" && (
                  <MessageAvatar className="bg-primary/10 text-primary">
                    S
                  </MessageAvatar>
                )}
                <MessageContent>
                  {m.from === "assistant" ? (
                    <CoachBubble m={m} />
                  ) : (
                    // "solid" paints its surface with --foreground and its text with --background:
                    // remap both to the brand colors for the learner's own bubbles.
                    <MessageBubble
                      variant="solid"
                      className={cn(
                        "[--background:var(--primary-foreground)] [--foreground:var(--primary)]",
                        m.help && "italic",
                      )}
                    >
                      <MessageBubbleContent className="whitespace-pre-wrap text-[15px] leading-relaxed">
                        {m.help && (
                          <LifeBuoy
                            aria-hidden
                            className="mr-1 inline size-3.5 align-[-2px]"
                          />
                        )}
                        {m.content}
                      </MessageBubbleContent>
                    </MessageBubble>
                  )}
                </MessageContent>
              </Message>
            ))}
          </MessageGroup>
          {c.report && <ReportCard state={c.report} />}
        </MessageScroller>
      )}

      {c.phase === "chat" && (
        <footer className="border-t border-border/70 bg-background pb-[env(safe-area-inset-bottom)]">
          <div className="mx-auto w-full max-w-2xl px-4 py-3">
            <PromptInput
              value={c.draft}
              onValueChange={c.setDraft}
              onSubmit={(text) => c.send(text)}
              loading={c.busy}
              minRows={1}
              maxRows={6}
              placeholder="Type in English…"
              labels={{ label: t("message"), send: t("send"), stop: t("wait") }}
              // The coach has to see the real mistakes: no autocorrect, no spellcheck. 16px stops iOS zoom;
              // the hidden mirror div that sizes the textarea gets the same size so lines wrap alike.
              // PromptInput sets height to rows * 24px with border-box, so its top padding becomes margin
              // or every line overflows by 6px.
              lang="en"
              spellCheck={false}
              autoCorrect="off"
              autoCapitalize="sentences"
              autoComplete="off"
              enterKeyHint="send"
              // The send/stop button is the last one in the action row and has no stable hook of its own.
              className="[&>[aria-hidden]]:text-base [&_textarea]:mt-1.5 [&_textarea]:pt-0 [&_textarea]:text-base pointer-coarse:[&>div:last-child>button:last-child]:size-10"
              leadingAction={
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={c.busy}
                  onClick={() => c.send(HELP_TEXT, true)}
                  data-testid="help"
                  className={COARSE_BUTTON}
                >
                  <LifeBuoy aria-hidden />
                  {t("stuck")}
                </Button>
              }
            />
          </div>
        </footer>
      )}
    </Frame>
  );
}
