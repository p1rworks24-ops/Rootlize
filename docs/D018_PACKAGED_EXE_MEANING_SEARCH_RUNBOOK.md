# D-018 packaged EXE Meaning Search 最小実機確認

製品仕様は `.ai/SPEC.md`。このファイルは **packaged EXE の動作確認手順だけ** を正とする。

精度 PoC はしない。`shotlogue_test` など既存の大量フォルダは開かない。Vision 再解析を誘発する Settings の Re-analyze は使わない。

## 今回の確認対象

**最終確認対象は packaged EXE。開発起動（`Run Capixe.bat` / `main.py`）は最終対象にしない。**

使う EXE:

```text
D:\07_Programs\dev\ScreenshotManager\dist\Capixe\Capixe.exe
```

フォルダごと使う（`Capixe.exe` と `_internal`）。Explorer からではなく、API key を認識している PowerShell から起動する。

使わない:

* `artifacts\*\Capixe\Capixe.exe`（古い中間 build）
* 2026-08-18 以前の `dist\Capixe\Capixe.exe`（D-018 Current ではない）

確認対象は公式 `build-info.json` が `official=true` の `dist\Capixe\Capixe.exe` だけ。mtime が新しい別 EXE は使わない。`artifacts\` と `build\` の中間物は対象外。

## 推奨テスト画像

**新規フォルダに PNG/JPEG を 4 枚**（許容 3〜5）。既存ライブラリからのコピーでよい。元フォルダは開かない。

Query は精度評価しない。

* Q1: 4 枚のうち少なくとも 1 枚に当てはまる短い語（犬画像があるなら `dog`）
* Q2: 明らかに無い語（`giraffe`）
* 追加画像用に、まだ入れていない 5 枚目を 1 枚用意しておく

## API 消費見込み（4 枚の場合）

| 操作 | Vision `facts_generate` | text LLM `meaning_search` |
|---|---|---|
| 同意だけ | 0 | 0 |
| 初回 Q1（未解析 4 枚） | 4 | 準備完了後に 1 |
| 2 回目 Q2 | 0 | 1 |
| 同じ Q1 再実行（任意） | 0 | 1（cache 未実装のため動いてよい） |
| 1 枚追加のあと Q3 | 追加分 1 だけ | 1（準備待ちにならない） |
| 追加分の facts 完了後に Q4 | 0 | 1 |
| 再起動後の Q5 | 0 | 1 |

合計目安: **Vision 5、text LLM 4〜6**。query を増やさない。

## 見るファイル

* 診断ログ: `%LOCALAPPDATA%\Capixe\semantic-search.log`
* 使用量: `%LOCALAPPDATA%\Capixe\ai-usage.sqlite3`
* 同意: `%APPDATA%\Capixe\config.json` の `ask_ai_external_processing_consented`

UI は英語（製品既定）。

失敗したら、その Step の直後に log の末尾と usage DB を見る。アプリは一度終了してから DB を読む。

---

### Step 1 — テストフォルダを作る

空の新規フォルダを作り、画像を **4 枚だけ** コピーする。Capixe で開いたことがないパスにする。

成功: そのフォルダ直下に 4 枚だけある。サブフォルダは使わない。

失敗: `D:\07_Programs\shotlogue_test` や既存の大量フォルダを選んでしまったら中止。

### Step 2 — 同意を未同意にする

Capixe が動いていれば終了する。`%APPDATA%\Capixe\config.json` の `ask_ai_external_processing_consented` を `false` にする。キーが無ければそのままでよい。

成功: 次回 Ask AI で同意ダイアログが出る。

失敗: ダイアログが出ない場合はこのファイルを確認。同意済みのままだと Step 5 の「同意だけでは送らない」が観察できない。

### Step 3 — API key とベースライン

この PowerShell だけに key を載せる。画面や履歴に key を出さない。

```powershell
$capixeSecureKey = Read-Host 'OpenAI API key' -AsSecureString
$env:OPENAI_API_KEY = [Net.NetworkCredential]::new('', $capixeSecureKey).Password
if ([string]::IsNullOrEmpty($env:OPENAI_API_KEY)) { 'missing' } else { 'present' }
```

`present` だけを確認する。続けてベースライン:

```powershell
$log = Join-Path $env:LOCALAPPDATA 'Capixe\semantic-search.log'
$usage = Join-Path $env:LOCALAPPDATA 'Capixe\ai-usage.sqlite3'
'log_bytes=' + $(if (Test-Path $log) { (Get-Item $log).Length } else { 0 })
'usage_exists=' + (Test-Path $usage)
```

成功: `Capixe: present`。usage がまだ無くてよい。

失敗: `missing` なら EXE を起動しない。

### Step 4 — EXE を起動し、少数フォルダを開く

同じ PowerShell から:

```powershell
Start-Process 'D:\07_Programs\dev\ScreenshotManager\dist\Capixe\Capixe.exe'
```

Search で Step 1 のフォルダを選ぶ。`Preparing AI search…` → `AI search ready` を待つ。これはローカル OCR / OpenCLIP であり Vision ではない。

画面に `Set up meaning search to find images by what they show.` が出ていれば **Set up** でローカル導入だけ先に済ませる（Vision API ではない）。既に入っていればバナーは出ない。

成功: 4 枚が見える。`AI search ready`。Ask AI はまだ送っていない。

失敗: 大量フォルダを開いたら即終了。log に `image-facts chunk` や `Vision-relevance request-sent` がこの時点で増えていたら中止。

### Step 5 — Ask AI を開き、同意するだけ

`Ask AI →` を押す。`Before you use Ask AI` で **Agree**。query は送らない。数十秒待つ。

成功: Chat は空のまま。中央グリッドは通常一覧のまま。usage ファイルが無い、または Step 3 から増えていない。log 末尾に `image-facts chunk` / `Ask-AI meaning search start` が無い。

失敗: 同意直後に `Preparing your screenshots` や Vision request が出たら停止。log と usage を見る。

### Step 6 — 初回 Q1 を 1 回送る

Chat に Q1 を入れて Send。同じ query を連打しない。

準備中の成功:

* Chat: `Preparing your screenshots so they can be searched…`（`ready / total` が付いてよい）
* グリッド見出し: `AI search · "Q1" · Preparing screenshots…`
* 中央に部分ヒットが出ない（空）
* `Found N related images.` も `Searching…` の結果件数も出ない

準備完了後の成功（query の再入力なし）:

* Chat が `Searching…` になり、その後 `Found N related images.` または `No matching images were found.`
* グリッドが `AI results for "Q1" · N images`
* Q1 の `Ask-AI meaning search start` と `Meaning-search first request starting` が **1 回ずつ**
* その行に `search_vision=0`
* 準備中の区間に `Meaning-search first request starting` が無い

失敗: 部分結果が出る、自動検索が無い、同じ Q1 が 2 回走る。log で `Ask-AI meaning search start` の回数と `image-facts chunk` を見る。

### Step 7 — 同じフォルダで Q2 を送る

Q2 を 1 回送る。

成功:

* `Preparing screenshots` に戻らない
* すぐに `Searching…` → 結果（0 件でも完了表示）
* log に新しい `image-facts chunk` が無い
* 新しい `Meaning-search` 行は `search_vision=0`
* usage の Vision request が増えていない（アプリ終了後に Step 11 で確定してよい）

失敗: 準備待ちに入る、Vision 再解析が走る。log の `image-facts chunk` と `jpeg_images=` を見る。

### Step 8 — 同じ Q1 を再実行する（任意）

Q1 をもう 1 回だけ送る。cache 未実装なので text LLM が再実行されてよい。

成功: 準備待ちなし。Vision 増分 0。結果が出る。

失敗: `image-facts chunk` が再実行される。usage の `reparse_count` / `facts_version_regen_count` を見る。

### Step 9 — 画像を 1 枚追加する

初回準備が終わった状態で、テストフォルダへ **まだ使っていない 1 枚** をコピーする。続けて短い query を 1 回送る（Q2 の再利用でよい）。

成功:

* 検索は準備待ちにならない
* log の `image-facts chunk` が `needed=1 chunk=1`（既存 4 枚分ではない）
* usage の Vision 増分が 1（`first_image_count` 増、`reparse_count` 0）
* 追加画像の facts が終わる前の結果に、その画像が含まれなくてよい
* facts 完了後にもう 1 回だけ検索すると、追加画像も対象になり得る

失敗: 既存 4 枚も含めて再解析される。usage の `image_count` と `reparse_count` を見る。

### Step 10 — アプリを終了して再起動する

Capixe を終了し、Step 3 と同じ PowerShell から同じ EXE を起動する。同じテストフォルダを開く。Ask AI で短い query を 1 回送る。

成功:

* 全画像の `Preparing screenshots` が始まらない
* `image-facts chunk` が全件分で走らない
* Vision request が増えない
* Meaning Search の結果が出る（0 件でも完了）

失敗: 起動やフォルダ選択だけで Vision が走る。log と usage を見る。

### Step 11 — usage DB を見る

Capixe を終了してから実行する。

```powershell
& 'D:\07_Programs\dev\ScreenshotManager\.build-venv\Scripts\python.exe' -c @"
from pathlib import Path
import os, sqlite3
p = Path(os.environ['LOCALAPPDATA']) / 'Capixe' / 'ai-usage.sqlite3'
print('path', p)
print('exists', p.exists())
if not p.exists():
    raise SystemExit('missing usage db')
con = sqlite3.connect(p)
print('--- totals ---')
for row in con.execute('SELECT metric, value FROM ai_usage_totals ORDER BY metric'):
    print(row[0], row[1])
print('--- events ---')
for row in con.execute('''
SELECT event_id, occurred_at, kind, operation, model, request_count,
       image_count, first_image_count, reparse_count, facts_version_regen_count,
       query_count, candidate_count, batch_count, matcher_image_count
FROM ai_usage_events ORDER BY event_id'''):
    print(row)
cols = [r[1] for r in con.execute('PRAGMA table_info(ai_usage_events)')]
print('--- event columns ---')
print(cols)
raw = p.read_bytes()
needles = [b'giraffe', b'shotlogue_test']
print('--- substring hits (must be 0) ---')
for n in needles:
    print(n, raw.lower().count(n.lower()))
"@
```

成功の目安（4 枚 + 追加 1 枚、Q1/Q2/追加後/再起動を実施し、Step 8 を省略）:

* `vision.request_count` = 5
* `vision.facts_image_count` = 5
* `vision.reparse_count` = 0
* `vision.facts_version_regen_count` = 0
* `facts_generate` の Vision event と `meaning_search` の text event が操作回数と一致
* `search.text_llm_request_count` は送った query 数（各 1 batch。4〜5 枚なら query あたり 1）
* カラムに query / path / filename / facts JSON が無い
* 使った query やファイル名が DB バイト列に含まれない（上は `giraffe` の例。Q1 とコピーしたファイル名でも同様に 0 を確認）

失敗: Vision が枚数より多い、再解析がある、query や path が保存されている。

### Step 12 — budget 拒否（mock のみ、1 回）

packaged EXE に budget mock / quota 設定は無い。**実 API で拒否テストをしない。**

リポジトリルートで:

```powershell
& '.\.build-venv\Scripts\python.exe' -m pytest -q test_ai_budget.py
```

成功: テストが通る。HTTP 送信前に拒否され、request が消費されない。

失敗: pytest が落ちる。packaged EXE で quota を触らない。

EXE 上の budget 拒否 UI は、現行では確認手段が無い（後述の残課題）。

---

## 成功判定

全部 Yes ならこの Runbook は成功。

* 同意だけでは Vision が走らない
* 最初の Send で facts 生成が始まる
* 準備中は部分結果なし、matcher 未起動
* 準備完了後に Q1 が自動で 1 回だけ実行される
* 2 回目以降は準備待ちなし、検索時 Vision 0
* 追加画像だけが progressive 生成される
* 再起動後は fresh facts を再利用する
* usage が操作と一致し、query / path を保存しない
* budget 拒否は pytest で HTTP 前拒否を確認した

## 実機確認後に残るリリース前課題

この Runbook は動作確認であり、精度評価でも quota 方針でもない。

* `check_ai_budget` の quota 値が未設定。製品 UI の budget 拒否表示は未確認
* packaged EXE に budget mock が無い
* 残る facts completeness FN（製品として許容済み）
* query cache 未実装（同じ query の text LLM 再実行は仕様）
* 公開 README / website / ZIP README は現行 Search + Ask AI と不一致
* Semantic bundle 導入導線の独立実機確認は別件
