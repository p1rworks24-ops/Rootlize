"""Home tag stats: No tags row at bottom; hidden without Root Folder."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.utils.workspace_stats import NO_TAG_ACCENT, collect_tag_stats


def _png(folder: Path, name: str) -> Path:
    path = folder / name
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(Qt.green)
    img.save(str(path))
    return path


def test_collect_tag_stats_appends_no_tag_at_bottom():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "screenshots" / "Capture"
        folder.mkdir(parents=True)
        a = _png(folder, "a.png")
        b = _png(folder, "b.png")
        c = _png(folder, "c.png")
        svc = MetadataService()
        svc.ensure_global_tag(root, "alpha")
        svc.add_image_tag(folder, a.name, "alpha")
        svc.add_image_tag(folder, b.name, "alpha")
        # c stays untagged

        rows = collect_tag_stats(str(root / "screenshots"), root, svc)
        assert rows
        assert rows[-1].label == t("group_by.no_tag")
        assert rows[-1].count == 1
        assert rows[-1].accent == NO_TAG_ACCENT
        assert rows[-1].apply_prefix is False
        assert any(r.label == "alpha" and r.count == 2 for r in rows[:-1])


def test_collect_tag_stats_hidden_without_root_folder():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        missing = root / "does_not_exist"
        rows = collect_tag_stats(str(missing), root, MetadataService())
        assert rows == []

        rows_empty = collect_tag_stats("", root, MetadataService())
        assert rows_empty == []
