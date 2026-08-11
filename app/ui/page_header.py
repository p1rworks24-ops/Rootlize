"""Shared page title + subtitle chrome for all main pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui.design_tokens import (
    ICON_LG,
    ICON_XL,
    PAGE_HEADER_SYMBOL_DOT,
    PAGE_HEADER_SYMBOL_GLOW,
    PAGE_HEADER_SYMBOL_HERO,
    PAGE_HEADER_SYMBOL_SHAPE,
)

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
    icon: QIcon | None = None,
    accent: str = "primary",
    emphasis: str = "standard",
) -> QWidget:
    """
    Build a pageHeader with pageTitle + pageSubtitle.

    Use the same margins on every page so titles line up across navigation.
    Accent colors stay page-specific via CSS wrappers (e.g. homeContentColumn).
    """
    header = QWidget(parent)
    header.setObjectName("pageHeader")
    header.setProperty("emphasis", emphasis)
    layout = QHBoxLayout(header)
    m = margins if margins is not None else (0, 0, 0, 0)
    layout.setContentsMargins(*m)
    layout.setSpacing(PAGE_HEADER_TITLE_SPACING)

    if icon is not None and not icon.isNull():
        symbol = QFrame(header)
        symbol.setObjectName("pageHeaderSymbol")
        symbol.setProperty("accent", accent)
        symbol.setProperty("hero", emphasis == "hero")
        symbol_size = PAGE_HEADER_SYMBOL_HERO if emphasis == "hero" else 40
        icon_size = ICON_XL if emphasis == "hero" else ICON_LG
        symbol.setFixedSize(symbol_size, symbol_size)
        symbol_layout = QGridLayout(symbol)
        symbol_layout.setContentsMargins(0, 0, 0, 0)
        symbol_layout.setSpacing(0)
        if emphasis == "hero":
            glow = QFrame(symbol)
            glow.setObjectName("pageHeaderSymbolGlow")
            glow.setFixedSize(PAGE_HEADER_SYMBOL_GLOW, PAGE_HEADER_SYMBOL_GLOW)
            symbol_layout.addWidget(glow, 0, 0, Qt.AlignLeft | Qt.AlignBottom)

            shape = QFrame(symbol)
            shape.setObjectName("pageHeaderSymbolShape")
            shape.setFixedSize(PAGE_HEADER_SYMBOL_SHAPE, PAGE_HEADER_SYMBOL_SHAPE)
            symbol_layout.addWidget(shape, 0, 0, Qt.AlignCenter)

            dot = QFrame(symbol)
            dot.setObjectName("pageHeaderSymbolDot")
            dot.setFixedSize(PAGE_HEADER_SYMBOL_DOT, PAGE_HEADER_SYMBOL_DOT)
            symbol_layout.addWidget(dot, 0, 0, Qt.AlignRight | Qt.AlignTop)
        symbol_label = QLabel(symbol)
        symbol_label.setObjectName("pageHeaderSymbolIcon")
        symbol_label.setAlignment(Qt.AlignCenter)
        symbol_label.setPixmap(icon.pixmap(QSize(icon_size, icon_size)))
        symbol_layout.addWidget(symbol_label, 0, 0, Qt.AlignCenter)
        layout.addWidget(symbol, 0, Qt.AlignTop)

    text_column = QWidget(header)
    text_column.setObjectName("pageHeaderText")
    text_layout = QVBoxLayout(text_column)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(PAGE_HEADER_TITLE_SPACING)

    title_label = QLabel(title, text_column)
    title_label.setObjectName("pageTitle")
    text_layout.addWidget(title_label)

    subtitle_label = QLabel(subtitle, text_column)
    subtitle_label.setObjectName("pageSubtitle")
    subtitle_label.setWordWrap(True)
    text_layout.addWidget(subtitle_label)
    layout.addWidget(text_column, 1)
    return header
