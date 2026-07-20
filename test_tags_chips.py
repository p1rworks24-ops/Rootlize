"""Tags page uses compact chips and search."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QListWidget

from app.services.metadata_service import MetadataService
from app.ui.pages.tags_page import TagsPage


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_tags_page_uses_chips_not_full_width_list():
    app = _ensure_app()
    root = Path(tempfile.mkdtemp())
    (root / "screenshots").mkdir()
    service = MetadataService()
    service.add_global_tag(root, "alpha")
    service.add_global_tag(root, "beta")
    page = TagsPage(service, root, {})
    page.refresh()
    app.processEvents()

    assert page.findChild(QListWidget) is None
    assert "alpha" in page._chip_buttons
    assert page._chip_buttons["alpha"].objectName() == "tagMasterChip"


def test_tags_search_filters_chips():
    app = _ensure_app()
    root = Path(tempfile.mkdtemp())
    (root / "screenshots").mkdir()
    service = MetadataService()
    service.add_global_tag(root, "design")
    service.add_global_tag(root, "meeting")
    page = TagsPage(service, root, {})
    page.refresh()

    page._search_input.setText("meet")
    page._apply_filter()
    # isHidden() reflects setVisible(); isVisible() also requires a shown parent
    assert not page._chip_buttons["meeting"].isHidden()
    assert page._chip_buttons["design"].isHidden()


def test_tags_clear_search_relayouts_without_overlap():
    app = _ensure_app()
    root = Path(tempfile.mkdtemp())
    (root / "screenshots").mkdir()
    service = MetadataService()
    for name in ("alpha", "beta", "gamma", "delta"):
        service.add_global_tag(root, name)
    page = TagsPage(service, root, {})
    page.resize(480, 600)
    page.show()
    page.refresh()
    app.processEvents()

    page._search_input.setText("alp")
    page._apply_filter()
    app.processEvents()
    page._on_clear_search()
    app.processEvents()

    for btn in page._chip_buttons.values():
        assert not btn.isHidden()

    # Chip geometries must not overlap after restoring all tags
    geos = [btn.geometry() for btn in page._chip_buttons.values()]
    for i, a in enumerate(geos):
        for b in geos[i + 1 :]:
            assert not a.intersects(b), f"overlap {a} vs {b}"
