"""Ask AI chat: user and Capixe bubbles. Image results render in the main grid."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.ui.ask_ai_status import ask_ai_phase_copy
from app.ui.design_tokens import COLORS, MOTION_FAST_MS
from app.ui.page_motion import motion_preferred
from app.ui.icons import icon_ai_sparkle, icon_find_images, icon_organize_images

ASK_AI_BUBBLE_MIN_WIDTH = 96
ASK_AI_USER_BUBBLE_RATIO = 0.96
ASK_AI_ASSISTANT_BUBBLE_RATIO = 0.99
ASK_AI_BUBBLE_PAD_X = 20
ASK_AI_START_ICON = 20
ASK_AI_START_PLATE = 28

StartActionHandler = Callable[[str], None]
RestoreResultsHandler = Callable[["AskAiResultMessage"], None]
ConfirmActionHandler = Callable[["AskAiConfirmMessage"], None]
SaveAutomationHandler = Callable[["AskAiConfirmMessage"], None]
ChipHandler = Callable[[str], None]
SignInHandler = Callable[[], None]

CARD_PROCESSING = "processing"
CARD_RESULT = "result"
CARD_ERROR = "error"
CARD_CLARIFY = "clarify"
CARD_UNSUPPORTED = "unsupported"
CARD_AUTH = "auth"
CARD_LIMIT = "limit"
CARD_TEXT = "text"


FADE_MESSAGE_LIMIT = 24


_QWIDGETSIZE_MAX = 16777215


def _unwrapped_text_width(text: str, widget: QWidget) -> int:
    metrics = QFontMetrics(widget.font())
    widest = 0
    for line in (text or "").splitlines() or [""]:
        widest = max(widest, int(metrics.horizontalAdvance(line)))
    return widest


def _apply_inner_wrap_width(message: QWidget, width: int) -> None:
    inner = max(1, int(width) - ASK_AI_BUBBLE_PAD_X)
    for label in message.findChildren(QLabel):
        if label.wordWrap():
            label.setMaximumWidth(inner)


def _fade_in(widget: QWidget, *, enabled: bool = True) -> None:
    if not enabled or not motion_preferred():
        return
    target = max(widget.sizeHint().height(), widget.height())
    if target <= 1:
        return
    widget.setMaximumHeight(0)
    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(MOTION_FAST_MS)
    anim.setStartValue(0)
    anim.setEndValue(target)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def _clear() -> None:
        widget.setMaximumHeight(_QWIDGETSIZE_MAX)

    anim.finished.connect(_clear)
    anim.start(QPropertyAnimation.DeleteWhenStopped)
    widget._ask_ai_fade = anim


def _transparent_label(widget: QWidget, *, styled: bool = False) -> None:
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    if styled:
        widget.setAttribute(Qt.WA_StyledBackground, True)


class AskAiStartRow(QPushButton):
    def __init__(
        self,
        action_id: str,
        title: str,
        body: str,
        icon,
        *,
        plate: str,
        coming_soon: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.action_id = action_id
        self.setObjectName("askAiStartRow")
        self.setProperty("startAction", action_id)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setCheckable(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName(title)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        plate_label = QLabel(self)
        plate_label.setObjectName("askAiStartIconPlate")
        plate_label.setProperty("startAction", plate)
        plate_label.setFixedSize(ASK_AI_START_PLATE, ASK_AI_START_PLATE)
        plate_label.setAlignment(Qt.AlignCenter)
        plate_label.setPixmap(icon.pixmap(ASK_AI_START_ICON, ASK_AI_START_ICON))
        _transparent_label(plate_label, styled=True)
        layout.addWidget(plate_label, 0, Qt.AlignTop)

        text_col = QWidget(self)
        text_col.setObjectName("askAiStartTextCol")
        text_layout = QVBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        title_row = QWidget(text_col)
        title_row.setObjectName("askAiStartTitleRow")
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title_label = QLabel(title, title_row)
        title_label.setObjectName("askAiStartTitle")
        title_label.setWordWrap(True)
        _transparent_label(title_label)
        title_layout.addWidget(title_label, 1)
        if coming_soon:
            soon = QLabel(t("images.ai.start.organize.soon"), title_row)
            soon.setObjectName("askAiStartSoon")
            _transparent_label(soon)
            title_layout.addWidget(soon, 0, Qt.AlignTop)
        title_layout.addStretch(0)
        text_layout.addWidget(title_row)
        body_label = QLabel(body, text_col)
        body_label.setObjectName("askAiStartBody")
        body_label.setWordWrap(True)
        _transparent_label(body_label)
        text_layout.addWidget(body_label)
        layout.addWidget(text_col, 1)

        if coming_soon:
            self.setEnabled(False)
            self.setCursor(Qt.ArrowCursor)
            self.setAccessibleName(
                f"{title}. {t('images.ai.start.organize.soon')}"
            )


class AskAiStartMenu(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_action: StartActionHandler | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("askAiStartMenu")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._on_action = on_action
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        heading = QLabel(t("images.ai.start.heading"), self)
        heading.setObjectName("askAiStartHeading")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        find_row = AskAiStartRow(
            "find",
            t("images.ai.start.find.title"),
            t("images.ai.start.find.body"),
            icon_find_images(size=ASK_AI_START_ICON, color="#3b6ea8"),
            plate="find",
            parent=self,
        )
        find_row.clicked.connect(lambda: self._choose("find"))
        layout.addWidget(find_row)
        self._find_row = find_row

        organize_row = AskAiStartRow(
            "organize",
            t("images.ai.start.organize.title"),
            t("images.ai.start.organize.body"),
            icon_organize_images(size=ASK_AI_START_ICON, color="#6f84a3"),
            plate="organize",
            coming_soon=True,
            parent=self,
        )
        layout.addWidget(organize_row)
        self._organize_row = organize_row
        self._organize_row.hide()

        help_row = AskAiStartRow(
            "help",
            t("images.ai.start.help.title"),
            t("images.ai.start.help.body"),
            icon_ai_sparkle(size=ASK_AI_START_ICON, color="#6d5a9a"),
            plate="help",
            parent=self,
        )
        help_row.clicked.connect(lambda: self._choose("help"))
        layout.addWidget(help_row)
        self._help_row = help_row
        layout.addStretch(1)

    @property
    def action_rows(self) -> list[AskAiStartRow]:
        return [self._find_row, self._organize_row, self._help_row]

    def set_coming_soon_visible(self, visible: bool) -> None:
        self._organize_row.setVisible(visible)

    def _choose(self, action_id: str) -> None:
        if self._on_action is not None:
            self._on_action(action_id)


class AskAiUserMessage(QFrame):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("askAiUserMessage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)
        body = QLabel(text, self)
        body.setObjectName("askAiUserText")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)
        self._body = body
        self._text = text

    @property
    def text(self) -> str:
        return self._text


class AskAiResultMessage(QFrame):
    def __init__(
        self,
        request_id: int,
        parent: QWidget | None = None,
        *,
        query: str = "",
        on_changed: Callable[[], None] | None = None,
        on_show_results: RestoreResultsHandler | None = None,
        on_chip: ChipHandler | None = None,
        on_sign_in: SignInHandler | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("askAiResultMessage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.request_id = request_id
        self._query = query
        self._result_folder: Path | None = None
        self._on_changed = on_changed
        self._on_show_results = on_show_results
        self._on_chip = on_chip
        self._on_sign_in = on_sign_in
        self._paths: list[Path] = []
        self._known: set[str] = set()
        self._ocr_ids: dict[str, int] = {}
        self._searching = True
        self._frozen = False
        self._card_kind = CARD_PROCESSING
        self._phase = "understanding"
        self.setProperty("cardKind", CARD_PROCESSING)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        header = QWidget(self)
        header.setObjectName("askAiCardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        self._icon = QLabel("●", header)
        self._icon.setObjectName("askAiCardIcon")
        self._icon.setFixedWidth(14)
        header_layout.addWidget(self._icon, 0, Qt.AlignTop)
        text_col = QWidget(header)
        text_col.setObjectName("askAiCardTextCol")
        text_layout = QVBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self._status = QLabel(ask_ai_phase_copy("understanding"), text_col)
        self._status.setObjectName("askAiStatus")
        self._status.setWordWrap(True)
        text_layout.addWidget(self._status)
        self._subtitle = QLabel("", text_col)
        self._subtitle.setObjectName("askAiCardSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.hide()
        text_layout.addWidget(self._subtitle)
        header_layout.addWidget(text_col, 1)
        layout.addWidget(header)
        self._body = QLabel("", self)
        self._body.setObjectName("askAiAssistantText")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.hide()
        layout.addWidget(self._body)
        self._chips = QWidget(self)
        self._chips.setObjectName("askAiClarifyChips")
        chip_layout = QHBoxLayout(self._chips)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(6)
        self._chips.hide()
        layout.addWidget(self._chips)
        self._result_action = QPushButton(self)
        self._result_action.setObjectName("askAiResultAction")
        self._result_action.setCursor(Qt.PointingHandCursor)
        self._result_action.setFocusPolicy(Qt.StrongFocus)
        self._result_action.setAutoDefault(False)
        self._result_action.setDefault(False)
        self._result_action.setFlat(True)
        self._result_action.hide()
        self._result_action.clicked.connect(self._emit_show_results)
        layout.addWidget(self._result_action, 0, Qt.AlignLeft)
        self._sign_in_btn = QPushButton(t("images.ai.sign_in_action"), self)
        self._sign_in_btn.setObjectName("askAiSignInAction")
        self._sign_in_btn.setCursor(Qt.PointingHandCursor)
        self._sign_in_btn.setAutoDefault(False)
        self._sign_in_btn.setDefault(False)
        self._sign_in_btn.hide()
        self._sign_in_btn.clicked.connect(self._emit_sign_in)
        layout.addWidget(self._sign_in_btn, 0, Qt.AlignLeft)
        self._pulse = QTimer(self)
        self._pulse.setInterval(500)
        self._pulse.timeout.connect(self._toggle_pulse)
        self._pulse_on = True
        self._pulse.start()

    @property
    def paths(self) -> list[Path]:
        return list(self._paths)

    @property
    def result_query(self) -> str:
        return self._query

    @property
    def result_folder(self) -> Path | None:
        return self._result_folder

    @property
    def result_image_ids(self) -> tuple[str, ...]:
        return tuple(self._known_ids())

    @property
    def ocr_image_ids(self) -> dict[str, int]:
        return dict(self._ocr_ids)

    @property
    def result_count(self) -> int:
        return len(self._paths)

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def assistant_text(self) -> str:
        return self._body.text() or self._status.text()

    @property
    def searching(self) -> bool:
        return self._searching

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def card_kind(self) -> str:
        return self._card_kind

    @property
    def phase(self) -> str:
        return self._phase

    def set_phase(self, phase: str) -> None:
        if self._frozen:
            return
        self._searching = True
        self._phase = phase
        self._set_kind(CARD_PROCESSING)
        self._status.setText(ask_ai_phase_copy(phase))
        self._status.show()
        self._subtitle.hide()
        self._body.hide()
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._start_pulse()
        self._notify()

    def set_result_query(self, query: str) -> None:
        if self._frozen:
            return
        self._query = query

    def set_result_folder(self, folder: Path | str | None) -> None:
        if self._frozen:
            return
        self._result_folder = Path(folder) if folder is not None else None

    def bind_ocr_image_ids(self, mapping: dict[str, int] | None) -> None:
        """Attach stable OCR ids for later path resolve. Safe after freeze."""
        for key, image_id in dict(mapping or {}).items():
            try:
                self._ocr_ids[str(key)] = int(image_id)
            except (TypeError, ValueError):
                continue

    def add_paths(self, paths: list[Path] | tuple[Path, ...]) -> None:
        if self._frozen:
            return
        added = False
        for path in paths:
            key = str(path.resolve())
            if key in self._known:
                continue
            self._known.add(key)
            self._paths.append(path)
            added = True
        if added:
            self._notify()

    def set_searching(self, text: str) -> None:
        if self._frozen:
            return
        self._searching = True
        self._phase = "searching"
        self._set_kind(CARD_PROCESSING)
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._subtitle.hide()
        self._body.hide()
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._start_pulse()
        self._notify()

    def complete(self, paths: list[Path] | tuple[Path, ...], status: str) -> None:
        if self._frozen:
            return
        self.add_paths(paths)
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        provided = str(status or "").strip()
        count = len(self._paths)
        if provided:
            title = provided
        elif count == 1:
            title = t("images.ai.found_one")
        else:
            title = t("images.ai.found", count=count)
        self._status.setText(title)
        self._status.show()
        self._icon.setText("✓")
        self._set_kind(CARD_RESULT)
        query = self._query.strip()
        self._subtitle.setText(query)
        self._subtitle.setVisible(bool(query))
        self._body.hide()
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._notify()

    def fail(self, status: str) -> None:
        if self._frozen:
            return
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        self._set_kind(CARD_ERROR)
        self._icon.setText("!")
        self._status.setText(status or t("images.ai.temporarily_unavailable"))
        self._status.show()
        self._subtitle.hide()
        self._body.hide()
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._notify()

    def complete_text(self, text: str) -> None:
        if self._frozen:
            return
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        self._set_kind(CARD_TEXT)
        self._icon.setText("✓")
        self._status.clear()
        self._status.hide()
        self._subtitle.hide()
        self._body.setText(text)
        self._body.setVisible(bool(text))
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._notify()

    def set_error_card(self, title: str, body: str = "") -> None:
        if self._frozen and self._card_kind not in {CARD_PROCESSING, ""}:
            return
        self._frozen = False
        self.fail(title)
        if body:
            self._frozen = False
            self._body.setText(body)
            self._body.show()
            self._frozen = True
            self._notify()

    def set_clarify_card(self, text: str, chips: list[tuple[str, str]] | None = None) -> None:
        if self._frozen:
            return
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        self._set_kind(CARD_CLARIFY)
        self._icon.setText("?")
        self._status.setText(text)
        self._status.show()
        self._subtitle.hide()
        self._body.hide()
        self._sign_in_btn.hide()
        self._fill_chips(chips or [])
        self._sync_result_action()
        self._notify()

    def set_unsupported_card(self, title: str, body: str = "") -> None:
        if self._frozen:
            return
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        self._set_kind(CARD_UNSUPPORTED)
        self._icon.setText("!")
        self._status.setText(title or t("images.ai.unsupported_title"))
        self._status.show()
        self._subtitle.hide()
        self._body.setText(body or t("images.ai.unsupported_body"))
        self._body.setVisible(bool(self._body.text()))
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._notify()

    def set_auth_card(self, text: str) -> None:
        if self._frozen:
            return
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        self._set_kind(CARD_AUTH)
        self._icon.setText("!")
        self._status.setText(text)
        self._status.show()
        self._subtitle.hide()
        self._body.hide()
        self._chips.hide()
        self._sign_in_btn.setVisible(self._on_sign_in is not None)
        self._sync_result_action()
        self._notify()

    def set_limit_card(self, title: str, body: str = "") -> None:
        if self._frozen and self._card_kind not in {CARD_PROCESSING, ""}:
            return
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        self._set_kind(CARD_LIMIT)
        self._icon.setText("!")
        self._status.setText(title or t("account.ai.limit_reached"))
        self._status.show()
        self._subtitle.hide()
        self._body.setText(body or t("account.ai.limit_reached_body"))
        self._body.setVisible(bool(self._body.text()))
        self._chips.hide()
        self._sign_in_btn.hide()
        self._sync_result_action()
        self._notify()

    def freeze(self) -> None:
        if self._frozen:
            return
        was_searching = self._searching
        self._searching = False
        self._frozen = True
        self._stop_pulse()
        if was_searching:
            if self._paths:
                count = len(self._paths)
                title = t("images.ai.found_one") if count == 1 else t("images.ai.found", count=count)
                self._status.setText(title)
                self._status.show()
                self._icon.setText("✓")
                self._set_kind(CARD_RESULT)
            else:
                self._status.clear()
                self._status.hide()
            self._sync_result_action()
            self._notify()

    def _known_ids(self) -> list[str]:
        return [str(path.resolve()) for path in self._paths]

    def _set_kind(self, kind: str) -> None:
        self._card_kind = kind
        self.setProperty("cardKind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

    def _start_pulse(self) -> None:
        if not self._pulse.isActive():
            self._pulse.start()
        self._icon.setText("●")

    def _stop_pulse(self) -> None:
        if self._pulse.isActive():
            self._pulse.stop()
        self._icon.setStyleSheet("")

    def _toggle_pulse(self) -> None:
        if self._card_kind != CARD_PROCESSING:
            self._stop_pulse()
            return
        self._pulse_on = not self._pulse_on
        self._icon.setStyleSheet(
            f"color: {COLORS.text_muted};" if self._pulse_on else f"color: {COLORS.border_strong};"
        )

    def _fill_chips(self, chips: list[tuple[str, str]]) -> None:
        layout = self._chips.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not chips:
            self._chips.hide()
            return
        for label, payload in chips:
            button = QPushButton(label, self._chips)
            button.setObjectName("askAiClarifyChip")
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setDefault(False)
            button.clicked.connect(lambda checked=False, text=payload: self._emit_chip(text))
            layout.addWidget(button, 0, Qt.AlignLeft)
        layout.addStretch(1)
        self._chips.show()

    def _emit_chip(self, text: str) -> None:
        if self._on_chip is not None:
            self._on_chip(text)

    def _emit_sign_in(self) -> None:
        if self._on_sign_in is not None:
            self._on_sign_in()

    def _sync_result_action(self) -> None:
        count = len(self._paths)
        show = (not self._searching) and count > 0
        self._result_action.setText(t("images.ai.result_action", count=count))
        self._result_action.setAccessibleName(self._result_action.text())
        self._result_action.setVisible(show)
        self._result_action.setEnabled(show)

    def _emit_show_results(self) -> None:
        if self._on_show_results is None or not self._paths:
            return
        self._on_show_results(self)

    def _notify(self) -> None:
        if self._on_changed is not None:
            self._on_changed()


class AskAiConfirmMessage(QFrame):
    """Preview → Confirm for Act. Action execution stays in the caller."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_changed: Callable[[], None] | None = None,
        on_confirm: ConfirmActionHandler | None = None,
        on_cancel: ConfirmActionHandler | None = None,
        on_save: SaveAutomationHandler | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("askAiResultMessage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._on_changed = on_changed
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._on_save = on_save
        self._frozen = False
        self._pending = False
        self._executing = False
        self._card_kind = "preview"
        self.setProperty("cardKind", "preview")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        header = QWidget(self)
        header.setObjectName("askAiCardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        self._icon = QLabel("▸", header)
        self._icon.setObjectName("askAiCardIcon")
        self._icon.setFixedWidth(14)
        header_layout.addWidget(self._icon, 0, Qt.AlignTop)
        self._status = QLabel("", header)
        self._status.setObjectName("askAiStatus")
        self._status.setWordWrap(True)
        header_layout.addWidget(self._status, 1)
        layout.addWidget(header)
        self._detail = QLabel("", self)
        self._detail.setObjectName("askAiAssistantText")
        self._detail.setWordWrap(True)
        self._detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._detail.hide()
        layout.addWidget(self._detail)
        actions = QWidget(self)
        actions.setObjectName("askAiConfirmActions")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 2, 0, 0)
        action_layout.setSpacing(8)
        self._cancel_btn = QPushButton(t("common.cancel"), actions)
        self._cancel_btn.setObjectName("askAiConfirmCancel")
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.setDefault(False)
        self._cancel_btn.clicked.connect(self._emit_cancel)
        self._confirm_btn = QPushButton(t("images.ai.confirm"), actions)
        self._confirm_btn.setObjectName("askAiConfirmExecute")
        self._confirm_btn.setCursor(Qt.PointingHandCursor)
        self._confirm_btn.setAutoDefault(False)
        self._confirm_btn.setDefault(False)
        self._confirm_btn.clicked.connect(self._emit_confirm)
        action_layout.addWidget(self._cancel_btn, 0, Qt.AlignLeft)
        action_layout.addWidget(self._confirm_btn, 0, Qt.AlignLeft)
        action_layout.addStretch(1)
        layout.addWidget(actions)
        self._actions = actions
        self._save_btn = QPushButton(t("images.ai.save_automation"), self)
        self._save_btn.setObjectName("askAiSaveAutomation")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setAutoDefault(False)
        self._save_btn.setDefault(False)
        self._save_btn.setFlat(False)
        self._save_btn.clicked.connect(self._emit_save)
        self._save_btn.hide()
        layout.addWidget(self._save_btn, 0, Qt.AlignLeft)

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def pending(self) -> bool:
        return self._pending and not self._frozen and not self._executing

    @property
    def executing(self) -> bool:
        return self._executing

    @property
    def card_kind(self) -> str:
        return self._card_kind

    @property
    def status_text(self) -> str:
        return self._status.text()

    def set_preview(self, summary: str, detail: str = "", confirm_label: str = "") -> None:
        if self._frozen:
            return
        self._pending = True
        self._executing = False
        self._card_kind = "preview"
        self.setProperty("cardKind", "preview")
        self._icon.setText("▸")
        self._status.setText(summary)
        self._status.setVisible(bool(summary))
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        if confirm_label:
            self._confirm_btn.setText(confirm_label)
        self._actions.show()
        self._cancel_btn.setEnabled(True)
        self._confirm_btn.setEnabled(True)
        self._save_btn.hide()
        self._polish()
        self._notify()

    def set_executing(self, text: str, *, progress: str = "") -> None:
        if self._frozen:
            return
        self._pending = False
        self._executing = True
        self._card_kind = "executing"
        self.setProperty("cardKind", "executing")
        self._icon.setText("●")
        self._status.setText(text)
        self._status.show()
        if progress:
            self._detail.setText(progress)
            self._detail.show()
        self._confirm_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._save_btn.hide()
        self._polish()
        self._notify()

    def complete(self, text: str, *, warning: bool = False, detail: str = "") -> None:
        self._pending = False
        self._executing = False
        self._frozen = True
        self._card_kind = "warning" if warning else "complete"
        self.setProperty("cardKind", self._card_kind)
        self._icon.setText("⚠" if warning else "✓")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        if detail:
            self._detail.setText(detail)
            self._detail.show()
        else:
            self._detail.hide()
        self._actions.hide()
        self._save_btn.setVisible(self._on_save is not None)
        self._polish()
        self._notify()

    def fail(self, text: str) -> None:
        self._pending = False
        self._executing = False
        self._frozen = True
        self._card_kind = "error"
        self.setProperty("cardKind", "error")
        self._icon.setText("!")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._detail.hide()
        self._actions.hide()
        self._save_btn.hide()
        self._polish()
        self._notify()

    def set_cancelled(self, text: str) -> None:
        self._pending = False
        self._executing = False
        self._frozen = True
        self._card_kind = "cancelled"
        self.setProperty("cardKind", "cancelled")
        self._icon.setText("–")
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._detail.hide()
        self._actions.hide()
        self._save_btn.hide()
        self._polish()
        self._notify()

    def freeze(self) -> None:
        if self._frozen:
            return
        self._pending = False
        self._frozen = True
        self._cancel_btn.setEnabled(False)
        self._confirm_btn.setEnabled(False)
        self._actions.hide()
        self._notify()

    def _polish(self) -> None:
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def _emit_save(self) -> None:
        if self._on_save is None:
            return
        self._on_save(self)

    def _emit_confirm(self) -> None:
        if self._frozen or self._executing or self._on_confirm is None:
            return
        self._confirm_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._on_confirm(self)

    def _emit_cancel(self) -> None:
        if self._frozen or self._on_cancel is None:
            return
        self._on_cancel(self)

    def _notify(self) -> None:
        if self._on_changed is not None:
            self._on_changed()


class AskAiChatView(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("aiChatHistory")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        viewport = self.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
            palette = viewport.palette()
            palette.setColor(QPalette.ColorRole.Base, Qt.transparent)
            palette.setColor(QPalette.ColorRole.Window, Qt.transparent)
            viewport.setPalette(palette)
        self._host = QWidget(self)
        self._host.setObjectName("askAiChatHost")
        self._host.setAutoFillBackground(False)
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(4, 8, 4, 10)
        self._layout.setSpacing(10)
        self._on_start_action: StartActionHandler | None = None
        self._on_restore_results: RestoreResultsHandler | None = None
        self._on_confirm_action: ConfirmActionHandler | None = None
        self._on_cancel_action: ConfirmActionHandler | None = None
        self._on_save_action: SaveAutomationHandler | None = None
        self._on_chip: ChipHandler | None = None
        self._on_sign_in: SignInHandler | None = None
        self._stick_to_bottom = True
        self._start_menu = AskAiStartMenu(
            self._host, on_action=self._handle_start_action
        )
        self._layout.addWidget(self._start_menu)
        self._layout.addStretch(1)
        self.setWidget(self._host)
        self._user_messages: list[AskAiUserMessage] = []
        self._result_messages: list[AskAiResultMessage] = []
        self._confirm_messages: list[AskAiConfirmMessage] = []
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._scroll_now)
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(self._on_scroll_value)
        self._jump_btn = QPushButton(t("images.ai.jump_to_latest"), self)
        self._jump_btn.setObjectName("askAiJumpLatest")
        self._jump_btn.setCursor(Qt.PointingHandCursor)
        self._jump_btn.setAutoDefault(False)
        self._jump_btn.setDefault(False)
        self._jump_btn.hide()
        self._jump_btn.clicked.connect(self._jump_to_latest)

    @property
    def user_texts(self) -> list[str]:
        return [message.text for message in self._user_messages]

    @property
    def result_messages(self) -> list[AskAiResultMessage]:
        return list(self._result_messages)

    @property
    def confirm_messages(self) -> list[AskAiConfirmMessage]:
        return list(self._confirm_messages)

    @property
    def start_menu(self) -> AskAiStartMenu:
        return self._start_menu

    def set_start_action_handler(self, handler: StartActionHandler | None) -> None:
        self._on_start_action = handler

    def set_restore_results_handler(
        self, handler: RestoreResultsHandler | None
    ) -> None:
        self._on_restore_results = handler

    def set_confirm_handlers(
        self,
        on_confirm: ConfirmActionHandler | None,
        on_cancel: ConfirmActionHandler | None,
        on_save: SaveAutomationHandler | None = None,
    ) -> None:
        self._on_confirm_action = on_confirm
        self._on_cancel_action = on_cancel
        self._on_save_action = on_save

    def set_chip_handler(self, handler: ChipHandler | None) -> None:
        self._on_chip = handler

    def set_sign_in_handler(self, handler: SignInHandler | None) -> None:
        self._on_sign_in = handler

    def set_coming_soon_visible(self, visible: bool) -> None:
        self._start_menu.set_coming_soon_visible(visible)

    def has_conversation(self) -> bool:
        return bool(self._user_messages or self._result_messages or self._confirm_messages)

    def _fade_enabled(self) -> bool:
        return (
            len(self._user_messages)
            + len(self._result_messages)
            + len(self._confirm_messages)
        ) <= FADE_MESSAGE_LIMIT

    def show_start_menu(self) -> None:
        if self.has_conversation():
            self._start_menu.hide()
            return
        self._start_menu.show()

    def hide_start_menu(self) -> None:
        self._start_menu.hide()

    def add_user_message(self, text: str) -> AskAiUserMessage:
        self.hide_start_menu()
        row = QWidget(self._host)
        row.setObjectName("askAiUserRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.addStretch(1)
        widget = AskAiUserMessage(text, row)
        row_layout.addWidget(widget, 0, Qt.AlignRight | Qt.AlignTop)
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._user_messages.append(widget)
        self._apply_bubble_widths()
        _fade_in(widget, enabled=self._fade_enabled())
        self.scroll_to_bottom()
        return widget

    def add_result_message(
        self, request_id: int, *, query: str = ""
    ) -> AskAiResultMessage:
        self.hide_start_menu()
        row = QWidget(self._host)
        row.setObjectName("askAiAssistantRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        widget = AskAiResultMessage(
            request_id,
            row,
            query=query,
            on_changed=self.scroll_to_bottom,
            on_show_results=self._handle_restore_results,
            on_chip=self._handle_chip,
            on_sign_in=self._handle_sign_in,
        )
        row_layout.addWidget(widget, 0, Qt.AlignLeft | Qt.AlignTop)
        row_layout.addStretch(1)
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._result_messages.append(widget)
        self._apply_bubble_widths()
        _fade_in(widget, enabled=self._fade_enabled())
        self.scroll_to_bottom()
        return widget

    def add_confirm_message(self) -> AskAiConfirmMessage:
        self.hide_start_menu()
        self.freeze_pending_confirms()
        row = QWidget(self._host)
        row.setObjectName("askAiAssistantRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        widget = AskAiConfirmMessage(
            row,
            on_changed=self.scroll_to_bottom,
            on_confirm=self._handle_confirm,
            on_cancel=self._handle_cancel_confirm,
            on_save=self._handle_save_automation,
        )
        row_layout.addWidget(widget, 0, Qt.AlignLeft | Qt.AlignTop)
        row_layout.addStretch(1)
        self._layout.insertWidget(self._layout.count() - 1, row)
        self._confirm_messages.append(widget)
        self._apply_bubble_widths()
        _fade_in(widget, enabled=self._fade_enabled())
        self.scroll_to_bottom()
        return widget

    def convert_result_to_confirm(self, result: AskAiResultMessage) -> AskAiConfirmMessage:
        row = result.parentWidget()
        if row is None:
            return self.add_confirm_message()
        layout = row.layout()
        if layout is not None:
            layout.removeWidget(result)
        result.hide()
        result.setParent(None)
        result.deleteLater()
        if result in self._result_messages:
            self._result_messages.remove(result)
        widget = AskAiConfirmMessage(
            row,
            on_changed=self.scroll_to_bottom,
            on_confirm=self._handle_confirm,
            on_cancel=self._handle_cancel_confirm,
            on_save=self._handle_save_automation,
        )
        if layout is not None:
            layout.insertWidget(0, widget, 0, Qt.AlignLeft | Qt.AlignTop)
        else:
            widget.setParent(row)
        self._confirm_messages.append(widget)
        self._apply_bubble_widths()
        _fade_in(widget, enabled=self._fade_enabled())
        self.scroll_to_bottom()
        return widget

    def freeze_pending_confirms(self) -> None:
        for message in self._confirm_messages:
            if message.pending:
                message.freeze()

    def scroll_to_bottom(self) -> None:
        if not self._stick_to_bottom:
            self._jump_btn.setVisible(self.has_conversation())
            return
        self._scroll_timer.start(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_bubble_widths()
        self._place_jump_button()

    def _handle_start_action(self, action_id: str) -> None:
        if self._on_start_action is not None:
            self._on_start_action(action_id)

    def _handle_restore_results(self, message: AskAiResultMessage) -> None:
        if self._on_restore_results is not None:
            self._on_restore_results(message)

    def _handle_confirm(self, message: AskAiConfirmMessage) -> None:
        if self._on_confirm_action is not None:
            self._on_confirm_action(message)

    def _handle_cancel_confirm(self, message: AskAiConfirmMessage) -> None:
        if self._on_cancel_action is not None:
            self._on_cancel_action(message)

    def _handle_save_automation(self, message: AskAiConfirmMessage) -> None:
        if self._on_save_action is not None:
            self._on_save_action(message)

    def _handle_chip(self, text: str) -> None:
        if self._on_chip is not None:
            self._on_chip(text)

    def _handle_sign_in(self) -> None:
        if self._on_sign_in is not None:
            self._on_sign_in()

    def _apply_bubble_widths(self) -> None:
        view_width = self.viewport().width() if self.viewport() is not None else 280
        user_max = max(
            ASK_AI_BUBBLE_MIN_WIDTH, int(view_width * ASK_AI_USER_BUBBLE_RATIO)
        )
        assistant_max = max(
            ASK_AI_BUBBLE_MIN_WIDTH, int(view_width * ASK_AI_ASSISTANT_BUBBLE_RATIO)
        )
        for message in self._user_messages:
            natural = _unwrapped_text_width(message.text, message) + ASK_AI_BUBBLE_PAD_X
            if natural >= user_max:
                message.setMinimumWidth(user_max)
            else:
                message.setMinimumWidth(
                    max(ASK_AI_BUBBLE_MIN_WIDTH, min(user_max, natural))
                )
            message.setMaximumWidth(user_max)
            _apply_inner_wrap_width(message, user_max)
        for message in self._result_messages:
            message.setMinimumWidth(assistant_max)
            message.setMaximumWidth(assistant_max)
            _apply_inner_wrap_width(message, assistant_max)
        for message in self._confirm_messages:
            message.setMinimumWidth(assistant_max)
            message.setMaximumWidth(assistant_max)
            _apply_inner_wrap_width(message, assistant_max)

    def _scroll_now(self) -> None:
        bar = self.verticalScrollBar()
        if bar is None:
            return
        bar.setValue(bar.maximum())
        self._stick_to_bottom = True
        self._jump_btn.hide()

    def _on_scroll_value(self, value: int) -> None:
        bar = self.verticalScrollBar()
        if bar is None:
            return
        near_bottom = value >= bar.maximum() - 24
        self._stick_to_bottom = near_bottom
        self._jump_btn.setVisible(self.has_conversation() and not near_bottom)
        self._place_jump_button()

    def _jump_to_latest(self) -> None:
        self._stick_to_bottom = True
        self._scroll_now()

    def _place_jump_button(self) -> None:
        if self._jump_btn.isHidden():
            return
        margin = 8
        width = self._jump_btn.sizeHint().width()
        height = self._jump_btn.sizeHint().height()
        self._jump_btn.setGeometry(
            self.width() - width - margin,
            self.height() - height - margin,
            width,
            height,
        )
        self._jump_btn.raise_()

    def sizeHint(self) -> QSize:
        return QSize(320, 240)
