"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Language } from "@/lib/api";
import type { LocaleMessages } from "@/lib/i18n";
import { store } from "@/lib/store";

/** English is the source language: its strings are the components' defaults, so it has no file. */
export const SOURCE_LANGUAGE = "en";
const STORE_KEY = "native_language";
const NO_MESSAGES: LocaleMessages = {};

/**
 * Loads `locales/<code>.json`. Adding a language is dropping in that file; a missing file or key
 * falls back to the English defaults.
 */
async function loadMessages(code: string): Promise<LocaleMessages> {
  if (code === SOURCE_LANGUAGE) return NO_MESSAGES;
  try {
    return (await import(`@/locales/${code}.json`)).default;
  } catch {
    return NO_MESSAGES;
  }
}

/**
 * The learner's native language: the interface language. The server profile is the source of truth;
 * the last code is cached in localStorage so a reload renders in the right language without waiting
 * for the profile.
 */
export function useNativeLanguage() {
  // code: null while unknown, "" when the learner hasn't picked one yet.
  const [state, setState] = useState<{
    code: string | null;
    messages: LocaleMessages;
  }>({ code: null, messages: NO_MESSAGES });
  // null while loading, [] if the list could not be fetched.
  const [languages, setLanguages] = useState<Language[] | null>(null);
  // The newest apply wins when the cached and the server language load at the same time.
  const applyGen = useRef(0);

  const apply = useCallback(async (code: string) => {
    const gen = ++applyGen.current;
    const messages = code ? await loadMessages(code) : NO_MESSAGES;
    if (gen !== applyGen.current) return;
    setState({ code, messages });
    store.set(STORE_KEY, code || null);
  }, []);

  useEffect(() => {
    const cached = store.get(STORE_KEY);
    if (cached) void apply(cached);
    api
      .profile()
      .then((p) => {
        if (p.native_language !== cached) void apply(p.native_language);
      })
      // Offline with nothing cached: show the app in English, it reports the unreachable server.
      .catch(() => {
        if (!cached) void apply(SOURCE_LANGUAGE);
      });
    api
      .languages()
      .then(setLanguages)
      .catch(() => setLanguages([]));
  }, [apply]);

  /** Saves the choice on the server, then switches the interface. Throws if the save failed. */
  const choose = useCallback(
    async (code: string) => {
      const p = await api.setProfile({ native_language: code });
      await apply(p.native_language);
    },
    [apply],
  );

  return { ...state, languages, choose };
}
