from app.utils.view_mode import (
    DEFAULT_THUMBNAIL_MODE,
    GRID_CARD_MIN_WIDTH,
    ICON_ITEM_MARGIN,
    THUMBNAIL_LIST_SPACING,
    THUMBNAIL_MODE_SIZES,
    compute_responsive_grid,
    normalize_thumbnail_mode,
)


def test_normalize_thumbnail_mode():
    assert normalize_thumbnail_mode("large") == "large"
    assert normalize_thumbnail_mode("medium") == "medium"
    assert normalize_thumbnail_mode("small") == "small"
    assert normalize_thumbnail_mode("details") == "small"
    assert normalize_thumbnail_mode("unknown") == DEFAULT_THUMBNAIL_MODE
    assert normalize_thumbnail_mode(None) == DEFAULT_THUMBNAIL_MODE


def test_compute_responsive_grid_fits_viewport():
    gap = THUMBNAIL_LIST_SPACING
    margin = ICON_ITEM_MARGIN
    min_card = GRID_CARD_MIN_WIDTH
    columns, card_w, header_w = compute_responsive_grid(1100, min_card)
    assert columns == 5
    occupied = columns * (card_w + 2 * margin + gap)
    assert occupied <= 1100
    assert header_w + 2 * margin + gap <= 1100
    assert header_w >= card_w
    assert card_w >= min_card

    one_col, one_w, one_header = compute_responsive_grid(200, min_card)
    assert one_col == 1
    assert one_w + 2 * margin + gap <= 200
    assert one_header + 2 * margin + gap <= 200


def test_responsive_grid_has_no_column_cap():
    min_card = THUMBNAIL_MODE_SIZES["large"][1]
    five, five_w, _ = compute_responsive_grid(1100, min_card)
    six, six_w, _ = compute_responsive_grid(1400, min_card)
    seven, seven_w, _ = compute_responsive_grid(1800, min_card)
    assert five == 5
    assert six >= 6
    assert seven >= 7
    assert five_w >= min_card
    assert six_w >= min_card
    assert seven_w >= min_card


if __name__ == "__main__":
    test_normalize_thumbnail_mode()
    test_compute_responsive_grid_fits_viewport()
    test_responsive_grid_has_no_column_cap()
    print("All view mode tests passed.")
