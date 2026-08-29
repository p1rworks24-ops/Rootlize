"""Grab Search workspace metrics and widget shots at 1600x900.

Uses ImagesPage only so it does not rewrite %APPDATA%\\Capixe\\config.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ITEM_KIND_HEADER, ITEM_KIND_ROLE, ImagesPage
from app.ui.styles import APP_STYLE
from app.utils.group_by import GROUP_BY_NONE
from app.utils.thumbnail_cache import ThumbnailCache


def _png(path: Path) -> None:
    image = QImage(24, 24, QImage.Format_RGB32)
    image.fill(Qt.darkCyan)
    image.save(str(path), "PNG")


def main() -> int:
    out = ROOT / "artifacts" / "search-workspace-layout-verify"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    tmp = Path(tempfile.mkdtemp(prefix="capixe-ui-verify-"))
    folder = tmp / "shots"
    folder.mkdir()
    for index in range(10):
        _png(folder / f"shot-{index:02d}.png")

    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp / "screenshots"),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1600,
            "window_height": 900,
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp,
    )
    page.setStyleSheet(APP_STYLE)
    page.resize(1600, 900)
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    page._set_gallery_layout("grid")
    page._thumbnail_mode = "large"
    page._apply_thumbnail_mode()
    app.processEvents()

    def grid_report() -> dict:
        columns, card_w, header_w = page._responsive_grid_metrics()
        hbar = page._list_widget.horizontalScrollBar()
        return {
            "page": [page.width(), page.height()],
            "viewport_w": page._list_widget.viewport().width(),
            "columns": columns,
            "card_w": card_w,
            "header_w": header_w,
            "hscroll_max": hbar.maximum(),
            "group_by": page._group_by,
            "headers": sum(
                1
                for i in range(page._list_widget.count())
                if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER
            ),
        }

    wide = grid_report()
    page._list_widget.grab().save(str(out / "grid-1600.png"))
    page.grab().save(str(out / "page-1600x900.png"))

    page.resize(1100, 900)
    app.processEvents()
    page._relayout_gallery_grid()
    app.processEvents()
    mid = grid_report()
    page._list_widget.grab().save(str(out / "grid-1100.png"))

    page.resize(720, 900)
    app.processEvents()
    page._relayout_gallery_grid()
    app.processEvents()
    narrow = grid_report()
    page._list_widget.grab().save(str(out / "grid-720.png"))

    payload = {
        "wide": wide,
        "mid": mid,
        "narrow": narrow,
        "default_ungrouped": wide["group_by"] == GROUP_BY_NONE and wide["headers"] == 0,
        "no_hscroll": all(row["hscroll_max"] == 0 for row in (wide, mid, narrow)),
        "columns_reflow": wide["columns"] >= mid["columns"] >= narrow["columns"]
        and wide["columns"] > narrow["columns"],
        "search_intent_removed": page.findChild(QWidget, "searchIntentControl") is None,
    }
    (out / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    page.close()
    print(json.dumps(payload, indent=2))
    ok = (
        payload["no_hscroll"]
        and payload["columns_reflow"]
        and payload["default_ungrouped"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
