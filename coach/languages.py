"""Native languages the learner can pick. Adding one is one line here; the base of the code (before "-") must be an
ISO 639-1 code that lingua supports, because detection uses it. UI strings (frontend locale files) and scenario
translations (scenarios.yaml) are optional: anything missing falls back to English."""

from __future__ import annotations

DEFAULT = "en"

# code -> (English name, name in that language). English first: it is the default and the fallback.
LANGUAGES: dict[str, tuple[str, str]] = {
    "en": ("English", "English"),
    "tr": ("Turkish", "Türkçe"),
    "es": ("Spanish", "Español"),
    "pt-BR": ("Brazilian Portuguese", "Português (Brasil)"),
    "de": ("German", "Deutsch"),
    "fr": ("French", "Français"),
    "it": ("Italian", "Italiano"),
    "pl": ("Polish", "Polski"),
    "ru": ("Russian", "Русский"),
    "ja": ("Japanese", "日本語"),
    "ko": ("Korean", "한국어"),
    "zh": ("Simplified Chinese", "简体中文"),
}


def resolve(code: str) -> str:
    """The stored code, or English when none is chosen yet."""
    return code if code in LANGUAGES else DEFAULT


def english_name(code: str) -> str:
    return LANGUAGES[resolve(code)][0]


def listing() -> list[dict]:
    return [{"code": c, "name": native, "english_name": eng} for c, (eng, native) in LANGUAGES.items()]


def pick(value: str | dict, code: str) -> str:
    """A scenarios.yaml text: a plain string, or a map by language code that falls back to English."""
    if not isinstance(value, dict):
        return value
    return value.get(resolve(code)) or value.get(DEFAULT, "")


def speaker(code: str) -> str:
    """How prompts describe the learner: "a Turkish speaker", or "an English learner" when the native language is
    English or not chosen."""
    return f"a {english_name(code)} speaker" if resolve(code) != DEFAULT else "an English learner"
