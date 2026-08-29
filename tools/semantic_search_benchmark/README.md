# Capixe Semantic Image Search Benchmark

**Historical model-comparison harness. Not the product search spec.** Current retrieval is OpenCLIP ViT-B/32; see `.ai/SPEC.md`. Live quality evaluation is `tools/meaning_eval`.

Capixe本体から独立した、多言語画像検索モデルのCPU比較環境です。本体の検索、DB、UI、依存関係は変更しません。

## What it does

1. Wikimedia Commons APIから、明示的なファイル別license・creator・説明metadataを持つCapixe向け写真subsetを自動構築します。
2. code editor、terminal、error、settings、product、comparison、login、dashboard、documentationの疑似UIをmetadata付きで生成します。
3. annotation/metadataから日本語・英語Queryと複数正解のground truthを構築します。
4. SigLIP 2、jina-clip-v2、MetaCLIP 2をCPUで実測し、Top-K、MRR、速度、RAM、保存容量を集計します。
5. `semantic_search_benchmark_report.md` を生成します。

## Setup and run

PowerShellから次の1コマンドを実行します。初回だけ専用 `.venv`、dataset、modelを取得します。

```powershell
cd tools\semantic_search_benchmark
.\run_benchmark.ps1
```

Datasetだけ準備する場合:

```powershell
.\run_benchmark.ps1 --dataset-only
```

モデルを限定する場合:

```powershell
.\run_benchmark.ps1 --models google/siglip2-base-patch16-224
```

SigLIP 2のONNX Runtime / INT8比較は [onnx/README.md](onnx/README.md) を参照してください。結果は `siglip2_onnx_benchmark_report.md` に記録します。

## Cache

`cache/`, `data/downloads/`, `data/images/`, `artifacts/` は再利用され、Git対象外です。途中のdownloadは `.part` として保存し、完了後にだけ正式名へ置換します。

## Dataset and license notes

- Wikimedia Commons: 各ファイルのsource page、creator、license、license URLをmanifestへ保存します。licenseが不明なファイルは「不明」のまま記録し、許可とは扱いません。本リポジトリでは画像を再配布しません。
- Capixe synthetic UI: このコードが独自生成し、既存サービスを複製しません。
- Google Images等からの無差別取得は行いません。

## Model license notes

- `google/siglip2-base-patch16-224`: Apache-2.0。
- `jinaai/jina-clip-v2`: download weightはCC BY-NC 4.0。商用利用にはJina提供経路または別契約が必要です。
- `facebook/metaclip-2-worldwide-b32`: CC BY-NC 4.0。商用Capixeへの同梱候補にはできません。

ライセンス情報はbenchmark実行時点で公式model cardを再確認してください。不明事項を自動的に「許可」とは扱いません。
