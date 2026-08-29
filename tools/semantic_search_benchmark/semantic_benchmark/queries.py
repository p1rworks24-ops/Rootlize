from __future__ import annotations

PHOTO_QUERIES = [
    ("dog", "犬", "a dog", 1), ("cat", "猫", "a cat", 1), ("car", "車", "a car", 1),
    ("person", "人物", "a person", 1), ("food", "料理や食べ物", "food or a meal", 1),
    ("laptop", "ノートPC", "a laptop computer", 1),
    ("snow", "雪景色", "a snowy scene", 2), ("beach", "海辺", "a beach by the sea", 2),
    ("city", "街の風景", "a city scene", 2), ("night", "夜の風景", "a scene at night", 2),
    ("indoor", "室内の写真", "an indoor photo", 2), ("outdoor", "屋外の写真", "an outdoor photo", 2),
    ("dog running", "走っている犬", "a dog running", 3),
    ("person cooking", "料理している人", "a person cooking", 3),
    ("person walking", "歩いている人", "a person walking", 3),
    ("person laptop", "PCを使っている人", "a person using a computer", 3),
]

SCREEN_QUERIES = [
    ("code_editor", "コードを書いている画面", "a screen showing source code", 4),
    ("terminal", "ターミナル画面", "a terminal command line screen", 4),
    ("error_dialog", "エラーが表示されている画面", "a computer screen showing an error", 4),
    ("settings", "設定画面", "an application settings screen", 4),
    ("product_page", "商品ページ", "an online product page", 4),
    ("comparison_page", "商品を比較している画面", "a screen comparing products", 4),
    ("login_screen", "ログイン画面", "a login screen", 4),
    ("dashboard", "統計ダッシュボード", "an analytics dashboard", 4),
    ("documentation", "ドキュメントを読んでいる画面", "a software documentation page", 4),
    ("comparison_page", "価格を比較している画像", "an image comparing prices", 5),
    ("login_failure", "ログインに失敗している画面", "a failed login screen", 5),
    ("problem", "何か問題が起きているPC画面", "a computer screen where something went wrong", 5),
]


def build_queries(records: list[dict]) -> list[dict]:
    queries = []
    for key, ja, en, level in PHOTO_QUERIES + SCREEN_QUERIES:
        relevant = []
        for item in records:
            haystack = " ".join(item.get("labels", []) + item.get("captions", [])).lower()
            screen_type = item.get("metadata", {}).get("screen_type", "")
            if key == "food" and any(x in haystack for x in ["banana", "apple", "sandwich", "orange", "broccoli", "carrot", "pizza", "donut", "cake", "food"]):
                relevant.append(item["id"])
            elif key == "login_failure" and "login failure" in haystack:
                relevant.append(item["id"])
            elif key == "problem" and any(x in haystack for x in ["error", "failure", "problem"]):
                relevant.append(item["id"])
            elif key == screen_type:
                relevant.append(item["id"])
            elif all(token in haystack for token in key.split("_")) or all(token in haystack for token in key.split()):
                relevant.append(item["id"])
        if not relevant:
            continue
        for language, text in [("ja", ja), ("en", en)]:
            queries.append({"id": f"{key}-{language}-l{level}", "language": language, "text": text, "level": level, "challenge": level == 5, "relevant": relevant})
    return queries
