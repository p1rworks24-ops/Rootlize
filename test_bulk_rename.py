"""Tests for bulk sequential rename and Work helpers."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from app.utils.bulk_rename import build_sequential_names, sort_paths_oldest_first


def _write_png(path: Path) -> None:
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.red)
    assert image.save(str(path), "PNG")


def test_build_sequential_names_oldest_first():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = root / "a.png"
        b = root / "b.png"
        c = root / "c.png"
        _write_png(a)
        time.sleep(0.02)
        _write_png(b)
        time.sleep(0.02)
        _write_png(c)

        # Pass in reverse order; output must still be oldest-first
        mapping = build_sequential_names([c, a, b], "ScreenShot_test_", 3)
        assert [m[1] for m in mapping] == [
            "ScreenShot_test_001.png",
            "ScreenShot_test_002.png",
            "ScreenShot_test_003.png",
        ]
        assert mapping[0][0].name == "a.png"
        assert mapping[1][0].name == "b.png"
        assert mapping[2][0].name == "c.png"


def test_build_sequential_names_expands_digits():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = []
        for i in range(12):
            p = root / f"f{i}.png"
            _write_png(p)
            # Force increasing mtimes
            os.utime(p, (1000 + i, 1000 + i))
            paths.append(p)

        mapping = build_sequential_names(paths, "Shot_", 3)
        assert mapping[0][1] == "Shot_001.png"
        assert mapping[9][1] == "Shot_010.png"
        assert mapping[11][1] == "Shot_012.png"


def test_sort_paths_oldest_first():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        newer = root / "new.png"
        older = root / "old.png"
        _write_png(older)
        os.utime(older, (1000, 1000))
        _write_png(newer)
        os.utime(newer, (2000, 2000))
        assert sort_paths_oldest_first([newer, older]) == [older, newer]


if __name__ == "__main__":
    test_build_sequential_names_oldest_first()
    test_build_sequential_names_expands_digits()
    test_sort_paths_oldest_first()
    print("All bulk rename tests passed.")
