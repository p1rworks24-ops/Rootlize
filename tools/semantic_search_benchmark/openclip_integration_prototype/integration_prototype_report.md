# OpenCLIP integration prototype 検証報告

## 結論

正式製品移行の実装段階へ進むことを推奨する。OpenCLIP ViT-B/32 LAION-2B FP32 ONNXは、Capixe製品外の独立process、UTF-8 JSON Lines、遅延model load、ONNX Runtime 1.28.0 CPUExecutionProviderという製品workerに近い構成で安定動作した。98実画像・24 queryの保存済みPoC入力に対してembeddingとsimilarityが一致し、PoCと同じランキング指標を維持した。

この検証では製品Semantic worker、DB schema、現行SigLIP 2 bundle、既存embeddingを変更していない。packaged Capixeのbuild・実機検証も実施していない。

## prototype構成

- `runtime.py`: image/text ONNX session、OpenCLIP image preprocessing、L2 normalization、cosine search
- `tokenizer.py`: OpenAI CLIP SimpleTokenizer互換のbyte-level BPE。`open_clip` とPyTorchには非依存
- `worker.py`: 独立processで動くUTF-8 JSON Lines worker。ping、status、遅延load、image/text embedding、error、shutdownを実装
- `run_validation.py`: worker lifecycle、98画像/24 query品質、性能、RAM、PoC parityを検証
- `test_integration_prototype.py`: tokenizer、preprocessingの契約テスト
- `validation_results.json`: 実測結果のmachine-readable記録

## preprocessing / tokenizer

Image preprocessingはRGB変換、EXIF transpose、shortest-side bicubic resize、224 x 224 center crop、`1/255` rescale、mean `[0.48145466, 0.4578275, 0.40821073]`、std `[0.26862954, 0.26130258, 0.27577711]`、CHW float32である。workspace内の実画像をOpenCLIP 3.3.0参照transformと比較し、tensor最大絶対差は0だった。

Tokenizerは同梱 `bpe_simple_vocab_16e6.txt.gz` を使う49,408語彙のOpenAI SimpleTokenizer byte-level BPEで、lower clean、SOT/EOT付加、77 token、超過時は末尾をEOTとしてtruncate、0 paddingを行う。24 queryすべてでPoCが保存したOpenCLIP token IDと完全一致した。

Image/textのONNX出力はfloat32 512次元として検証し、各rowをFP32でL2正規化する。検索scoreは正規化済みtextとimageの内積、rankはscore降順のstable sortである。

## runtime / worker lifecycle

ONNX Runtime 1.28.0、CPUExecutionProvider、intra-op 4、inter-op 1、sequential execution、全graph optimizationで測定した。

| lifecycle | 結果 |
|---|---:|
| process起動 / ping | 成功 |
| image + text model load | 成功 |
| 実画像embedding request | 成功 |
| text embedding request | 成功 |
| 複数連続request | 成功 |
| 不正commandのstructured error | 成功 (`INVALID_REQUEST`) |
| graceful shutdown | 成功 |
| process再起動・再load | 成功 |
| 0.25秒設定でのidle shutdown相当 | 成功 |

## PoC parity / ranking

元の98画像ファイル群は現在のworkspaceに存在しなかったため、PoC時に同じ98実画像から保存した `prepared_inputs.npz` のfloat32 image tensorを別process IPCへ渡して比較した。preprocessing実装自体は別の実画像でOpenCLIP参照と差0を確認している。今後、元画像群が再配置された場合は `run_validation.py --images <directory>` でファイルdecodeからrankingまで再実行できる。

| 比較 | 結果 |
|---|---:|
| image embedding cosine min / mean | 0.99999976 / 1.00000000 |
| text embedding cosine min / mean | 0.99999982 / 1.00000000 |
| similarity最大絶対差 | 0.00000000 |
| tokenizer input ID | 24 / 24完全一致 |
| Top-1 | 50.0% |
| Top-3 | 66.7% |
| Top-5 | 70.8% |
| Top-10 | 79.2% |
| MRR | 0.602283 |

重要queryもPoC順位を維持した。

- `Windows desktop` / `Windows desktop screenshot`: 正解4画像が1 / 2 / 3 / 4
- `dog`: `images.jpg` 1、`A2.png` 2
- `a dog`: `A2.png` 1、`images.jpg` 2
- `dog photo`: `images.jpg` 1、`A2.png` 2
- `image search application`: 最良正解1
- `code editor`: 最良正解3
- `browser window`: 正解13
- `settings screen`: 最良正解21

後二つの弱さもPoCと同一で、integration劣化ではない。

## CPU性能 / RAM

同一PCでbatch 4、98画像を25回の連続IPC requestとして測定した代表run。

| 項目 | prototype | PoC ONNX |
|---|---:|---:|
| worker起動（ping込み） | 0.285秒 | 対象外 |
| 再起動（ping込み） | 0.375秒 | 対象外 |
| image + text model load | 1.445秒 | 1.494秒 |
| image | 38.48 ms/枚 | 133.46 ms/枚 |
| 98画像連続処理 | 3.771秒 | 13.079秒 |
| text | 24.18 ms/query | 41.94 ms/query |
| 24 query | 0.580秒 | 1.007秒 |
| Peak worker RAM | 756.00 MB | 723.36 MB |

prototypeの速度改善はintra-op 4 / sequential / batch 4設定を固定した影響が大きい。正式実装でも同じsession optionsを候補にするが、packaged buildでCPU世代差とUI同居時の応答性を再計測する。Peak RAMはPoC比約33 MB増で、独立worker・IPCを含むworking setとして妥当だが、optional機能としてidle shutdownを維持する。

## 製品移行に必要な変更箇所

### 768次元前提 / 512次元化

- `app/semantic/embedding.py`: `EMBEDDING_DIMENSION = 768` と既定encode/decode validation
- `app/semantic/runtime.py`: ONNX出力の `vector.size != 768`
- `app/semantic/worker.py`: fake embedding、`struct.pack("<768f")`、response envelope dimension
- `app/semantic/worker_client.py`: response envelopeのdimension 768固定
- `app/semantic/bundle.py`: manifest embedding dimension 768固定validation
- `app/semantic/repository.py`: identity dimensionを現行定数へ固定するvalidation
- real/worker/release系テストの768 assertionsとfake vectors
- `packaging/semantic-model-v1-manifest.json`: dimension 768および現行file roles

DBには既にembeddingごとの `dimension`、model/bundle/revision/pipeline/format version列があるため、512化そのものにschema変更は不要と見込む。ただし、製品コードのdimension固定をmanifest identity由来へ変更し、query embeddingと保存embeddingのidentity/dimension一致を検索前に必須検証する。

### tokenizer / preprocessing / manifest

- SigLIP 2のHugging Face tokenizer JSON/config接続を、同梱gzip BPEとSimpleTokenizerへ変更する。77 token、SOT/EOT、lower clean、truncate規則をmanifestで固定する
- SigLIP 2の直接224 x 224 resizeを、shortest-side bicubic + center cropへ変更する。mean/stdもOpenAI CLIP値へ変更する
- manifestにmodel ID/revision、512 normalized float32、opset 18、image/text I/O名とshape、preprocess方式、BPE file/hash、tokenizer algorithm/version、license/attributionを宣言する
- bundle loaderのrolesをOpenCLIP bundleへ合わせる。既存v1 manifestの意味を上書きせず、新bundle versionとして配布する

### stale判定 / embedding再生成

現行のmodel identity（model ID、bundle version、revision、pipeline version、embedding format version、dimension）比較を利用し、いずれかが違うSigLIP embeddingを `STALE_MODEL` とする。OpenCLIP bundleを有効化した時点で既存768次元rowは検索に混在させず、元画像から512次元を差分index処理で再生成する。移行中はText Searchへfallbackし、OpenCLIP再生成済み画像だけをSemantic候補にする。全件を一括破壊更新せず、通常のclaim/lease、pause/resume/cancel、失敗retryを使う。

## bundle migration / optional download / rollback

1. OpenCLIPを新しいbundle versionとしてreleaseし、現行SigLIP 2 version directoryは保持する。
2. `semantic-model-source.json` はOpenCLIP manifest URL/files base URL/versionへ切替可能にするが、初回起動で強制downloadしない。
3. 既存installerどおり一時directoryへdownloadし、size/SHA-256/manifest/runtime検証後だけversion directoryへ原子的に昇格する。
4. 利用者の明示操作後にOpenCLIPを選択し、512 embeddingをbackground再生成する。完了前もText Search fallbackを維持する。
5. rollbackはsource/current bundle pointerをSigLIP 2へ戻し、保持したSigLIP bundleを再選択する。OpenCLIP rowはidentity不一致として利用せず、既存SigLIP embeddingを保持している場合は即時復帰する。
6. DB容量上、同一image IDへupsertして旧embeddingを失う現行設計なら「即時rollback」と両立しない。正式移行前に、(a) 旧embeddingをbackup table/fileへ退避、(b) model identityをkeyに複数世代保持するschema migration、(c) rollback時にSigLIPを再生成、のどれを採用するか決める。今回DB schemaは変更していない。安全性と追加容量のバランスでは、移行期間限定backup DB/fileが最小変更である。

## PoCとの差と残課題

- PoCは単一process内の直接session実行、prototypeは独立workerとJSONL IPCを含む
- prototypeはOpenCLIP/PyTorch非依存の独自preprocessing/BPEを使用し、参照実装との一致を確認した
- worker起動、lazy load、連続request、structured error、graceful shutdown、restart、idle shutdownを追加検証した
- original 98 files不在のため、98件のdecode/preprocessingからの再走は未実施。ただし保存済み同一tensorでruntime/ranking parity、別実画像でpreprocessing差0を確認した
- packaged Capixe、installerからの実download、製品UI同居時、異なるCPU/メモリ条件は次タスク

次タスクは、feature flagまたは新bundle version選択を伴うpackaged integration buildを作り、旧SigLIPを残した状態で実機download、全画像再生成、検索fallback、cancel/restart、rollbackを検証することとする。
