from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)

from app.config import save_config
from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.icons import icon_images, icon_organize, icon_settings, icon_tags
from app.ui.segmented_toggle import SegmentedToggle
from app.ui.stats_chart import StatsChartPanel
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.workspace import resolve_screenshot_root
from app.utils.workspace_stats import (
    collect_folder_stats,
    collect_root_totals,
    collect_tag_stats,
    format_bytes,
)

STATS_FOLDER = "folder"
STATS_TAG = "tag"
# Wider than before for readable folder/tag bars; still short of full window edge
_CHART_MAX_WIDTH = 960
_CHART_VIEWPORT_HEIGHT = 300


class HomePage(QWidget):
    """Home dashboard: folder/tag stats charts and quick actions."""

    open_images_requested = Signal()
    open_action_requested = Signal()
    open_tags_requested = Signal()
    open_settings_requested = Signal()

    def __init__(
        self,
        config: dict,
        metadata_service: MetadataService,
        thumbnail_cache: ThumbnailCache,
        app_root: Path,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config
        self._metadata_service = metadata_service
        self._thumbnail_cache = thumbnail_cache
        self._app_root = app_root
        self._stats_mode = config.get("home_stats_mode", STATS_FOLDER)
        if self._stats_mode not in (STATS_FOLDER, STATS_TAG):
            self._stats_mode = STATS_FOLDER
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        from app.ui.scroll_page import make_page_scroll

        scroll = make_page_scroll(self)
        outer.addWidget(scroll)

        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)

        title = QLabel(t("home.title"), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(t("home.subtitle"), content)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Quick actions sit directly under the Home title
        actions_title = QLabel(t("home.quick_actions"), content)
        actions_title.setObjectName("sectionTitle")
        layout.addWidget(actions_title)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        for label_key, icon_fn, signal in (
            ("nav.images", icon_images, self.open_images_requested),
            ("nav.organize", icon_organize, self.open_action_requested),
            ("nav.tags", icon_tags, self.open_tags_requested),
            ("nav.settings", icon_settings, self.open_settings_requested),
        ):
            btn = QPushButton(t(label_key), content)
            btn.setObjectName("secondaryButton")
            btn.setIcon(icon_fn())
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(signal.emit)
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self._folder_card = self._create_stat_card(t("home.root_folder"), "-")
        self._count_card = self._create_stat_card(t("home.image_count"), "0")
        cards.addWidget(self._folder_card)
        cards.addWidget(self._count_card)
        cards.addStretch()
        layout.addLayout(cards)

        # Stats card: Statistics → Display by → [Folder|Tag] → chart
        chart_frame = QFrame(content)
        chart_frame.setObjectName("infoPanel")
        chart_frame.setMinimumWidth(860)
        chart_frame.setMaximumWidth(_CHART_MAX_WIDTH)
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(18, 16, 18, 16)
        chart_layout.setSpacing(10)

        stats_title = QLabel(t("home.stats"), chart_frame)
        stats_title.setObjectName("sectionTitle")
        chart_layout.addWidget(stats_title)

        view_label = QLabel(t("home.stats_view"), chart_frame)
        view_label.setObjectName("mutedLabel")
        chart_layout.addWidget(view_label)

        self._stats_toggle = SegmentedToggle(
            [t("home.stats_folder"), t("home.stats_tag")],
            chart_frame,
        )
        self._stats_toggle.set_current(1 if self._stats_mode == STATS_TAG else 0)
        self._stats_toggle.changed.connect(self._on_stats_mode_changed)
        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self._stats_toggle)
        toggle_row.addStretch(1)
        chart_layout.addLayout(toggle_row)

        hint = QLabel(t("home.stats_hint"), chart_frame)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        chart_layout.addWidget(hint)

        divider = QFrame(chart_frame)
        divider.setObjectName("sectionDivider")
        divider.setFixedHeight(1)
        divider.setFrameShape(QFrame.HLine)
        chart_layout.addWidget(divider)

        # Fixed viewport height so long folder/tag lists scroll inside the chart
        self._stats_chart = StatsChartPanel(chart_frame)
        self._stats_chart.setFixedHeight(_CHART_VIEWPORT_HEIGHT)
        chart_layout.addWidget(self._stats_chart, stretch=0)

        chart_row = QHBoxLayout()
        chart_row.setContentsMargins(0, 0, 0, 0)
        chart_row.addWidget(chart_frame, stretch=0)
        chart_row.addStretch(1)
        layout.addLayout(chart_row, stretch=0)

        layout.addStretch(1)

    def _create_stat_card(self, title: str, value: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("statCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(6)

        title_label = QLabel(title, card)
        title_label.setObjectName("mutedLabel")
        card_layout.addWidget(title_label)

        value_label = QLabel(value, card)
        value_label.setObjectName("statValue")
        card_layout.addWidget(value_label)

        card.value_label = value_label  # type: ignore[attr-defined]
        return card

    def _on_stats_mode_changed(self, index: int) -> None:
        self._stats_mode = STATS_TAG if index == 1 else STATS_FOLDER
        self._config["home_stats_mode"] = self._stats_mode
        try:
            save_config(self._config)
        except OSError:
            pass
        self._refresh_stats()

    def _root_label(self) -> str:
        """Display name for Settings Root Folder (screenshot root)."""
        root = resolve_screenshot_root(
            self._config.get("screenshot_dir", "screenshots"),
            self._app_root,
        )
        return root.name or str(root)

    def _refresh_stats(self) -> None:
        screenshot_dir = self._config.get("screenshot_dir", "screenshots")
        if self._stats_mode == STATS_TAG:
            rows = collect_tag_stats(
                screenshot_dir, self._app_root, self._metadata_service
            )
            self._stats_chart.set_rows(rows, label_prefix="#")
        else:
            rows = collect_folder_stats(
                screenshot_dir, self._app_root, self._metadata_service
            )
            self._stats_chart.set_rows(rows, label_prefix="")

    def refresh(self) -> None:
        self._folder_card.value_label.setText(self._root_label())  # type: ignore[attr-defined]

        count, nbytes = collect_root_totals(
            self._config.get("screenshot_dir", "screenshots"),
            self._app_root,
        )
        self._count_card.value_label.setText(  # type: ignore[attr-defined]
            t("home.root_totals", count=count, size=format_bytes(nbytes))
        )

        self._refresh_stats()
