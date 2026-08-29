# Vision relevance 実API・実機検証手順

製品仕様は `.ai/SPEC.md`。評価契約は D-011 / `tools/meaning_eval`。このファイルは手順だけを正とする。

現行 UI は Search ホーム。フォルダ選択でローカル解析が自動開始する。通常 UI に Analyze はない。既定検索は Meaning（Vision relevance）。

## 1. API keyを設定する

API keyをPowerShellの履歴や画面へ表示しないため、非表示入力を使う。

### 開いているPowerShellだけで一時的に使う

```powershell
$capixeSecureKey = Read-Host 'OpenAI API key' -AsSecureString
$env:OPENAI_API_KEY = [Net.NetworkCredential]::new('', $capixeSecureKey).Password
if ([string]::IsNullOrEmpty($env:OPENAI_API_KEY)) { 'missing' } else { 'present' }
```

このPowerShellからCapixeまたはbenchmarkを起動する。このウィンドウを閉じると設定は消える。

### Windowsユーザー環境変数として保存する

```powershell
$capixeSecureKey = Read-Host 'OpenAI API key' -AsSecureString
$capixePlainKey = [Net.NetworkCredential]::new('', $capixeSecureKey).Password
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $capixePlainKey, 'User')
$capixePlainKey = $null
if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'User'))) { 'missing' } else { 'present' }
```

設定後は、起動済みのPowerShellとCapixeをすべて閉じてから新しく起動する。

### Capixeが認識できるか確認する

Capixeを起動するのと同じPowerShellで次を実行する。key文字列は表示されない。

```powershell
if ([string]::IsNullOrEmpty($env:OPENAI_API_KEY)) { 'Capixe: missing' } else { 'Capixe: present' }
```

## 2. 99画像のbenchmarkを実行する

リポジトリルートで実行する。既定で指定9 query、実在する初見5 query、不存在3 queryをbatch 5/10/20・並列2で評価する。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\vision_relevance_benchmark.py' --folder 'D:\07_Programs\shotlogue_test' --output '.\artifacts\vision-relevance-real-api.json'
```

正解ラベルはAPI promptには渡らず、応答後のmetrics計算だけに使われる。出力にはTP/FP/FN、Precision/Recall/F1、OpenCLIP完了、縮小、Vision開始、最初の判定、全判定、UI最終反映、request/retry、実usage token、1/100/1000検索のcostが入る。

## 2b. Phase B A/B（object-presence vs usefulness）

同じ固定候補画像集合で旧object-presence judgeと新usefulness judgeを比較する。dev / hold-outの分割は評価ツール側だけに置き、製品ロジックへは入れない。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\vision_judge_ab_eval.py' --folder 'D:\07_Programs\shotlogue_test' --split both --output '.\artifacts\vision-judge-ab.json'
```

## 2c. Phase D 評価基盤（正式運用）

固定テストライブラリに対して、正式 Retriever（OpenCLIP + raw `{q}`）と Vision Judge → ranking までを定量評価する。dev / hold-out は評価ツール側だけに置き、製品ロジックへは入れない。hold-out は prompt や設定調整に使わない。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\meaning_eval\evaluate.py' --folder 'D:\07_Programs\shotlogue_test'
```

Retriever のみなら `--retriever-only`。出力は `artifacts\meaning-eval\runs\<timestamp>\results.json` と `summary.md`、および `artifacts\meaning-eval\latest\`。正解ラベルは API prompt に渡らない。

## 3. packaged Capixeを実機確認する

D-018 製品 Meaning Search（Ask AI / DB facts）の packaged EXE 確認は `docs/D018_PACKAGED_EXE_MEANING_SEARCH_RUNBOOK.md` を使う。この節の旧手順（通常 Search が Meaning、`shotlogue_test`、Analyze）は現行製品の確認手順ではない。

## 2d. Semantic Index Hybrid（現行 Judge vs Index-only vs Hybrid）

評価スクリプトは製品コードを書き換えない。同一 Ground Truth・同一 query で A（現行 Vision Judge）、B（Semantic Index のみ）、C（Index で確定し不確実分だけ Judge）を比較する。Hybrid の閾値は dev だけで選び、hold-out は凍結評価にだけ使う。C の Vision 判定は保存済み製品 Judge を replay する（追加の query ごと画像送信はしない）。製品 Meaning Search は同じ凍結 Hybrid を Vision ゲートとして使う（D-016）。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\meaning_eval\evaluate_index_hybrid.py' --folder 'D:\07_Programs\shotlogue_test'
```

出力は `artifacts\meaning-eval\runs\semantic-index-hybrid\`（`results.json` / `hybrid-analysis.md` / `summary.md`）。`artifacts\meaning-eval\latest` は上書きしない。Index 生成コストと query ごとの Judge コストは分計する。

## 2e. Phase E 全量 A/B（凍結 Hybrid vs 現行 Judge）

評価スクリプトは製品コードを書き換えない。前回 dev で選んだ precision_first 帯域 `posL1.01_posC0.45_negL0.33_negC0.32` を凍結し、全 Ground Truth で A（現行 Vision Judge）と C（Hybrid）を比較する。hold-out で閾値を変えない。既定では API key があるときだけ、最大 12 画像のライブ Judge を replay と比較する。製品接続後もこの凍結条件は変えない。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\meaning_eval\evaluate_hybrid_phase_e.py' --folder 'D:\07_Programs\shotlogue_test'
```

ライブを明示的に止める場合は `--live-sample never`。出力は `artifacts\meaning-eval\runs\semantic-index-hybrid-phase-e\`。`artifacts\meaning-eval\latest` と Hybrid 選定 run は上書きしない。

## 2f. Semantic Index v3 only（B-v3、検索時 Vision なし）

評価スクリプトは製品コードを書き換えない。同一 Ground Truth / query set / dev / hold-out で、保存済み `semantic-index-v3` と既存 local matcher（`hybrid_v1` include_hit）だけを使う。検索時に画像を Vision Judge へ送らない。A と C-v3 は前回 Phase E v3 結果を再利用し、B-old は v1 Index-only 結果を再利用する。hold-out で閾値を選ばない。既存 SEARCH_CONFIGS の Recall / Balanced / Precision 比較は dev だけ。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\meaning_eval\evaluate_index_only_v3.py' --folder 'D:\07_Programs\shotlogue_test'
```

出力は `artifacts\meaning-eval\runs\semantic-index-v3-only\`。`artifacts\meaning-eval\latest` と Hybrid 選定 / Phase E run は上書きしない。Index が cache されていれば追加の Vision API は呼ばない。

## 2g. Semantic Index free-form only（B-freeform、検索時 Vision なし）

評価スクリプトは製品コードを書き換えない。同一 Ground Truth / query set / dev / hold-out で、自然言語 search document（`semantic-index-freeform-v1`）だけを DB-only 検索する。検索時に画像を Vision Judge へ送らない。A / B-v3 / B-v4 / C は前回結果を再利用する。hold-out で閾値は選ばない。製品 Ask AI / Hybrid / v4 Index は変えない。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\meaning_eval\evaluate_index_only_freeform.py' --folder 'D:\07_Programs\shotlogue_test'
```

出力は `artifacts\meaning-eval\runs\semantic-index-freeform-only\`。`artifacts\meaning-eval\latest` と v3 / v4 / Hybrid run は上書きしない。Index が cache されていれば追加の Vision API は呼ばない。

## 2h. Semantic Index free-form matching FP 抑制（評価専用、検索時 Vision なし）

評価スクリプトは製品コードを書き換えない。同一 Ground Truth / query set / dev / hold-out で、既存 free-form search document に opening / generic-density / multi-evidence gate を載せる。hold-out で閾値は選ばない。製品 Ask AI / Hybrid / v4 Index / UI / DB schema は変えない。

```powershell
& '.\.build-venv\Scripts\python.exe' '.\tools\meaning_eval\evaluate_freeform_fp_gate.py' --folder 'D:\07_Programs\shotlogue_test'
```

出力は `artifacts\meaning-eval\runs\semantic-index-freeform-fp-gate\`。`artifacts\meaning-eval\latest` と v4 / Hybrid / 前回 freeform run は上書きしない。Index が cache されていれば追加の Vision API は呼ばない。


