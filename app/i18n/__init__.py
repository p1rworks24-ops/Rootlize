"""Lightweight i18n helpers for UI strings.

English is the only locale today. To add another language later:
1. Create app/i18n/<locale>.py with a MESSAGES dict
2. Register it in _CATALOGS
3. Call set_locale("<locale>")
"""

from __future__ import annotations

from app.i18n import en as en_messages

_CATALOGS: dict[str, dict[str, str]] = {
    "en": en_messages.MESSAGES,
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
