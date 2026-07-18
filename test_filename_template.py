"""Unit tests for filename templates and collision numbering."""

from datetime import datetime
from pathlib import Path

from app.utils.filename_template import (
    make_unique_stem,
    preview_filename,
    render_template,
    resolve_screenshot_filename,
    template_uses_num,
)


def test_render_date_time():
    when = datetime(2026, 7, 15, 22, 15, 30)
    assert render_template("{date}_{time}", when=when) == "20260715_221530"


def test_render_folder_num():
    when = datetime(2026, 7, 15, 12, 0, 0)
    assert (
        render_template("{folder}_{num}", when=when, folder="Capture", num=3)
        == "Capture_003"
    )


def test_preview_filename():
    when = datetime(2026, 7, 15, 22, 15, 30)
    assert (
        preview_filename("{date}_{time}", folder="Capture", when=when)
        == "20260715_221530.png"
    )


def test_template_uses_num():
    assert template_uses_num("testshot_{num}")
    assert not template_uses_num("{date}_{time}")


def test_make_unique_stem_collision(tmp_path: Path):
    (tmp_path / "shot.png").write_bytes(b"x")
    assert make_unique_stem(tmp_path, "shot") == "shot_001"
    (tmp_path / "shot_001.png").write_bytes(b"x")
    assert make_unique_stem(tmp_path, "shot") == "shot_002"


def test_resolve_date_time_collision(tmp_path: Path):
    when = datetime(2026, 7, 15, 22, 15, 30)
    name1 = resolve_screenshot_filename(
        tmp_path, "{date}_{time}", folder="Capture", when=when
    )
    assert name1 == "20260715_221530.png"
    (tmp_path / name1).write_bytes(b"x")
    name2 = resolve_screenshot_filename(
        tmp_path, "{date}_{time}", folder="Capture", when=when
    )
    assert name2 == "20260715_221530_001.png"


def test_resolve_testshot_num_sequence(tmp_path: Path):
    when = datetime(2026, 7, 15, 10, 0, 0)
    n1 = resolve_screenshot_filename(
        tmp_path, "testshot_{num}", folder="Capture", when=when
    )
    assert n1 == "testshot_001.png"
    (tmp_path / n1).write_bytes(b"x")
    n2 = resolve_screenshot_filename(
        tmp_path, "testshot_{num}", folder="Capture", when=when
    )
    assert n2 == "testshot_002.png"
