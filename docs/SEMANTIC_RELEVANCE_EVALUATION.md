# OpenCLIP relevance evaluation

**Decision record, not the live product spec.** Current Meaning search contract: `.ai/SPEC.md`. Live evaluation harness: `tools/meaning_eval`. Numbers below are the 98-image study that justified not shipping a similarity-only filter.

## Decision

Do not ship a similarity-only binary relevance filter from this evaluation.
OpenCLIP keeps its current role as a ranking / candidate-retrieval model. A
Vision AI usefulness judge with a graded `relevance_score` decides whether an
image should appear as a search result, and in what order.

No OpenCLIP model, tokenizer, preprocessing, embedding, or ranking behavior was
changed.

## Data and parity

- 98 real images from `D:\07_Programs\shotlogue_test`
- 24 labeled English queries; the nine requested queries were used here
- saved PoC `prepared_inputs.npz` was evaluated with the exported OpenCLIP ONNX
  image and text towers
- all 24 reconstructed Top-10 lists matched the saved PoC result

## Requested-query score distributions

| Query | Positive min..max | Negative min..max | Best per-query threshold | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dog | 0.265390..0.275556 | 0.133663..0.245552 | 0.265390 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| a dog | 0.269106..0.269220 | 0.082386..0.206526 | 0.269106 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| dog photo | 0.269822..0.289225 | 0.064376..0.197581 | 0.269822 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| Windows desktop | 0.305104..0.330306 | 0.069266..0.281966 | 0.305104 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| Windows desktop screenshot | 0.318570..0.352216 | 0.077079..0.276084 | 0.318570 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| code editor | 0.229358..0.271249 | 0.114759..0.281925 | 0.229358 | 0.161 | 1.000 | 0.278 | 26 | 0 |
| image search application | 0.209170..0.289402 | 0.135118..0.286153 | 0.219460 | 0.289 | 0.846 | 0.431 | 27 | 2 |
| browser window | 0.265215 | 0.157293..0.294858 | 0.265215 | 0.077 | 1.000 | 0.143 | 12 | 0 |
| settings screen | 0.203578..0.240328 | 0.042342..0.280368 | 0.230331 | 0.122 | 0.833 | 0.213 | 36 | 1 |

The per-query thresholds above are diagnostic upper bounds, not a deployable
policy. Hard-coding them would overfit the test queries.

## General methods compared

All tunable methods below were optimized on the same nine queries, so the
figures are optimistic upper bounds.

| Method | Best parameter | Macro F1 |
|---|---:|---:|
| Single cosine threshold | 0.264989 | 0.515 |
| Score / top-score ratio | 0.899 | 0.604 |
| Query score z-score | 1.95 | 0.534 |
| Score percentile | 98.9 | 0.553 |
| Largest relative gap (top 10) | none | 0.483 |

The best relative method happens to separate the dog and Windows desktop
examples, but returns 9-13 candidates for several weak queries, misses all
settings-screen positives, and therefore does not generalize. A single fixed
threshold also produces 6-7 false positives for each Windows query while
missing useful positives in other categories.

## Product consequence

The former Semantic result limit was removed. Semantic-only diagnostics now
retrieve and log every candidate in the selected folder in unchanged similarity
order. This must not be presented as completed relevance filtering: OpenCLIP
remains a ranking / candidate-retrieval model. Meaning search uses a Vision
usefulness judge with a graded `relevance_score` as the primary result order;
embedding similarity is processing order and tie-break only.

Ongoing quality measurement is the Phase D platform in `tools/meaning_eval`.
It scores the frozen product retriever and the Retriever → Vision Judge →
ranking path on a versioned Ground Truth file. Labels and the dev / hold-out
split stay out of product search. See
`docs/VISION_RELEVANCE_REAL_API_RUNBOOK.md` section 2c.
