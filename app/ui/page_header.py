"""Shared page title + subtitle chrome for all main pages."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# Unified geometry — keep AI / future pages on the same grid
PAGE_HEADER_MARGINS = (28, 20, 28, 8)  # left, top, right, bottom
PAGE_HEADER_TITLE_SPACING = 6  # title → subtitle
PAGE_BODY_TOP_GAP = 12  # subtitle → first body content


def make_page_header(
    parent: QWidget,
    title: str,
    subtitle: str,
    *,
    margins: tuple[int, int, int, int] | None = None,
) -> QWidget:
    """
    Build a pageHeader with pageTitle + pageSubtitle.

    Use the same margins on every page so titles line up across navigation.
    Accent colors stay page-specific via CSS wrappers (e.g. homeContentColumn).
    """
    header = QWidget(parent)
    header.setObjectName("pageHeader")
    layout = QVBoxLayout(header)
    m = margins if margins is not None else (0, 0, 0, 0)
    layout.setContentsMargins(*m)
    layout.setSpacing(PAGE_HEADER_TITLE_SPACING)

    title_label = QLabel(title, header)
    title_label.setObjectName("pageTitle")
    layout.addWidget(title_label)

    subtitle_label = QLabel(subtitle, header)
    subtitle_label.setObjectName("pageSubtitle")
    subtitle_label.setWordWrap(True)
    layout.addWidget(subtitle_label)
    return header
