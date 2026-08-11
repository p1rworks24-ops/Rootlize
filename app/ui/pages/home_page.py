"""Home dashboard for the selected library and plan usage."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.config import save_config
from app.services.metadata_service import MetadataService
from app.ui.design_tokens import apply_card_shadow
from app.ui.icons import icon_folder
from app.utils.selected_folder import get_selected_folder, set_selected_folder
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.workspace_stats import collect_selected_folder_totals


class UsageDonut(QWidget):
    """Compact plan-usage chart; data can later come from an account backend."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._used = 0
        self._limit = 0
        self.setFixedSize(176, 176)

    def set_usage(self, used: int, limit: int) -> None:
        self._limit = max(0, int(limit))
        self._used = (
            min(max(0, int(used)), self._limit)
            if self._limit
            else max(0, int(used))
        )
        self.update()

    @property
    def unlimited(self) -> bool:
        return self._limit == 0

    @property
    def remaining(self) -> int:
        return max(0, self._limit - self._used)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        ring = QRectF(18, 18, self.width() - 36, self.height() - 36)
        width = 15
        painter.setPen(QPen(QColor("#e2e8f0"), width, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(ring, 0, 360 * 16)
        # Blue is the remaining usable quota, matching the center label.
        if self.unlimited or self.remaining > 0:
            span = (
                360 * 16
                if self.unlimited
                else int((self.remaining / self._limit) * 360 * 16)
            )
            painter.setPen(
                QPen(QColor("#2563eb"), width, Qt.SolidLine, Qt.RoundCap)
            )
            painter.drawArc(ring, 90 * 16, -span)

        painter.setPen(QColor("#111827"))
        font = painter.font()
        font.setPointSize(22)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 48, self.width(), 48),
            Qt.AlignCenter,
            "∞" if self.unlimited else str(self.remaining),
        )
        painter.setPen(QColor("#64748b"))
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 94, self.width(), 28),
            Qt.AlignHCenter | Qt.AlignTop,
            t(
                "home.dashboard.images_available"
                if self.unlimited
                else "home.dashboard.images_left"
            ),
        )
        painter.end()


class HomePage(QWidget):
    """Wide dashboard with distinct folder, library, and plan hierarchy."""

    folder_changed = Signal(str)

    def __init__(
        self,
        config: dict,
        metadata_service: MetadataService,
        thumbnail_cache: ThumbnailCache,
        app_root: Path,
        parent=None,
        **_unused,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._metadata_service = metadata_service
        self._thumbnail_cache = thumbnail_cache
        self._app_root = app_root
        self._folder_total = 0
        self._analysis_summary = {"total": 0, "analyzed": 0, "pending": 0}
        self._analysis_running = False
        self._plan_usage_override: tuple[str, int, int] | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        from app.ui.page_header import make_page_header
        from app.ui.scroll_page import make_page_scroll

        scroll = make_page_scroll(self)
        outer.addWidget(scroll)
        content = QWidget(scroll)
        content.setObjectName("homeContentColumn")
        scroll.setWidget(content)
        page_layout = QHBoxLayout(content)
        page_layout.setContentsMargins(28, 20, 28, 28)
        page_layout.setSpacing(0)
        dashboard = QWidget(content)
        dashboard.setObjectName("homeDashboardBody")
        self._dashboard = dashboard
        dashboard.setMaximumWidth(1120)
        dashboard.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(dashboard)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(make_page_header(dashboard, t("home.title"), t("home.subtitle")))
        page_layout.addWidget(dashboard, 1)
        page_layout.addStretch(1)

        self._folder_card = QFrame(content)
        self._folder_card.setObjectName("homeSelectedFolderCard")
        apply_card_shadow(self._folder_card, blue_tinted=True)
        folder_layout = QHBoxLayout(self._folder_card)
        folder_layout.setContentsMargins(18, 14, 18, 14)
        folder_layout.setSpacing(16)
        folder_copy = QVBoxLayout()
        folder_copy.setSpacing(4)
        folder_title = QLabel(t("home.dashboard.selected_folder"), self._folder_card)
        folder_title.setObjectName("homeContextLabel")
        self._folder_path = QLabel("—", self._folder_card)
        self._folder_path.setObjectName("homeFolderPath")
        self._folder_path.setWordWrap(True)
        folder_copy.addWidget(folder_title)
        folder_copy.addWidget(self._folder_path)
        folder_layout.addLayout(folder_copy, 1)
        self._select_folder_btn = QPushButton(
            t("home.dashboard.select_folder"), self._folder_card
        )
        self._select_folder_btn.setObjectName("homeSelectFolderButton")
        self._select_folder_btn.setIcon(icon_folder(color="#2563eb"))
        self._select_folder_btn.setIconSize(QSize(16, 16))
        self._select_folder_btn.setCursor(Qt.PointingHandCursor)
        self._select_folder_btn.clicked.connect(self._choose_folder)
        folder_layout.addWidget(self._select_folder_btn, 0, Qt.AlignVCenter)
        layout.addWidget(self._folder_card)

        lower = QHBoxLayout()
        lower.setContentsMargins(0, 0, 0, 0)
        lower.setSpacing(12)
        self._library_panel = self._build_library_panel(content)
        self._plan_panel = self._build_plan_panel(content)
        lower.addWidget(self._library_panel, 3)
        lower.addWidget(self._plan_panel, 2)
        layout.addLayout(lower, 1)
        layout.addStretch(1)

    def _build_library_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("homeLibraryPanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        apply_card_shadow(panel, blue_tinted=True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)
        title = QLabel(t("home.dashboard.library_status"), panel)
        title.setObjectName("homePanelTitle")
        layout.addWidget(title)

        metrics = QHBoxLayout()
        metrics.setSpacing(18)
        self._total_value = self._add_metric(
            metrics, t("home.dashboard.total_images")
        )
        self._analyzed_value = self._add_metric(
            metrics, t("home.dashboard.analyzed")
        )
        self._pending_value = self._add_metric(
            metrics, t("home.dashboard.unanalyzed")
        )
        layout.addLayout(metrics)

        progress_label = QLabel(t("home.dashboard.analysis_progress_label"), panel)
        progress_label.setObjectName("homeContextLabel")
        layout.addWidget(progress_label)
        self._analysis_progress = QProgressBar(panel)
        self._analysis_progress.setObjectName("homeAnalysisProgress")
        self._analysis_progress.setRange(0, 100)
        self._analysis_progress.setTextVisible(False)
        self._analysis_progress.setFixedHeight(12)
        layout.addWidget(self._analysis_progress)
        self._analysis_state = QLabel("", panel)
        self._analysis_state.setObjectName("mutedLabel")
        layout.addWidget(self._analysis_state)
        layout.addStretch(1)
        return panel

    def _add_metric(self, row: QHBoxLayout, label: str) -> QLabel:
        box = QWidget(self)
        box.setObjectName("homeMetric")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(3)
        caption = QLabel(label, box)
        caption.setObjectName("homeMetricLabel")
        value = QLabel("0", box)
        value.setObjectName("homeMetricValue")
        box_layout.addWidget(caption)
        box_layout.addWidget(value)
        row.addWidget(box, 1)
        return value

    def _build_plan_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("homePlanPanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        apply_card_shadow(panel, blue_tinted=True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)
        title = QLabel(t("home.dashboard.plan_usage"), panel)
        title.setObjectName("homePanelTitle")
        layout.addWidget(title)
        self._plan_name = QLabel(t("home.dashboard.plan_placeholder"), panel)
        self._plan_name.setObjectName("homePlanName")
        layout.addWidget(self._plan_name)
        chart_row = QHBoxLayout()
        chart_row.addStretch(1)
        self._usage_donut = UsageDonut(panel)
        chart_row.addWidget(self._usage_donut)
        chart_row.addStretch(1)
        layout.addLayout(chart_row)
        self._usage_caption = QLabel("", panel)
        self._usage_caption.setObjectName("homeUsageCaption")
        self._usage_caption.setAlignment(Qt.AlignCenter)
        self._usage_caption.setWordWrap(True)
        layout.addWidget(self._usage_caption)
        layout.addStretch(1)
        return panel

    def set_plan_usage(self, plan_name: str, used: int, limit: int) -> None:
        """Backend-ready adapter for future account/usage data."""
        self._plan_usage_override = (str(plan_name), max(0, int(used)), max(0, int(limit)))
        self._refresh_plan_usage()

    def _choose_folder(self) -> None:
        current = get_selected_folder(self._config, self._app_root)
        start = str(current if current and current.exists() else Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            t("home.dashboard.select_folder_title"),
            start,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        path = set_selected_folder(self._config, selected)
        save_config(self._config)
        self.refresh()
        self.folder_changed.emit(str(path))

    def set_analysis_summary(self, summary: object) -> None:
        data = summary if isinstance(summary, dict) else {}
        self._analysis_summary = {
            "total": max(0, int(data.get("total", 0) or 0)),
            "analyzed": max(0, int(data.get("analyzed", 0) or 0)),
            "pending": max(0, int(data.get("pending", 0) or 0)),
        }
        self._analysis_running = False
        self._refresh_library_status()
        self._refresh_plan_usage()

    def set_analysis_progress(self, status: object | None) -> None:
        state = str(getattr(status, "state", "idle"))
        active = state in {
            "preparing", "scanning", "initializing_worker", "running",
            "pausing", "paused", "cancelling", "closing",
        }
        self._analysis_running = active
        if not active:
            self._refresh_library_status()
            return
        completed = max(0, int(getattr(status, "completed", 0) or 0))
        required = max(0, int(getattr(status, "total_requires_ocr", 0) or 0))
        analyzed = min(
            self._analysis_summary["total"],
            self._analysis_summary["analyzed"] + completed,
        )
        self._render_library_values(analyzed)
        self._analysis_state.setText(
            t("home.dashboard.analysis_progress", completed=completed, total=required)
        )

    def refresh(self) -> None:
        folder = get_selected_folder(self._config, self._app_root)
        count, _nbytes = collect_selected_folder_totals(folder)
        self._folder_total = count
        self._folder_path.setText(str(folder) if folder else "—")
        if self._analysis_summary["total"] != count and not self._analysis_running:
            self._analysis_summary = {"total": count, "analyzed": 0, "pending": count}
        self._refresh_library_status()
        self._refresh_plan_usage()

    def _refresh_library_status(self) -> None:
        self._render_library_values(self._analysis_summary["analyzed"])
        if self._analysis_summary["pending"]:
            self._analysis_state.setText(
                t("home.dashboard.pending_count", count=self._analysis_summary["pending"])
            )
        else:
            self._analysis_state.setText(t("home.dashboard.all_searchable"))

    def _render_library_values(self, analyzed: int) -> None:
        total = self._folder_total
        analyzed = min(max(0, analyzed), total)
        pending = max(0, total - analyzed)
        rate = round((analyzed / total) * 100) if total else 0
        self._total_value.setText(str(total))
        self._analyzed_value.setText(f"{analyzed} / {total}")
        self._pending_value.setText(str(pending))
        self._analysis_progress.setValue(rate)

    def _refresh_plan_usage(self) -> None:
        if self._plan_usage_override is not None:
            plan, used, limit = self._plan_usage_override
        else:
            plan = t("home.dashboard.plan_placeholder")
            limit = 0  # Prototype plan has no analysis-image cap.
            used = max(
                0,
                int(
                    self._config.get(
                        "analysis_images_used", self._analysis_summary["analyzed"]
                    )
                    or 0
                ),
            )
        used = min(used, limit) if limit else used
        self._plan_name.setText(plan)
        self._usage_donut.set_usage(used, limit)
        if self._usage_donut.unlimited:
            self._usage_caption.setText(
                t("home.dashboard.usage_caption_unlimited", used=used)
            )
        else:
            self._usage_caption.setText(
                t(
                    "home.dashboard.usage_caption",
                    used=used,
                    remaining=self._usage_donut.remaining,
                    limit=limit,
                )
            )
