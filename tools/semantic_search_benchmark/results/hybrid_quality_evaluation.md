# Hybrid Search 実画像品質評価

画像: 130（写真70、疑似UI 60） / query: 64（同一set）

## 結論

* 現行 `RRF k=60 / candidate_limit=100 / Text:Semantic=1:1` を維持する。
* HybridはText比で56 query、Semantic比で4 query改善し、いずれに対しても悪化は0 queryだった。
* TextとSemanticの両方が有効なexact query 8件はすべてHybrid Top-1。Semantic-only 56件はHybridでSemantic順位を維持し、Textに埋もれなかった。
* exact queryではSemantic単体が23位、14位、30位、54位だった4件をHybridがすべて1位へ戻した。Semanticノイズによるexact検索の悪化は観測しなかった。
* 日本語28 queryはText一致0件のためHybrid=Semantic（Top-1 42.9%、Top-5 75.0%）。英語36 queryはOCR exact 8件が加わりHybrid Top-1 75.0%、Top-5 91.7%。言語差は主に英語文字だけのfixtureに由来するため、日本語OCR文字を含むfixtureでの追試が必要。
* `k=0/10/30/60/100` と重み `1:1 / 2:1 / 1:2` は候補100で集計値が同一。現時点で定数・重みを変更する根拠はない。
* 候補100→50でTop-1が60.9%→59.4%、20で56.2%、10以下で54.7%へ低下した。候補100は十分かつ削減非推奨。

## Baseline集計

|方式|Top-1|Top-3|Top-5|
|---|---:|---:|---:|
|Text|12.5%|12.5%|12.5%|
|Semantic|54.7%|62.5%|78.1%|
|Hybrid|60.9%|68.8%|84.4%|

## Query別順位

`-` は正解なし。

|ID|Lang|Query|Text|Semantic|Hybrid|
|---|---|---|---:|---:|---:|
|dog-ja-l1|ja|犬|-|1|1|
|dog-en-l1|en|a dog|-|1|1|
|cat-ja-l1|ja|猫|-|5|5|
|cat-en-l1|en|a cat|-|5|5|
|car-ja-l1|ja|車|-|3|3|
|car-en-l1|en|a car|-|27|27|
|person-ja-l1|ja|人物|-|7|7|
|person-en-l1|en|a person|-|1|1|
|food-ja-l1|ja|料理や食べ物|-|18|18|
|food-en-l1|en|food or a meal|-|4|4|
|laptop-ja-l1|ja|ノートPC|-|43|43|
|laptop-en-l1|en|a laptop computer|-|1|1|
|snow-ja-l2|ja|雪景色|-|2|2|
|snow-en-l2|en|a snowy scene|-|1|1|
|beach-ja-l2|ja|海辺|-|4|4|
|beach-en-l2|en|a beach by the sea|-|1|1|
|city-ja-l2|ja|街の風景|-|2|2|
|city-en-l2|en|a city scene|-|3|3|
|night-ja-l2|ja|夜の風景|-|5|5|
|night-en-l2|en|a scene at night|-|5|5|
|indoor-ja-l2|ja|室内の写真|-|13|13|
|indoor-en-l2|en|an indoor photo|-|1|1|
|outdoor-ja-l2|ja|屋外の写真|-|6|6|
|outdoor-en-l2|en|an outdoor photo|-|1|1|
|dog running-ja-l3|ja|走っている犬|-|1|1|
|dog running-en-l3|en|a dog running|-|1|1|
|person cooking-ja-l3|ja|料理している人|-|4|4|
|person cooking-en-l3|en|a person cooking|-|5|5|
|person walking-ja-l3|ja|歩いている人|-|2|2|
|person walking-en-l3|en|a person walking|-|6|6|
|person laptop-ja-l3|ja|PCを使っている人|-|37|37|
|person laptop-en-l3|en|a person using a computer|-|1|1|
|code_editor-ja-l4|ja|コードを書いている画面|-|1|1|
|code_editor-en-l4|en|a screen showing source code|-|1|1|
|terminal-ja-l4|ja|ターミナル画面|-|1|1|
|terminal-en-l4|en|a terminal command line screen|-|1|1|
|error_dialog-ja-l4|ja|エラーが表示されている画面|-|1|1|
|error_dialog-en-l4|en|a computer screen showing an error|-|1|1|
|settings-ja-l4|ja|設定画面|-|1|1|
|settings-en-l4|en|an application settings screen|-|1|1|
|product_page-ja-l4|ja|商品ページ|-|12|12|
|product_page-en-l4|en|an online product page|-|1|1|
|comparison_page-ja-l4|ja|商品を比較している画面|-|1|1|
|comparison_page-en-l4|en|a screen comparing products|-|8|8|
|login_screen-ja-l4|ja|ログイン画面|-|1|1|
|login_screen-en-l4|en|a login screen|-|1|1|
|dashboard-ja-l4|ja|統計ダッシュボード|-|1|1|
|dashboard-en-l4|en|an analytics dashboard|-|1|1|
|documentation-ja-l4|ja|ドキュメントを読んでいる画面|-|1|1|
|documentation-en-l4|en|a software documentation page|-|1|1|
|comparison_page-ja-l5|ja|価格を比較している画像|-|1|1|
|comparison_page-en-l5|en|an image comparing prices|-|1|1|
|login_failure-ja-l5|ja|ログインに失敗している画面|-|4|4|
|login_failure-en-l5|en|a failed login screen|-|4|4|
|problem-ja-l5|ja|何か問題が起きているPC画面|-|1|1|
|problem-en-l5|en|a computer screen where something went wrong|-|1|1|
|exact-error-title-en|en|Something went wrong|1|1|1|
|exact-error-body-en|en|The request could not be completed|1|1|1|
|exact-login-error-en|en|Incorrect password|1|1|1|
|exact-doc-ui-en|en|Semantic Search API|1|23|1|
|exact-settings-ui-en|en|Search indexing|1|14|1|
|exact-product-en|en|Aurora Headphones|1|30|1|
|exact-comparison-en|en|Cloud sync|1|54|1|
|exact-terminal-en|en|capixe analyze ./images|1|1|1|

## 改善・悪化

改善: dog-ja-l1, dog-en-l1, cat-ja-l1, cat-en-l1, car-ja-l1, car-en-l1, person-ja-l1, person-en-l1, food-ja-l1, food-en-l1, laptop-ja-l1, laptop-en-l1, snow-ja-l2, snow-en-l2, beach-ja-l2, beach-en-l2, city-ja-l2, city-en-l2, night-ja-l2, night-en-l2, indoor-ja-l2, indoor-en-l2, outdoor-ja-l2, outdoor-en-l2, dog running-ja-l3, dog running-en-l3, person cooking-ja-l3, person cooking-en-l3, person walking-ja-l3, person walking-en-l3, person laptop-ja-l3, person laptop-en-l3, code_editor-ja-l4, code_editor-en-l4, terminal-ja-l4, terminal-en-l4, error_dialog-ja-l4, error_dialog-en-l4, settings-ja-l4, settings-en-l4, product_page-ja-l4, product_page-en-l4, comparison_page-ja-l4, comparison_page-en-l4, login_screen-ja-l4, login_screen-en-l4, dashboard-ja-l4, dashboard-en-l4, documentation-ja-l4, documentation-en-l4, comparison_page-ja-l5, comparison_page-en-l5, login_failure-ja-l5, login_failure-en-l5, problem-ja-l5, problem-en-l5, exact-doc-ui-en, exact-settings-ui-en, exact-product-en, exact-comparison-en

悪化: なし

## Parameter grid 上位

|k|候補|Text重み|Semantic重み|Top-1|Top-3|Top-5|
|---:|---:|---:|---:|---:|---:|---:|
|60|5|2|1|60.9%|68.8%|84.4%|
|60|10|2|1|60.9%|68.8%|84.4%|
|60|20|2|1|60.9%|68.8%|84.4%|
|60|50|2|1|60.9%|68.8%|84.4%|
|60|100|1|1|60.9%|68.8%|84.4%|
|60|100|2|1|60.9%|68.8%|84.4%|
|60|100|1|2|60.9%|68.8%|84.4%|
|30|5|2|1|60.9%|68.8%|84.4%|
|30|10|2|1|60.9%|68.8%|84.4%|
|30|20|2|1|60.9%|68.8%|84.4%|
