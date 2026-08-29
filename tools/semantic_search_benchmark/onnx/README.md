# SigLIP 2 ONNX benchmark

Historical encoder export/benchmark. Not the product retrieval spec. Current model is OpenCLIP; see `.ai/SPEC.md`.

既存のデータセットとローカルモデルキャッシュを再利用し、Image/Text Encoderを個別にONNXへ変換します。生成モデル、量子化モデル、embeddingは `onnx/cache/` に置かれ、Git対象外です。

```powershell
cd tools\semantic_search_benchmark
.\.venv\Scripts\python.exe .\onnx\benchmark_onnx.py
```

短い変換・動作確認は `--quick`、再exportは `--force-export` を指定します。ネットワークを無効化した状態でモデルを読み込むため、事前に既存benchmarkのSigLIP 2キャッシュが必要です。
