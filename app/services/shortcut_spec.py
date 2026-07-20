"""Capture shortcut specs — parse / validate / persist (app-wide config).

Independent of how keys are registered (Win32 hotkeys today; tray/service later).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

# Stable action ids (config keys under config["shortcuts"])
ACTION_REGION_CAPTURE = "region_capture"
ACTION_FULLSCREEN_CAPTURE = "fullscreen_capture"

SHORTCUT_ACTIONS: tuple[str, ...] = (
    ACTION_REGION_CAPTURE,
    ACTION_FULLSCREEN_CAPTURE,
)

DEFAULT_SHORTCUTS: dict[str, str] = {
    ACTION_REGION_CAPTURE: "Ctrl+Shift+R",
    ACTION_FULLSCREEN_CAPTURE: "Ctrl+Shift+F",
}

ACTION_LABEL_KEYS: dict[str, str] = {
    ACTION_REGION_CAPTURE: "shell.capture.region",
    ACTION_FULLSCREEN_CAPTURE: "shell.capture.fullscreen",
}

# Non-modifier keys we accept for capture shortcuts
_ALLOWED_KEYS = frozenset(
    {
        *[Qt.Key(k) for k in range(int(Qt.Key_A), int(Qt.Key_Z) + 1)],
        *[Qt.Key(k) for k in range(int(Qt.Key_0), int(Qt.Key_9) + 1)],
        *[Qt.Key(k) for k in range(int(Qt.Key_F1), int(Qt.Key_F12) + 1)],
        Qt.Key_Print,
        Qt.Key_Delete,
        Qt.Key_Insert,
        Qt.Key_Home,
        Qt.Key_End,
        Qt.Key_PageUp,
        Qt.Key_PageDown,
    }
)

_MODIFIER_KEYS = frozenset(
    {
        Qt.Key_Control,
        Qt.Key_Shift,
        Qt.Key_Alt,
        Qt.Key_Meta,
        Qt.Key_AltGr,
    }
)

_ALLOWED_MODS = Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier


def normalize_shortcut(text: str | None) -> str | None:
    """Return portable shortcut string (e.g. Ctrl+Shift+R) or None if empty/invalid parse."""
    raw = (text or "").strip()
    if not raw:
        return None
    seq = QKeySequence(raw)
    if seq.isEmpty() or seq.count() < 1:
        return None
    return seq.toString(QKeySequence.PortableText)


def format_shortcut_display(text: str | None) -> str:
    """Human-friendly display: 'Ctrl + Shift + R'."""
    normalized = normalize_shortcut(text)
    if not normalized:
        return ""
    return " + ".join(part.strip() for part in normalized.split("+") if part.strip())


def _combo_parts(text: str | None) -> tuple[Qt.Key, Qt.KeyboardModifiers] | None:
    normalized = normalize_shortcut(text)
    if not normalized:
        return None
    seq = QKeySequence(normalized)
    if seq.count() != 1:
        return None
    combo = seq[0]
    return combo.key(), combo.keyboardModifiers()


def is_print_screen_key(key: Qt.Key) -> bool:
    return key == Qt.Key_Print


def validate_shortcut(text: str | None) -> tuple[bool, str]:
    """
    Validate a shortcut binding.

    Returns (ok, error_message_key). error_message_key is "" when ok.
    """
    parts = _combo_parts(text)
    if parts is None:
        return False, "settings.shortcuts.error_invalid"

    key, mods = parts
    if key in _MODIFIER_KEYS:
        return False, "settings.shortcuts.error_modifiers_only"

    # Only Ctrl / Shift / Alt (no Windows / Meta)
    allowed_mods = _ALLOWED_MODS | Qt.KeypadModifier | Qt.GroupSwitchModifier
    if mods & ~allowed_mods:
        return False, "settings.shortcuts.error_invalid"

    if key not in _ALLOWED_KEYS:
        return False, "settings.shortcuts.error_unsupported_key"

    # PrintScreen alone is allowed; every other key needs at least one modifier
    if mods == Qt.NoModifier or mods == Qt.KeyboardModifiers(Qt.NoModifier):
        if is_print_screen_key(key):
            return True, ""
        return False, "settings.shortcuts.error_modifiers_only"

    return True, ""


def shortcuts_equal(a: str | None, b: str | None) -> bool:
    na = normalize_shortcut(a)
    nb = normalize_shortcut(b)
    if not na or not nb:
        return False
    return na.lower() == nb.lower()


def find_shortcut_conflict(
    action_id: str,
    candidate: str | None,
    bindings: dict[str, str],
) -> str | None:
    """Return the other action_id that already uses candidate, or None."""
    for other_id, other_value in bindings.items():
        if other_id == action_id:
            continue
        if shortcuts_equal(candidate, other_value):
            return other_id
    return None


def load_shortcuts_from_config(config: dict) -> dict[str, str]:
    """Merge config shortcuts with defaults (app-wide, not per-project)."""
    raw = config.get("shortcuts")
    stored: dict = raw if isinstance(raw, dict) else {}
    result: dict[str, str] = {}
    for action_id in SHORTCUT_ACTIONS:
        value = normalize_shortcut(str(stored.get(action_id) or ""))
        if value is None:
            value = DEFAULT_SHORTCUTS[action_id]
        ok, _ = validate_shortcut(value)
        if not ok:
            value = DEFAULT_SHORTCUTS[action_id]
        result[action_id] = value
    return result


def apply_shortcuts_to_config(config: dict, bindings: dict[str, str]) -> dict[str, str]:
    """Write validated bindings into config['shortcuts']; return normalized map."""
    normalized = load_shortcuts_from_config({"shortcuts": bindings})
    # Prefer explicit bindings when valid
    out: dict[str, str] = {}
    for action_id in SHORTCUT_ACTIONS:
        candidate = normalize_shortcut(bindings.get(action_id))
        if candidate and validate_shortcut(candidate)[0]:
            out[action_id] = candidate
        else:
            out[action_id] = normalized[action_id]
    config["shortcuts"] = dict(out)
    return out
