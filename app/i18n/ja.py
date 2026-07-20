"""Japanese UI message catalog (partial — falls back to English for missing keys)."""

MESSAGES: dict[str, str] = {
    # Home empty state
    "home.empty_title": "まだスクリーンショットがありません",
    "home.empty_body": (
        "画面下部の「Capture」から最初のスクリーンショットを撮影できます。"
    ),
    "home.empty_save_hint": "撮影した画像は「Capture」フォルダに保存されます。",
    # Images empty state
    "images.empty_title": "このフォルダには画像がありません。",
    "images.empty_body": (
        "「Capture」で撮影するか、別のフォルダを選択してください。"
    ),
}
