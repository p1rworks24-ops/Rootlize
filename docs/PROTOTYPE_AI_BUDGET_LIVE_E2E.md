# Public Prototype AI usage limit — live E2E

目的は、本番の **$1.25 を使い切らず**、test user 1名だけ一時的に低い lifetime hard cap にして、上限到達までの実機フローを確認すること。

この段階では **正式な Public release build は作らない**。Edge Function の再デプロイも不要（hard cap は RPC が見る）。

UI は英語（製品既定）。確認する文言:

```text
AI usage limit reached.

You've reached the AI usage limit for this prototype.
```

## 何を変えてよいか

| 対象 | この E2E で変えるか | 値 |
|---|---|---|
| `plan_defaults` の正式値 | **変えない** | hard cap / onboarding $1.25、monthly $0.25 |
| 他ユーザーの `entitlements` | **変えない** | 公式 $1.25 |
| test user の `entitlements.ai_lifetime_hard_cap_micros` | 一時変更する | まず `50000`（$0.05）。成功確認後に committed 付近へ締める |
| `ai_usage_lifetime.used_micros` | **変えない** | 実リクエストの finalize だけが増やす |
| `ai_usage_lifetime.reserved_micros` | **変えない** | reserve / finalize / release だけが動かす |
| `ai_usage_events` / periods | **消さない** | 読み取りのみ |

金額は整数 USD micros（`$1 = 1_000_000`）。Ask AI `meaning_search` の予約は **10,000**（$0.01）。`facts_generate` は **50,000**（$0.05）。

---

## 1. `004` を live へ適用

前提: live に `001_auth_v1.sql` と `002_ai_budget_v1.sql` が入っていること。`003` は feedback 用で、004 の依存ではない。

### 適用前（読み取り）

Supabase Dashboard → SQL Editor で `supabase/ops/e2e_verify_004_prototype_ai_budget.sql` を実行する。

- `ai_usage_lifetime` が `null`、または `ai_lifetime_hard_cap_micros` 列が無い → **未適用**。次へ進む。
- 列も lifetime テーブルもあり、`free` の hard cap が `1250000` → **適用済み**。004 を再実行しない。temporary cap SQL へ進む。

### 適用

1. live プロジェクトの SQL Editor を開く。
2. `supabase/migrations/004_prototype_ai_budget_v1.sql` を **全文** 貼り付けて Run する。分割しない。
3. 同じ verify SQL を再実行する。期待:
   - `ai_usage_lifetime` が存在する
   - `plan_defaults.free` の hard cap / onboarding が `1250000`、monthly が `250000`
   - `reserve_ai_budget` / `finalize_ai_usage` / `release_ai_reservation` / `get_ai_usage_status` がある

004 が live ですること（再確認）:

- `plan_defaults` / `entitlements` に onboarding と lifetime hard cap 列を足す
- 公式額を入れる。`entitlements` の hard cap は **既存値が null のときだけ** 公式値を埋める
- 全ユーザーの monthly を `plan_defaults` に合わせる（Prototype は $0.25）
- `ai_usage_lifetime` を作り、過去の monthly used を lifetime に載せる（`on conflict do nothing`）
- RPC を hard cap 付きに置き換える

004 は行を DELETE しない。Edge Function は触らない。

適用後に `plan_defaults.free.ai_lifetime_hard_cap_micros` が `1250000` 以外なら、E2E 用 SQL はそこで止まる。

---

## 2. test user 用 temporary cap SQL

ファイル: `supabase/ops/e2e_set_test_user_temporary_hard_cap.sql`

1. `insert into e2e_target` のメールを live の test user 1名に書き換える。
2. 先に `e2e_inspect_test_user_ai_budget.sql`（同じメール）で対象が 1行か見る。
3. set SQL を Run する。

**この SQL が変えるもの:** その user の `entitlements.ai_lifetime_hard_cap_micros` だけを `50000`（$0.05）にする。`updated_at` も更新する。

**変えないもの:** `plan_defaults`、他ユーザー、`used_micros`、`reserved_micros`、events。

ガード: メール未置換 / 0件・複数件 / entitlements 無し / `plan_defaults.free` が公式 $1.25 でない、で中止する。

---

## 3. restore SQL

ファイル: `supabase/ops/e2e_restore_test_user_hard_cap.sql`

E2E が終わったら、同じメールを `insert into e2e_target` に入れて Run する。

**この SQL が変えるもの:** その user の `entitlements.ai_lifetime_hard_cap_micros` を、その plan の `plan_defaults`（公式 `1250000`）へ戻す。

**変えないもの:** used / reserved / events。E2E の実費（通常数セント未満）は残る。消さない。meter はほぼ $1.25 残りになる。

`plan_defaults` の hard cap が `1250000` でなければ中止する。

---

## 4. E2E 手順

使うクライアント: **live Supabase を向いている、この usage UI が入った既存 EXE / ソース起動**。`tools/build_official_prototype.py` は走らせない。`artifacts\` の古い EXE は使わない。

フォルダ: **facts 済みの少数枚**（3〜5）。未解析フォルダだと先に `facts_generate`（予約 $0.05）が走り、最初の成功確認が崩れる。

言語: English。

### A. 004 適用 → temporary cap

1. 上の verify / 004 / set SQL。
2. inspect で test user hard cap が `50000`、他ユーザーが公式 `1250000`、`plan_defaults` が `1250000`。

### B. Account — Plan と meter

1. その test user でサインインする。
2. Account を開く（開くたびに cloud から usage を取り直す）。
3. `Plan: Prototype` がある。
4. `AI usage` の meter、`N% used`、`N% remaining` がある。金額（`$`）は出ない。

### C. 成功した AI request のあと usage が増える

1. Ask AI で短い meaning query を 1 回送る。
2. 結果が返る。
3. Account を開き直す。
4. used % が増える、remaining % が減る。

UI が `0%` のままでも、inspect の `used_micros` が 0 より大きければ成功（表示は整数 % に切り捨て）。その場合も次へ進む。

**ここで $0.05 を使い切ろうとしない。** 実費は予約より小さいので、Ask AI を繰り返しても $1.25 はもちろん、$0.05 にもすぐ届かない。

### D. remaining < 次の予約 → Provider の前に reject

1. `e2e_stage_test_user_for_limit.sql` の `insert` メールを同じ user にする。
2. `stage_mode` は `limit_reached` のまま（推奨）。
3. Run する。**変えるのは hard cap だけ。** `hard_cap = used + reserved`。used / reserved は触らない。
4. inspect で `remaining_micros = 0`、`limit_reached = true`。
5. アプリを Account に戻すか、一度終了して同じ user で入れ直す（古い remaining キャッシュを捨てる）。
6. Ask AI をもう 1 回送る。

期待: Provider は呼ばれない。Ask AI は generic error ではなく次の 2 行。

```text
AI usage limit reached.
You've reached the AI usage limit for this prototype.
```

任意の `below_estimate`: remaining を `5000` にして proxy の reserve 失敗だけを見る。Account の limit reached 文言は、その後 `limit_reached` でもう一度 stage するまで出ないことがある。

### E. Account でも limit reached

Account を開き直す。hint が同じ 2 行。meter は used 100% / remaining 0%。`$` も reset 日も出ない。

### F. ローカル機能は生きている

Ask AI 以外を触る。

- Basic Search（ファイル名 / OCR テキスト / タグ）
- Browse（グリッド・プレビュー）
- OCR index（ローカル）
- non-AI Actions（手でタグ・favorite・移動・リネーム）

これらは budget RPC を通らない。止まったらこの E2E の範囲外。

### G. 再起動後も usage が戻る

1. アプリを完全終了する。
2. 同じ live クライアントを起動し、同じ test user のままにする。
3. Account を開く。limit reached のまま。
4. Ask AI をもう 1 回送り、同じ 2 行が出る。
5. Basic Search / Browse は使える。

### H. restore

1. restore SQL を Run する。
2. inspect で test user hard cap が `1250000`、`users_not_on_official_hard_cap = 0`、`plan_defaults` が公式値。
3. アプリを開き直す。Account は limit reached ではない。used は E2E 実費だけ（ほぼ 0%）。

---

## 5. 期待結果

| 確認 | 期待 |
|---|---|
| 004 後の `plan_defaults` | hard cap / onboarding `1250000`、monthly `250000` |
| temporary cap 後 | test user hard cap `50000`。他ユーザーと `plan_defaults` は `1250000`。used / reserved 不変 |
| Account Plan | `Plan: Prototype` |
| Account meter | バーと used / remaining %。`$` なし |
| 最初の Ask AI | 成功。inspect の `used_micros` が増える。remaining が減る |
| stage 後 | hard cap だけが committed（または committed+5000）になる。used / reserved 不変 |
| 次の Ask AI | Provider 前に reject。上記 2 行。generic error ではない |
| Account limit | 同じ 2 行。100% used / 0% remaining |
| ローカル | Search / Browse / OCR / 手作業 Actions が動く |
| 再起動 | 同じ limit 状態が cloud から戻る |
| restore 後 | その user だけ hard cap `1250000`。events は残る。公式 $1.25 に近い残り |

---

## 予約額（参照）

| operation | 予約 micros | 金額 |
|---|---|---|
| `meaning_search`（Ask AI） | 10000 | $0.01 |
| `act_plan` | 10000 | $0.01 |
| `facts_generate` | 50000 | $0.05 |

reject 条件（RPC）: `estimated > remaining`。`remaining = hard_cap - used - reserved`。クライアントの preflight は `limit_reached`（committed >= hard cap）のとき同じ文言で止める。どちらも Provider の前。

---

## 使うファイル

| ファイル | 書き込み |
|---|---|
| `supabase/migrations/004_prototype_ai_budget_v1.sql` | live 未適用なら 1 回 |
| `supabase/ops/e2e_verify_004_prototype_ai_budget.sql` | なし |
| `supabase/ops/e2e_inspect_test_user_ai_budget.sql` | なし |
| `supabase/ops/e2e_set_test_user_temporary_hard_cap.sql` | test user の hard cap だけ `$0.05` |
| `supabase/ops/e2e_stage_test_user_for_limit.sql` | 同じ user の hard cap だけ committed 付近へ |
| `supabase/ops/e2e_restore_test_user_hard_cap.sql` | 同じ user の hard cap だけ `$1.25` へ戻す |
