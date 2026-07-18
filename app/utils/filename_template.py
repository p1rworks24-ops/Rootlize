"""Screenshot filename templates with collision numbering."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

DEFAULT_FILENAME_TEMPLATE = "{date}_{time}"

# (template, short label key suffix for i18n — labels resolved in UI)
FILENAME_TEMPLATE_PRESETS: list[str] = [
    "{date}_{time}",
    "{folder}_{num}",
    "Screenshot_{date}_{time}",
    "{date}_{folder}_{num}",
    "testshot_{num}",
]

_TOKEN_RE = re.compile(r"\{(date|time|folder|num)\}")
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]+')


def sanitize_stem(stem: str) -> str:
    cleaned = _INVALID_CHARS.sub("_", stem).strip(" .")
    return cleaned or "screenshot"


def render_template(
    template: str,
    *,
    when: datetime | None = None,
    folder: str = "Capture",
    num: int | None = None,
) -> str:
    """
    Expand tokens into a file stem (no extension).

    Tokens: {date} YYYYMMDD, {time} HHMMSS, {folder}, {num} zero-padded 3 digits.
    """
    when = when or datetime.now()
    tpl = (template or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE

    values = {
        "date": when.strftime("%Y%m%d"),
        "time": when.strftime("%H%M%S"),
        "folder": sanitize_stem(folder),
        "num": f"{(num or 1):03d}",
    }

    def repl(match: re.Match[str]) -> str:
        return values[match.group(1)]

    stem = _TOKEN_RE.sub(repl, tpl)
    # Leave unknown braces as-is but sanitize illegal path chars
    return sanitize_stem(stem)


def template_uses_num(template: str) -> bool:
    return "{num}" in (template or "")


def next_sequence_num(save_dir: Path, template: str, folder: str, when: datetime) -> int:
    """Find next {num} by scanning existing files for the same template pattern."""
    # Build a regex: render with a sentinel then replace
    sample = render_template(template, when=when, folder=folder, num=0)
    # Too brittle — instead scan all png and find max trailing _NNN or embedded num
    # Strategy: render with num=N and check existence; binary-ish search from 1
    n = 1
    while n < 100_000:
        stem = render_template(template, when=when, folder=folder, num=n)
        if not (save_dir / f"{stem}.png").exists():
            return n
        n += 1
    return n


def make_unique_stem(save_dir: Path, stem: str) -> str:
    """
    If stem.png exists, append _001, _002, ... (Explorer-like collision).
    Always suffixes the full stem so times like _221530 are not treated as numbers.
    """
    if not (save_dir / f"{stem}.png").exists():
        return stem

    n = 1
    while True:
        candidate = f"{stem}_{n:03d}"
        if not (save_dir / f"{candidate}.png").exists():
            return candidate
        n += 1


def resolve_screenshot_filename(
    save_dir: Path,
    template: str,
    *,
    folder: str,
    when: datetime | None = None,
) -> str:
    """
    Produce a unique .png filename from the template.
    Uses {num} sequencing when present; otherwise collision suffix _001.
    """
    when = when or datetime.now()
    tpl = (template or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE

    if template_uses_num(tpl):
        num = next_sequence_num(save_dir, tpl, folder, when)
        stem = render_template(tpl, when=when, folder=folder, num=num)
    else:
        stem = render_template(tpl, when=when, folder=folder, num=1)
        stem = make_unique_stem(save_dir, stem)

    return f"{stem}.png"


def preview_filename(
    template: str,
    *,
    folder: str = "Capture",
    when: datetime | None = None,
) -> str:
    """Example name shown under the template control."""
    when = when or datetime.now()
    tpl = (template or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE
    num = 1 if template_uses_num(tpl) else None
    stem = render_template(tpl, when=when, folder=folder, num=num or 1)
    return f"{stem}.png"
