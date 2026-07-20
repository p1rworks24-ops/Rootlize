"""Lightweight i18n helpers for UI strings.

English is the default locale. Japanese (ja) is registered for keys that have
translations; missing keys fall back to English via ``t()``.
"""

from __future__ import annotations

from app.i18n import en as en_messages
from app.i18n import ja as ja_messages

_CATALOGS: dict[str, dict[str, str]] = {
    "en": en_messages.MESSAGES,
    "ja": ja_messages.MESSAGES,
}

_locale: str = "en"


def set_locale(locale: str) -> None:
    """Switch active locale. Falls back to English if unknown."""
    global _locale
    _locale = locale if locale in _CATALOGS else "en"


def get_locale() -> str:
    return _locale


def t(key: str, **kwargs) -> str:
    """Return the translated string for key, with optional format kwargs."""
    catalog = _CATALOGS.get(_locale) or _CATALOGS["en"]
    text = catalog.get(key)
    if text is None:
        text = _CATALOGS["en"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
