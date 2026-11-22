"use client";

import {
  ArrowLeft,
  ChevronDown,
  House,
  Languages,
  LifeBuoy,
  MessagesSquare,
  RotateCcw,
  Square,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { AgentDisclosure } from "@/components/agents/agent-disclosure";
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
import { SessionHistory } from "@/components/coach/session-history";
import { WarmupCard } from "@/components/coach/warmup-card";
import { Button } from "@/components/ui/button";
import { SPRING_SWAP } from "@/lib/ease";
import { LocaleProvider, useMessages } from "@/lib/i18n";
import { COARSE_BUTTON } from "@/lib/touch";
import {
  type ChatMessage,
  HELP_TEXT,
  type ReportState,
  useCoach,
} from "@/lib/use-coach";
import { SOURCE_LANGUAGE, useNativeLanguage } from "@/lib/use-native-language";
import { cn } from "@/lib/utils";

const DEFAULTS = {
  thinking: "Sam is thinking…",
  end: "End",
  confirmEnd: "Sure?",
  newSession: "New session",
  home: "Home",
  showConversation: "Show conversation",
  hideConversation: "Hide conversation",
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
  /** Makes the app name a link home. Left out mid-chat: leaving would abandon the session, End is the way out. */
  onHome?: () => void;
  children?: ReactNode;
}

const APP_NAME = "English Coach";

function Frame({ subtitle, actions, onHome, children }: FrameProps) {
  const t = useMessages("coachApp", DEFAULTS);
  const name = (
    <span className="text-sm font-semibold leading-tight">{APP_NAME}</span>
  );
  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="border-b border-border/70 bg-background pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex h-14 w-full max-w-2xl items-center gap-3 px-4">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">
            EC
          </span>
          <div className="flex min-w-0 flex-1 flex-col items-start">
            {onHome ? (
              <button
                type="button"
                onClick={onHome}
                aria-label={`${APP_NAME}: ${t("home")}`}
                data-testid="app-home"
                className="-mx-1 rounded-md px-1 outline-none transition-colors hover:text-primary hover:transition-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {name}
              </button>
            ) : (
              name
            )}
            {subtitle}
          </div>
          {actions}
        </div>
      </header>
      {children}
    </div>
  );
}

/** The chat's messages, live in the chat and read-only on the report screen. */
function Conversation({ messages }: { messages: ChatMessage[] }) {
  return (
    <MessageGroup spacing="default" lang="en">
      {messages.map((m) => (
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
  );
}

interface ReportScreenProps {
  report: ReportState;
  messages: ChatMessage[];
  error: string | null;
  onGenerate: () => void;
  onHome: () => void;
  onNew: () => void;
}

/** After a session, or a past one opened from home: the report first, the conversation folded away below it. */
function ReportScreen({
  report,
  messages,
  error,
  onGenerate,
  onHome,
  onNew,
}: ReportScreenProps) {
  const t = useMessages("coachApp", DEFAULTS);
  const reduce = useReducedMotion() ?? false;
  const [open, setOpen] = useState(false);
  const contentId = useId();
  return (
    <>
      <main className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6">
          <ReportCard state={report} onGenerate={onGenerate} error={error} />
          <div>
            <button
              type="button"
              aria-expanded={open}
              aria-controls={contentId}
              onClick={() => setOpen(!open)}
              data-testid="show-conversation"
              className="-ml-1 flex min-h-10 items-center gap-2 rounded-lg px-1 text-sm text-muted-foreground outline-none transition-colors hover:text-foreground hover:transition-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <MessagesSquare aria-hidden className="size-4" />
              <span className="font-medium">
                {t(open ? "hideConversation" : "showConversation")}
              </span>
              <motion.span
                aria-hidden
                animate={{ rotate: open ? 180 : 0 }}
                transition={reduce ? { duration: 0 } : SPRING_SWAP}
                className="text-muted-foreground/60"
              >
                <ChevronDown className="size-3.5" />
              </motion.span>
            </button>
            <AgentDisclosure id={contentId} open={open}>
              <div className="pt-4">
                <Conversation messages={messages} />
              </div>
            </AgentDisclosure>
          </div>
        </div>
      </main>
      <footer className="border-t border-border/70 bg-background pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto flex w-full max-w-2xl justify-end gap-2 px-4 py-3">
          <Button
            variant="outline"
            onClick={onHome}
            data-testid="home"
            className={cn("flex-1 sm:flex-none", COARSE_BUTTON)}
          >
            <House aria-hidden />
            {t("home")}
          </Button>
          <Button
            onClick={onNew}
            data-testid="new"
            className={cn("flex-1 sm:flex-none", COARSE_BUTTON)}
          >
            <RotateCcw aria-hidden />
            {t("newSession")}
          </Button>
        </div>
      </footer>
    </>
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
        onHome={picking ? () => setPicking(false) : undefined}
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
  const s = c.session;
  const busy = s.phase === "chat" && s.busy;
  const current = c.scenarios.find((sc) => sc.id === c.scenario);
  const home = useRef<HTMLElement>(null);

  return (
    <Frame
      onHome={
        s.phase === "report"
          ? c.reset
          : s.phase === "idle"
            ? () => home.current?.scrollTo({ top: 0, behavior: "smooth" })
            : undefined
      }
      subtitle={
        s.phase !== "idle" &&
        current && (
          <span className="flex items-center gap-1 truncate text-xs text-muted-foreground">
            <ScenarioIcon id={current.id} className="size-3" />
            <span className="truncate">{current.title}</span>
          </span>
        )
      }
      actions={
        <>
          {s.phase === "idle" && (
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
          {s.phase === "chat" && (
            <EndButton
              disabled={busy || !c.messages.some((m) => m.from === "user")}
              onEnd={c.end}
            />
          )}
        </>
      }
    >
      {s.phase === "idle" && (
        <main ref={home} className="flex-1 overflow-y-auto">
          <ScenarioPicker
            scenarios={c.scenarios}
            // No scenario spins while a past session opens.
            selected={s.opening === null ? c.scenario : ""}
            disabled={s.starting}
            error={c.error}
            onPick={(id) => {
              c.setScenario(id);
              void c.start(id);
            }}
            footer={
              <SessionHistory
                disabled={s.starting}
                opening={s.opening}
                onOpen={(sid, generate) => void c.open(sid, generate)}
              />
            }
          />
        </main>
      )}
      {s.phase === "report" && (
        <ReportScreen
          key={s.sid}
          report={s.report}
          messages={c.messages}
          error={c.error}
          onGenerate={() => void c.generate()}
          onHome={c.reset}
          onNew={c.restart}
        />
      )}
      {s.phase === "chat" && (
        <MessageScroller
          className="min-h-0 flex-1"
          viewportClassName="py-6 [scrollbar-gutter:stable_both-edges]"
          contentClassName="mx-auto w-full max-w-2xl px-4"
          busy={busy}
          smooth={!busy}
          labels={{ label: t("chat") }}
        >
          <WarmupCard chunks={s.warmup} />
          <Conversation messages={c.messages} />
        </MessageScroller>
      )}

      {s.phase === "chat" && (
        <footer className="border-t border-border/70 bg-background pb-[env(safe-area-inset-bottom)]">
          <div className="mx-auto w-full max-w-2xl px-4 py-3">
            <PromptInput
              value={c.draft}
              onValueChange={c.setDraft}
              onSubmit={(text) => c.send(text)}
              loading={busy}
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
                  disabled={busy}
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
