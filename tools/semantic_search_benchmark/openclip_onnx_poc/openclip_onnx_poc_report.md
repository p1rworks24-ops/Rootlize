# OpenCLIP ViT-B/32 LAION-2B FP32 ONNX PoC

## 結論

正式移行の次段階（製品外でのintegration prototype）を推奨する。FP32 ONNXはCPUExecutionProviderで正常動作し、98実画像・24英語queryでPyTorch参照実装と同じ集計精度を再現した。製品コード、DB schema、既存embedding、SigLIP 2 bundleは変更していない。

## 固定したモデルとexport

- checkpoint: `laion/CLIP-ViT-B-32-laion2B-s34B-b79K`
- local snapshot: `1a25a446712ba5ee05982a381eed697ef9b435cf`
- OpenCLIP 3.3.0 / PyTorch 2.13.0 CPU
- legacy `torch.onnx.export`、opset 18、dynamic batch、constant folding、FP32
- image/text towerを分離し、L2正規化前のprojected embeddingを出力
- image: `pixel_values float32[B,3,224,224] -> embedding float32[B,512]`
- text: `input_ids int64[B,77] -> embedding float32[B,512]`

## preprocessing / tokenizer / similarity

- RGB、shortest-side bicubic resize、224x224 center crop
- mean `[0.48145466, 0.4578275, 0.40821073]`
- std `[0.26862954, 0.26130258, 0.27577711]`
- OpenAI SimpleTokenizer byte-level BPE、49,408語彙、77 token、EOT token位置をpooling
- image/textをそれぞれFP32 L2 normalization後、内積（normalized cosine similarity）を降順rank

## PyTorch vs ONNX

| 項目 | 結果 |
|---|---:|
| image embedding cosine min / mean | 0.99999988 / 1.00000000 |
| text embedding cosine min / mean | 0.99999988 / 1.00000000 |
| raw cosine score 最大絶対差 | 0.000001222 |
| Top-10完全一致query | 21 / 24 |
| 全98件内の最大順位移動 | 1 |
| graph optimization有/無 image最大差 | 0.000002295 |
| graph optimization有/無 text最大差 | 0.000000328 |

集計値は両実装で完全一致した。

| 実装 | Top-1 | Top-3 | Top-5 | Top-10 | MRR |
|---|---:|---:|---:|---:|---:|
| PyTorch | 50.0% | 66.7% | 70.8% | 79.2% | 0.602283 |
| ONNX Runtime | 50.0% | 66.7% | 70.8% | 79.2% | 0.602283 |

## 重要queryのONNX順位

- Windows desktop: `ScreenShot_Atest_001.png` 1、`20260718_202718.png` 2、`20260718_203016.png` 3、`20260718_202724.png` 4
- Windows desktop screenshot: 同じ4画像が1/2/3/4
- dog: `images.jpg` 1、`A2.png` 2
- a dog: `A2.png` 1、`images.jpg` 2
- dog photo: `images.jpg` 1、`A2.png` 2
- image search application: 最良正解 1（次点2）
- code editor: 最良正解 3
- browser window: 正解 13
- settings screen: 最良正解 21

最後の2 queryの弱さはPyTorch参照実装にも同じであり、ONNX変換劣化ではない。全24 queryの画像別順位は `comparison_results.json` に収録した。

## CPU性能

Windows CPU、ONNX Runtime 1.28.0、CPUExecutionProvider、batch 4、graph optimization all。前処理済みtensorからencoder推論までをクリーンなONNX専用processで測定した。

- model load: 1.494秒（image + text）
- image: 133.46 ms/枚、98枚合計13.079秒
- text: 41.94 ms/query、24 query合計1.007秒
- Peak RAM: 723.36 MB

PyTorchの同一比較runはload 3.07秒、image 38.62 ms/枚、text 49.70 ms/queryだった。ONNXは配布可能だが、現計測ではimage towerがPyTorchより遅い。threading/batch/session設定の調整余地は正式integration前に検証すべきである。

## bundle / 配布

| ファイル | サイズ |
|---|---:|
| image_encoder.onnx | 351,780,008 bytes (335.48 MiB) |
| text_encoder.onnx | 254,341,724 bytes (242.56 MiB) |
| BPE + config + manifest + license | 1,359,200 bytes (1.30 MiB) |
| 合計 | 607,480,932 bytes (579.34 MiB) |
| ZIP | 563,081,873 bytes (537.95 MiB) |

必要runtimeはONNX Runtime CPU（Python wheel内native payload実測約42.7 MiB。製品配布ではPython不要）、画像の同一preprocessing実装、同梱BPE tokenizerである。

モデルrepositoryはMIT表示。OpenCLIP codeもMITで、配布時はモデル/sourceとOpenCLIPのMIT license noticeをbundle attributionへ同梱する方針が安全である。学習データ由来の出力品質・利用リスクは別途製品レビュー対象とする。

## 現行SigLIP 2との比較と判断

前回の同じ実画像benchmarkではSigLIP 2がTop-1 41.7%、Top-3 66.7%、Top-5 70.8%、Top-10 83.3%、MRR 0.562、OpenCLIPが50.0%、66.7%、70.8%、79.2%、0.602だった。OpenCLIPは今回の中心課題であるdesktopと英語queryのTop-1/MRRを改善し、ONNX変換でも品質を失っていない。bundleは約579 MiBで現行SigLIP 2の実測約1,468 MiBより小さい。

従って正式移行の価値はある。ただしこのPoCだけで正式決定はせず、次段階でCapixeと同じC#/ORT preprocessing・tokenizer実装、worker lifecycle、RAM、image throughputを製品外feature flagで検証してからschema/version migrationを設計する。
