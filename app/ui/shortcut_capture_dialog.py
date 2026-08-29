"""Modal dialog: wait for a key combination to assign as a shortcut."""

from __future__ import annotations

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QVBoxLayout

from app.i18n import t
from app.ui.page_motion import AnimatedDialog
from app.services.shortcut_spec import (
    format_shortcut_display,
    normalize_shortcut,
    validate_shortcut,
)


class ShortcutCaptureDialog(AnimatedDialog):
    """Press a key combo to capture; Escape cancels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("shortcutCaptureDialog")
        self.setWindowTitle(t("settings.shortcuts.capture_title"))
        self.setModal(True)
        self.setMinimumWidth(360)
        self._result: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        prompt = QLabel(t("settings.shortcuts.capture_prompt"), self)
        prompt.setObjectName("shortcutCapturePrompt")
        prompt.setWordWrap(True)
        prompt.setAlignment(Qt.AlignCenter)
        layout.addWidget(prompt)

        hint = QLabel(t("settings.shortcuts.capture_hint"), self)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

    def captured_shortcut(self) -> str | None:
        return self._result

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        key = Qt.Key(event.key())
        if key == Qt.Key_Escape:
            self.reject()
            return
        # Wait until a non-modifier key arrives
        if key in (
            Qt.Key_Control,
            Qt.Key_Shift,
            Qt.Key_Alt,
            Qt.Key_Meta,
            Qt.Key_AltGr,
        ):
            return

        mods = event.modifiers() & (
            Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier
        )
        combo = QKeyCombination(mods, key)
        seq = QKeySequence(combo)
        text = normalize_shortcut(seq.toString(QKeySequence.PortableText))
        ok, err_key = validate_shortcut(text)
        if not ok or not text:
            # Keep listening; show brief feedback in window title
            self.setWindowTitle(
                t(err_key) if err_key else t("settings.shortcuts.error_invalid")
            )
            return
        self._result = text
        self.setWindowTitle(format_shortcut_display(text))
        self.accept()
