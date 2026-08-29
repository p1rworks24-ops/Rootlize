"""Grab 1600x900 shots of the 3-column Search workspace."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.metadata_service import MetadataService
from app.ui.main_window import MainWindow
from app.ui.styles import APP_STYLE
from app.utils.thumbnail_cache import ThumbnailCache


def _png(path: Path) -> None:
    image = QImage(24, 24, QImage.Format_RGB32)
    image.fill(Qt.darkCyan)
    image.save(str(path), "PNG")


def main() -> int:
    out = ROOT / "artifacts" / "search-3col-layout-verify"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    tmp = Path(tempfile.mkdtemp(prefix="capixe-3col-"))
    folder = tmp / "shots"
    folder.mkdir()
    for index in range(8):
        _png(folder / f"shot-{index:02d}.png")

    window = MainWindow(
        {
            "screenshot_dir": str(tmp / "screenshots"),
            "selected_folder": str(folder),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1600,
            "window_height": 900,
            "window_title": "Capixe",
            "ask_ai_external_processing_consented": True,
        }
    )
    window.show()
    app.processEvents()
    window.resize(1600, 900)
    app.processEvents()
    page = window._images_page
    page.refresh()
    app.processEvents()

    item = page._list_widget.item(0)
    if item is not None:
        page._list_widget.setCurrentItem(item)
        item.setSelected(True)
        page._show_image(item)
        app.processEvents()

    window.grab().save(str(out / "preview-1600x900.png"))
    page._show_ai_panel()
    app.processEvents()
    window.grab().save(str(out / "ai-chat-1600x900.png"))
    page._show_preview_panel()
    app.processEvents()

    hbar = page._list_widget.horizontalScrollBar()
    payload = {
        "window": [window.width(), window.height()],
        "sidebar": window._side_nav.width(),
        "list": page._list_panel.width(),
        "right": page._right_panel.width(),
        "right_visible": (not page._right_panel.isHidden()),
        "preview_visible": page._preview_card.isVisible(),
        "ask_ai_on_preview": page._ask_ai_btn.parentWidget() is page._preview_page,
        "recents_hidden": window._side_nav._recents_header.isHidden(),
        "hscroll_max": hbar.maximum(),
        "search_mode": page._active_search_mode,
        "search_intent_removed": not hasattr(page, "_search_mode_toggle"),
    }
    (out / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    window.close()
    print(json.dumps(payload, indent=2))
    ok = (
        payload["right_visible"]
        and payload["preview_visible"]
        and payload["ask_ai_on_preview"]
        and payload["recents_hidden"]
        and payload["hscroll_max"] == 0
        and payload["search_mode"] == "text"
        and payload["list"] > payload["right"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
