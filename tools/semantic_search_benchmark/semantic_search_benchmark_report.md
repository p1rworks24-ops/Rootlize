# Capixe Semantic Image Search Benchmark Report

## Executive Summary

推薦: **google/siglip2-base-patch16-224**。実測精度、Windows CPU性能、配布ライセンスを合わせた総合判断です。

## Compared Models

| Rank | Model | Family | License | Score |
|---:|---|---|---|---:|
| 1 | `google/siglip2-base-patch16-224` | SigLIP 2 | Apache-2.0 | 66.1 |
| 2 | `facebook/metaclip-2-worldwide-b32` | MetaCLIP 2 | CC-BY-NC-4.0 | 57.5 |
| 3 | `jinaai/jina-clip-v2` | jina-clip-v2 | CC-BY-NC-4.0 (downloaded weights) | 51.3 |

## Dataset

Wikimedia Commons metadata-grounded subset: 70 images. Capixe synthetic UI: 60 images. Total: 130 images.

Each Commons record retains its source page, creator, and per-file license in `data/manifest.json`. Downloads stay outside Git and are not redistributed. Synthetic UI images are generated locally from project-owned code.

## Accuracy

| Model | JA Top-1 | JA Top-3 | JA Top-5 | JA Top-10 | EN Top-1 | EN Top-3 | EN Top-5 | EN Top-10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SigLIP 2 | 42.9% | 53.6% | 75.0% | 82.1% | 67.9% | 71.4% | 92.9% | 96.4% |
| MetaCLIP 2 | 53.6% | 60.7% | 78.6% | 82.1% | 53.6% | 57.1% | 75.0% | 75.0% |
| jina-clip-v2 | 64.3% | 71.4% | 89.3% | 92.9% | 67.9% | 67.9% | 78.6% | 89.3% |

## Level Accuracy

Top-3 accuracy by query level:

| Model | L1 Object | L2 Scene | L3 Action | L4 Screenshot | L5 Challenge |
|---|---:|---:|---:|---:|---:|
| SigLIP 2 | 41.7% | 58.3% | 37.5% | 88.9% | 66.7% |
| MetaCLIP 2 | 33.3% | 50.0% | 50.0% | 88.9% | 50.0% |
| jina-clip-v2 | 50.0% | 66.7% | 50.0% | 94.4% | 66.7% |

## No-text / Screenshot Accuracy

| Model | No-text Top-1 | No-text Top-3 | Screenshot Top-1 | Screenshot Top-3 |
|---|---:|---:|---:|---:|
| SigLIP 2 | 36.7% | 50.0% | 83.3% | 83.3% |
| MetaCLIP 2 | 36.7% | 46.7% | 79.2% | 79.2% |
| jina-clip-v2 | 56.7% | 60.0% | 83.3% | 87.5% |

Wikimedia Commons photographs are the no-text subset. Screenshot includes Level 4 and Level 5 synthetic UI; Level 5 remains a separate Challenge.

## Performance

| Model | Load | Image / item | Query / item | Search 10k (measured/extrapolated) | Peak RAM | Dim | 10k vectors | Model cache |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SigLIP 2 | 6.72s | 118.9ms | 27.5ms | 6.78ms | 1141MB | 768 | 29.3MB | 1468MB |
| MetaCLIP 2 | 7.76s | 47.6ms | 4.3ms | 3.95ms | 1965MB | 512 | 19.5MB | 2318MB |
| jina-clip-v2 | 40.84s | 4593.4ms | 327.5ms | 9.78ms | 6336MB | 1024 | 39.1MB | 1667MB |

## Deployment

| Model | Windows CPU | ONNX | Offline | Commercial redistribution |
|---|---|---|---|---|
| SigLIP 2 | Measured | Feasibility only; model-specific validation required | Yes after caching | Yes |
| MetaCLIP 2 | Measured | Feasibility only; model-specific validation required | Yes after caching | No under downloaded-weight license |
| jina-clip-v2 | Measured | Feasibility only; model-specific validation required | Yes after caching | No under downloaded-weight license |

## Failure Cases

### SigLIP 2

| Query | Language | Level | Expected IDs | Top result | Failure type |
|---|---|---:|---|---|---|
| 猫 | ja | 1 | commons-019, commons-028, commons-031 | commons-029 (0.101) | Retrieval mismatch |
| a cat | en | 1 | commons-019, commons-028, commons-031 | commons-029 (0.127) | Retrieval mismatch |
| a car | en | 1 | commons-025, commons-026, commons-027 | commons-010 (0.107) | Retrieval mismatch |
| 人物 | ja | 1 | commons-035, commons-036, commons-037 | commons-009 (0.076) | Retrieval mismatch |
| 料理や食べ物 | ja | 1 | commons-048 | commons-062 (0.051) | Retrieval mismatch |
| food or a meal | en | 1 | commons-048 | commons-062 (0.056) | Retrieval mismatch |
| ノートPC | ja | 1 | commons-055, commons-056, commons-057 | synthetic-027 (0.080) | Retrieval mismatch |
| 街の風景 | ja | 2 | commons-028, commons-039, commons-048 | commons-027 (0.102) | Retrieval mismatch |

### MetaCLIP 2

| Query | Language | Level | Expected IDs | Top result | Failure type |
|---|---|---:|---|---|---|
| 猫 | ja | 1 | commons-019, commons-028, commons-031 | commons-029 (0.233) | Retrieval mismatch |
| a cat | en | 1 | commons-019, commons-028, commons-031 | commons-029 (0.227) | Retrieval mismatch |
| a car | en | 1 | commons-025, commons-026, commons-027 | commons-010 (0.165) | Retrieval mismatch |
| 人物 | ja | 1 | commons-035, commons-036, commons-037 | commons-009 (0.166) | Retrieval mismatch |
| a person | en | 1 | commons-035, commons-036, commons-037 | synthetic-031 (0.151) | Retrieval mismatch |
| 料理や食べ物 | ja | 1 | commons-048 | commons-029 (0.143) | Retrieval mismatch |
| food or a meal | en | 1 | commons-048 | commons-007 (0.144) | Retrieval mismatch |
| a laptop computer | en | 1 | commons-055, commons-056, commons-057 | synthetic-037 (0.159) | Retrieval mismatch |

### jina-clip-v2

| Query | Language | Level | Expected IDs | Top result | Failure type |
|---|---|---:|---|---|---|
| 犬 | ja | 1 | commons-020, commons-021, commons-022 | commons-009 (0.234) | Retrieval mismatch |
| 猫 | ja | 1 | commons-019, commons-028, commons-031 | commons-029 (0.302) | Retrieval mismatch |
| a cat | en | 1 | commons-019, commons-028, commons-031 | commons-029 (0.357) | Retrieval mismatch |
| a car | en | 1 | commons-025, commons-026, commons-027 | commons-010 (0.235) | Retrieval mismatch |
| 料理や食べ物 | ja | 1 | commons-048 | commons-062 (0.186) | Retrieval mismatch |
| food or a meal | en | 1 | commons-048 | commons-062 (0.198) | Retrieval mismatch |
| 街の風景 | ja | 2 | commons-028, commons-039, commons-048 | commons-027 (0.265) | Retrieval mismatch |
| a city scene | en | 2 | commons-028, commons-039, commons-048 | commons-027 (0.294) | Retrieval mismatch |

## Ranking Method

Retrieval accuracy 35%, Japanese/multilingual 25%, CPU performance 15%, model/runtime size 10%, Windows deployment 10%, license/maintainability 5%. The numerical ranking describes benchmark fitness; downloaded weights that prohibit commercial redistribution are ineligible for the Capixe recommendation regardless of score.

## Main Weaknesses

The recommended model's UI and abstract-relation weaknesses are visible in Level 4/5 and failure cases. Visual embeddings cannot replace OCR for exact error messages, product attributes, or other text-heavy intent; those remain Hybrid Search candidates.

## Reproduction

```powershell
.\run_benchmark.ps1
```
