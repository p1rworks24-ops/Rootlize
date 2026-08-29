# Capixe SigLIP 2 ONNX Runtime Benchmark Report

## Executive Summary

**推薦: A — ONNX Runtime FP32を採用候補とする。INT8は不採用。** FP32はPyTorchと全Top-K指標が一致し、Image/Text embedding cosine平均はともに1.000。4-thread balancedは画像138.6 ms、Query 48.5 msで、PyTorchの140.4 / 42.4 msと同等だった。dynamic per-channel INT8は365.2 MBまで縮小したが、画像cosine 0.746、Top-1順位一致21.4%、Screenshot Top-3 -4.2ptのため精度優先条件を満たさない。

## Compared Runtimes

| Runtime | 設定 | 判定 |
|---|---|---|
| PyTorch 2.13 CPU | baseline, batch 4 | 基準 |
| ONNX Runtime 1.28 FP32 | CPUExecutionProvider, default threads | 精度一致、CPU専有に注意 |
| ONNX Runtime 1.28 FP32 balanced | 4 intra-op / 1 inter-op / sequential | **推薦** |
| ONNX Runtime 1.28 INT8 | dynamic, signed weights, per-channel, 4 threads | 不採用 |

Static INT8はImage Encoder用calibration設計が別途必要であり、dynamic INT8の大幅な画像embedding劣化を踏まえて今回は方式を増やさなかった。FP16はWindows CPU採用候補から除外した。

## Export

- PyTorch標準 `torch.onnx.export`（legacy TorchScript exporter）、opset 17
- Image: `pixel_values` → `embedding`、`[batch, 3, 224, 224]` → `[batch, 768]`
- Text: `input_ids` → `embedding`、`[batch, 64]` → `[batch, 768]`
- dynamic axis: batchのみ。Textはmax length 64へpadding/truncationする
- 両出力はモデル内でL2 normalize済み
- warning: legacy exporterのdeprecation、およびTextの系列長判定がtrace時定数になる警告。長さ64固定なので本構成では許容
- `onnx.checker` と実推論で両Encoderを検証済み。unsupported opなし

## Accuracy

| Runtime | JA T1 | JA T3 | JA T5 | JA T10 | EN T1 | EN T3 | EN T5 | EN T10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PyTorch | 42.9% | 53.6% | 75.0% | 82.1% | 67.9% | 71.4% | 92.9% | 96.4% |
| ONNX FP32 | 42.9% | 53.6% | 75.0% | 82.1% | 67.9% | 71.4% | 92.9% | 96.4% |
| ONNX INT8 | 35.7% | 57.1% | 67.9% | 75.0% | 53.6% | 67.9% | 78.6% | 82.1% |

INT8のJA Top-3だけは+3.6ptだが、JA Top-1 -7.2pt、JA Top-5/10 -7.1pt、EN Top-1 -14.3ptであり改善とは判断しない。

## No-text / Screenshot

| Runtime | No-text photo T3 | Screenshot T3 | L1 | L2 | L3 | L4 | L5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| PyTorch | 50.0% | 83.3% | 41.7% | 58.3% | 37.5% | 88.9% | 66.7% |
| ONNX FP32 | 50.0% | 83.3% | 41.7% | 58.3% | 37.5% | 88.9% | 66.7% |
| ONNX INT8 | 50.0% | 79.2% | 50.0% | 58.3% | 37.5% | 77.8% | 83.3% |

FP32はcode editor、terminal、error、settings、browser、comparison、login、dashboardを含む全Screenshot評価で集計値を維持した。

## Embedding Compatibility

| Runtime | Image cosine mean | Image L2 mean | Text cosine mean | Text L2 mean | Top-1 rank agreement |
|---|---:|---:|---:|---:|---:|
| ONNX FP32 | 1.000000 | 0.0000024 | 1.000000 | 0.0000005 | 98.2% |
| ONNX INT8 | 0.745704 | 0.706055 | 0.965165 | 0.257844 | 21.4% |

FP32の不一致は56 Query中1件の同点近傍（comparison page）だけで、全Top-K精度およびCase A/B/C/Dの集計は一致した。既存PyTorch embeddingを保持したruntime切替はFP32なら可能と判断する。

## Performance

同一Windows x64実機（Intel Family 6 Model 158、8 logical threads）、batch 4、warm全件平均。

| Runtime | Load | Image / item | Images/s | Query / item |
|---|---:|---:|---:|---:|
| PyTorch | 0.82s | 140.4ms | 7.12 | 42.4ms |
| ONNX FP32 default | 2.05s | 169.4ms | 5.90 | 39.4ms |
| ONNX FP32 balanced | 2.13s | 138.6ms | 7.21 | 48.5ms |
| ONNX INT8 balanced | 3.01s | 128.8ms | 7.76 | 24.9ms |

Coldはsession/model load、warmは全件平均として分離した。1/10/100枚とbatch 1/4/8の独立反復値は今回の自動実測に含められず、採用前の追加測定事項とする。最大速度よりUI共存を優先し、4 thread balancedを候補とする。

## RAM

| Runtime | Peak process RSS |
|---|---:|
| PyTorch | 1,124 MB |
| ONNX FP32 | 2,683 MB |
| ONNX INT8 | 1,618 MB |

注意: ONNX値は同一プロセスにPyTorch modelを保持した互換性測定のprocess peakで、ONNX単独常駐量ではない。したがって差分を配布時RAMと断定できない。独立worker/プロセス測定が次の必須確認。

## Deployment Size

| Runtime | Model | Runtime/主要Python依存 | 概算展開サイズ |
|---|---:|---:|---:|
| PyTorch | 1,468 MB | torch 490 MB + transformers 102 MBほか | 2.1 GB超 |
| ONNX FP32 | 1,431.6 MB | ORT 42.5 MB + NumPy/Pillow/tokenizer等 約155 MB | 約1.63 GB |
| ONNX INT8 | 365.2 MB | 同上 約155 MB | 約520 MB |

FP32内訳はImage 354.5 MB、Text 1,077.1 MB。tokenizer filesは約37 MB。ZIP増加は圧縮率と最終パッケージ方式未確定のため推測値を出さない。

## Offline

`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`local_files_only=True`でmodel load、Image/Text embeddingを実測済み。モデル、config、preprocessor、tokenizer filesを同梱すればネットワーク不要。

## PyTorch Removal

推論graph自体はONNX Runtimeのみで動作し、配布版からPyTorchを排除可能。ただし現在のbenchmark runnerは前処理にTransformers `AutoProcessor`を使用する。製品化時は保存済み設定に従うPillow/NumPy画像前処理と、`tokenizer.json`を読む軽量`tokenizers`へ置換・一致テストし、Transformersも除外する。今回そのtorch-free配布環境の独立実測までは未完了。

## Windows / ONNX Runtime Sharing

- 実測: Windows 11 x64、CPUExecutionProvider、ONNX Runtime 1.28.0
- Windows 10は未実機確認。公式にはWindows 10/11とCPU EPが対象で、Windows buildはVisual C++ 2019 runtime（最新版推奨）が必要
- Python wheelの主要DLLは `onnxruntime.dll`、`onnxruntime_providers_shared.dll`、Python binding
- OCR PoCはONNX Runtime 1.27.0をexact pin、Semantic benchmarkは1.28.0。単一processで二版共存は避ける。SigLIP graphは標準opset 17のみなので、OCR側を1.28へ上げる回帰試験後に同一runtime共有できる可能性が高い。現時点ではversion一致を未検証

参考: [ONNX Runtime installation requirements](https://onnxruntime.ai/docs/install/)、[Windows support](https://onnxruntime.ai/docs/get-started/with-windows.html)、[quantization guidance](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)。

## Failure Cases

PyTorch Top-3成功→INT8失敗: `車`、`an outdoor photo`、`a screen showing source code`、`設定画面`、`an online product page`。FP32では該当なし。INT8の画像側崩れが主因で、日本語・Screenshot用途に採用できない。

## Worker Design

モデル常駐の独立workerを推奨する。本体processへ1.4 GB級FP32 modelを持たせず、4-thread balanced、batch 4を初期候補にする。キャンセル・進捗・CPU制御は既存OCR worker設計を再利用できるが、本体統合は今回行っていない。

## Recommendation

**A: ONNX FP32を採用候補。** 精度、日本語、Screenshot、cross-runtime互換性を完全に維持したことを最優先した。速度はPyTorch同等で、PyTorch排除余地がある。弱点は1.43 GBのmodel size、単独worker RAM未測定、軽量前処理構成未検証。INT8はサイズ利点が大きいが精度劣化が採用基準を超える。

## Reproduction

```powershell
cd tools\semantic_search_benchmark
.\.venv\Scripts\python.exe .\onnx\benchmark_onnx.py
```

生結果はGit対象外の `results/siglip2_onnx_benchmark.json` に保存される。
