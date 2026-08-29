# Capixe SigLIP 2 Runtime Final Validation

## Executive Summary

**本体アーキテクチャ設計へ進めてよい。第一推薦は ONNX Runtime 1.28.0 / Semantic 専用常駐 worker / 4 intra-op・1 inter-op / batch 1 / torch・transformers なし / model optional download。** 軽量 runtime は前回 FP32 と検索精度が完全一致し、独立 worker の実測 peak は 1,608.30 MiB だった。Capixe 本体、DB、UI、release dependency は変更していない。

## Worker RAM

Windows 11 x64、8 logical thread、CPUExecutionProvider。PyTorch/Transformersを同居させない独立 process の値。

| Phase | batch 1 / 4 threads | batch 4 / 4 threads | batch 8 / 4 threads |
|---|---:|---:|---:|
| 起動直後 | 33.18 MiB | 33.62 MiB | 33.64 MiB |
| 両model load後 | 1,565.79 MiB | 1,566.02 MiB | 1,565.72 MiB |
| Image peak | 1,608.30 MiB | 1,666.35 MiB | 1,753.35 MiB |
| Text peak | 1,605.46 MiB | 1,686.16 MiB | 1,790.16 MiB |
| idle（推論後） | 1,605.44 MiB | 1,686.14 MiB | 1,790.14 MiB |
| process peak | **1,608.30 MiB** | 1,686.16 MiB | 1,790.16 MiB |

正式な製品判断値は推薦 batch 1 の 1,608.30 MiB。前回 2,683 MiB は PyTorch 同居値であり置き換える。

## Batch

同じ 131 枚、warm-upを別途挟まない実運用寄りの全件値。

| batch | Images/s | ms/image | Image peak | 平均CPU（全8 logical thread比） | total |
|---:|---:|---:|---:|---:|---:|
| **1** | **8.314** | **120.276** | **1,608.30 MiB** | 約48% | 15.636s |
| 4 | 6.485 | 154.205 | 1,666.35 MiB | 約45% | 20.047s |
| 8 | 6.490 | 154.094 | 1,753.35 MiB | 約45% | 20.032s |

このCPUでは batch 1 が速度・RAMとも最良。batch output は 1/4/8 で `atol=2e-6` 一致。

## Balanced Settings

**batch 1、intra-op 4、inter-op 1、ORT_SEQUENTIAL** を推薦する。4 thread は image 120.3 ms/item、全8 thread比較は batch 4で185.0 ms/itemかつCPU約72%となり、全コア設定は遅くUI余力も小さかった。

## Torch-free

可。独立 worker で画像前処理、Image/Text ONNX inference、L2-normalized embedding、similarityを実行した。runtime module は `torch` を importしない。

## Transformers-free

可。配布 runtime は `onnxruntime 1.28.0 + numpy + Pillow + tokenizers` とする。Transformersは検証時の公式出力比較にのみ使用し、製品 runtime には不要。

## Tokenizer

`tokenizers.Tokenizer` で `tokenizer.json` を直接読む。必要ファイルは `tokenizer.json`、`tokenizer_config.json`、`special_tokens_map.json`。pad `<pad>` / id 0、EOSはtokenizer graphのpost-processor、right padding、truncation、固定max length 64。日英56 Queryのtoken IDは公式processorと全件完全一致した。`tokenizer.model` はこの方式では不要。

## Preprocessing

Pillow/NumPyでRGB変換、224×224へBICUBIC resize、1/255 rescale、mean/std各0.5、CHW float32化を行う。SigLIP設定にはcrop指定がなく、非正方形も直接resizeする。公式processorとの差は max `1.1921e-7`、mean `3.1591e-8`。

## Accuracy

前回と同じ131枚（Wikimedia Commons + synthetic UI）、日英56 Queryを再利用。

| 指標 | 軽量runtime | 前回FP32 | 差 |
|---|---:|---:|---:|
| Japanese Top-3 | 53.6% | 53.6% | 0.0pt |
| English Top-3 | 71.4% | 71.4% | 0.0pt |
| Screenshot Top-3 | 83.3% | 83.3% | 0.0pt |
| No-text Top-3 | 50.0% | 50.0% | 0.0pt |

## Offline

`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`HF_DATASETS_OFFLINE=1` とnetwork bypassなしの独立 workerでmodel loadと両embeddingが完了した。runtime codeにdownload処理はなく、ローカルmodel/config/tokenizerだけを参照する。

## OCR 1.28 Regression

Python 3.12の隔離環境でRapidOCR 3.9.1を固定し、ORTだけ1.27.0→1.28.0へ変更。既存 worker・DB・diff indexing・検索・PoCテストは **151 passed / 2 skipped**。

| fixture | 内容 | text | confidence | blocks | 1.27 → 1.28 runtime |
|---|---|---|---|---:|---:|
| development-mixed.png | 日本語UI + English + code + terminal | 完全一致 | 0.936534、差0 | 133 | 4.894s → 4.006s |
| capixe-home.png | English UI | 完全一致 | 0.981115、差0 | 37 | 1.411s → 1.111s |
| synthetic_code_editor_000.png | code/editor | 完全一致 | 0.997729、差0 | 9 | 0.757s → 0.689s |

errorは全件なし。単発計測のため速度差は採用根拠にせず、出力・confidence・互換性の一致を採用根拠とする。

## Runtime Sharing

**ORT 1.28.0のversion共有は可能。** RapidOCRの3 graphとSigLIP opset 17はCPUExecutionProviderで動作し、package/DLL/provider/model conflictは発生しなかった。ただしmodelを同一processへ同居させる意味ではなく、同じ配布versionを別workerから利用する。

## Worker Architecture Recommendation

**OCR workerとSemantic workerは別process。** dependency versionは共有するが、lifetime・crash isolation・CPU schedulingを分ける。OCR既存設計を変更せず、Semantic側だけ4-thread制限する。同一workerは1.6 GiB級Semantic modelの常駐がOCRの起動・回復・保守へ波及するため不採用。

Semantic workerは常駐を推薦する。model loadは3.63s、idle約1.61 GiB。Analyzeごとのload/unloadは毎回3.6sの待ちを生み、検索QueryにもText Encoderが必要なためUXが悪い。将来のメモリ節約策としてImage EncoderをAnalyze worker、Text EncoderをSearch serviceへ分離可能だが、初期実装ではprocess管理の複雑化を避け両sessionをSemantic workerに保持する。

## Deployment Size

| Component | Size |
|---|---:|
| Image Encoder ONNX | 354.54 MiB |
| Text Encoder ONNX | 1,077.09 MiB |
| tokenizer/config | 32.82 MiB |
| ORT + NumPy + Pillow + tokenizers package files・required DLL | 116.38 MiB |
| **合計展開** | **1,580.83 MiB** |
| **ZIP（Deflate level 6、実測）** | **1,383.93 MiB** |

共通のORT/NumPy等が既存OCR配布に既に含まれる場合、純増は最大値より小さくなる。必要VC++ runtimeは既存配布前提で、この集計には含めていない。

## Model Distribution

**App ZIPへ同梱せず、Semantic modelをoptional download。** GitHub Releaseの通常asset上限や更新差分、初回不要ユーザーへの約1.384 GiB downloadを考えると同梱は不適切。初回Semantic Search有効化時にversion付きmodel bundleを取得し、hash検証後にoffline利用可能にする。画像やembeddingを送信する必要はなく、生成・検索はローカルで完結する。完全offline導入向けには同じbundleの手動配置経路を用意する。

## Risks

- 常駐RAM約1.61 GiBは低メモリ端末で重い。起動時にはloadせず、Semantic Searchを有効化したsessionだけ常駐させる。
- Windows 10実機と異なるCPU世代は未測定。統合前にsupported最低環境で再測定する。
- optional downloadの署名/hash、resume、version migration、破損復旧は次の設計事項。
- 現在のText Encoderは1,077 MiBで大半を占める。将来のmodel更新は同じ精度基準で再検証が必要。
- model分割process案は初期実装では採らないが、RAM圧力が実機UXを損なう場合の次候補。

## Final Decision

**本体アーキテクチャ設計へ進んでよい。** 第一推薦を以下で固定する。

- Runtime: ONNX Runtime 1.28.0 CPUExecutionProvider
- Semantic worker: OCRとは別の常駐process、Image/Text両session保持
- Batch: 1
- Threads: intra-op 4 / inter-op 1 / sequential
- torch: なし
- transformers: なし（`tokenizers`直接利用）
- Model配布: version付きoptional download、hash検証、以後offline
- OCR runtime: 1.28.0へ統一可能。ただし本体dependency更新は次タスク

次はSemantic workerのIPC・lifecycle・cancel/progress・model bundle manifestを設計する。本レポート段階ではSemantic Search本体、DB schema、Images UI、Search、embedding保存、AI Action、releaseを変更していない。
