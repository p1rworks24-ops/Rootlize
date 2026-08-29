from __future__ import annotations

from tools.meaning_eval.freeform_chunking import (
    CLIP_CONTENT_LIMIT,
    split_clauses,
    split_document,
    split_sentences,
)
from tools.meaning_eval.freeform_doc_matching import (
    DOC_MATCH_CONFIGS,
    DocMatchConfig,
    _chunk_is_background,
    _chunk_lexical_score,
    doc_match_judgement,
    extract_primary_span,
    fp_eval_configs,
    generic_token_density,
    search_doc_matching_records,
)
from tools.meaning_eval.index_only_doc_matching import (
    FP_CAUSE_ENVIRONMENT,
    classify_doc_fn,
    classify_doc_fp,
)
from tools.meaning_eval.index_only_fp_gate import select_fp_gate_policies


class _FakeRuntime:
    def embed_text(self, text: str) -> list[float]:
        words = text.lower().split()
        if "chrome" in words:
            return [1.0] + [0.0] * 511
        if "dark" in words and "theme" in words:
            return [0.0, 1.0] + [0.0] * 510
        if "dog" in words:
            return [0.0, 0.0, 1.0] + [0.0] * 509
        return [0.0] * 512


def test_split_sentences_keeps_long_document_in_parts():
    text = "Google Chrome is open. ChatGPT fills the page. The Windows taskbar is visible."
    parts = split_sentences(text)
    assert len(parts) == 3
    assert parts[0].startswith("Google Chrome")


def test_split_document_respects_sentence_strategy():
    runtime = _FakeRuntime()
    text = "A dark code editor is open. Google Chrome sits behind it on the desktop wallpaper."
    chunks = split_document(text, "sentence", runtime)
    assert len(chunks) >= 2
    assert all(len(chunk) > 0 for chunk in chunks)


def test_split_document_overlap_window_produces_multiple_chunks():
    runtime = _FakeRuntime()
    text = " ".join(["visible content"] * 120)
    chunks = split_document(text, "overlap_window", runtime)
    assert len(chunks) >= 3


def test_chunk_lexical_score_supports_partial_multi_token_match():
    chunk = "A dark themed chat application fills the screen."
    assert _chunk_lexical_score("dark themed application", chunk) >= 0.67
    assert _chunk_lexical_score("giraffe", chunk) == 0.0


def test_background_chunk_detection():
    assert _chunk_is_background("The Windows desktop wallpaper is visible in the background.")
    assert not _chunk_is_background("Google Chrome is open to ChatGPT.")


def test_doc_match_judgement_hits_semantic_chunk_without_full_token_coverage():
    config = DocMatchConfig(
        "test", "sentence", "max", txt_min=0.22, lex_support=0.34, lex_include=1.0,
    )
    record = {
        "search_document": (
            "Google Chrome is open to ChatGPT. A dark themed chat interface fills "
            "the page. The Windows desktop wallpaper is visible in the background."
        )
    }
    chunks = [
        {
            "text": "Google Chrome is open to ChatGPT.",
            "vector": [1.0] + [0.0] * 511,
            "position": 0,
            "is_background": False,
        },
        {
            "text": "A dark themed chat interface fills the page.",
            "vector": [0.0, 1.0] + [0.0] * 510,
            "position": 1,
            "is_background": False,
        },
        {
            "text": "The Windows desktop wallpaper is visible in the background.",
            "vector": [0.0] * 512,
            "position": 2,
            "is_background": True,
        },
    ]
    judged = doc_match_judgement(
        "dark themed application",
        record,
        query_vector=[0.0, 1.0] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["relevant"] is True
    assert judged["txt"] >= 0.22


def test_broad_ui_query_penalizes_background_only_match():
    config = DocMatchConfig(
        "test_ctx", "sentence", "max", txt_min=0.20, lex_support=0.34,
        lex_include=1.0, background_penalty=0.35, require_non_bg_for_broad=True,
    )
    record = {"search_document": "Google Chrome is open. The Windows desktop wallpaper is visible in the background."}
    chunks = [
        {
            "text": "Google Chrome is open.",
            "vector": [1.0] + [0.0] * 511,
            "position": 0,
            "is_background": False,
        },
        {
            "text": "The Windows desktop wallpaper is visible in the background.",
            "vector": [0.0, 0.25] + [0.0] * 510,
            "position": 1,
            "is_background": True,
        },
    ]
    judged = doc_match_judgement(
        "Windows desktop",
        record,
        query_vector=[0.0, 0.25] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["relevant"] is False


def test_search_doc_matching_records_is_deterministic():
    records = {
        "a.png": {"search_document": "A sitting brown dog on grass."},
        "b.png": {"search_document": "A mountain wallpaper on a Windows desktop."},
    }
    chunk_index = {
        "a.png": [{
            "text": "A sitting brown dog on grass.",
            "vector": [0.0, 0.0, 1.0] + [0.0] * 509,
            "position": 0,
            "is_background": False,
        }],
        "b.png": [{
            "text": "A mountain wallpaper on a Windows desktop.",
            "vector": [0.0] * 512,
            "position": 0,
            "is_background": True,
        }],
    }
    config = DOC_MATCH_CONFIGS[0]
    query_vector = [0.0, 0.0, 1.0] + [0.0] * 509
    first = search_doc_matching_records(
        "dog", ["b.png", "a.png"], records,
        query_vector=query_vector, chunk_index=chunk_index, config=config,
    )
    second = search_doc_matching_records(
        "dog", ["b.png", "a.png"], records,
        query_vector=query_vector, chunk_index=chunk_index, config=config,
    )
    assert first["predicted"] == ["a.png"]
    assert first["predicted"] == second["predicted"]


def test_fn_classifier_marks_matching_miss_when_terms_present():
    config = DOC_MATCH_CONFIGS[0]
    item = classify_doc_fn(
        query="code editor",
        name="editor.png",
        judgement={"lex": 0.5, "txt": 0.10, "relevant": False, "non_bg_txt": 0.10},
        record={"search_document": "A dark code editor is open."},
        config=config,
    )
    assert item["cause"] == "present_but_matching_miss"


def _gated_config(**overrides) -> DocMatchConfig:
    values = dict(
        name="gate_test",
        chunk_strategy="sentence",
        aggregation="max",
        txt_min=0.22,
        lex_support=0.50,
        lex_include=0.67,
        generic_density_min=2 / 3,
        opening_gate=True,
        min_evidence=1,
    )
    values.update(overrides)
    return DocMatchConfig(**values)


def test_generic_token_density_is_query_agnostic():
    assert generic_token_density("Windows desktop") == 1.0
    assert generic_token_density("image gallery") == 1.0
    assert generic_token_density("image search application") == 1.0
    assert generic_token_density("dark themed application") < 0.5
    assert generic_token_density("dog") == 0.0
    assert generic_token_density("Chrome") == 0.0
    assert generic_token_density("folder selection screen") >= 2 / 3


def test_extract_primary_span_drops_scene_setting_prefix():
    framed = (
        "A Windows desktop is shown with a large black Windows PowerShell "
        "terminal window in the foreground"
    )
    span = extract_primary_span(framed).lower()
    assert "powershell" in span
    assert "desktop is shown with" not in span
    subject = (
        "Windows 11 desktop with a calm lake-and-mountains wallpaper, "
        "no open application windows"
    )
    assert "desktop" in extract_primary_span(subject).lower()


def test_extract_primary_span_keeps_foreground_app_clause():
    framed = (
        "A Windows desktop is shown with Google Chrome open in the background, "
        "while the Images screenshot-capture application is centered in front."
    )
    span = extract_primary_span(framed).lower()
    assert "images" in span
    assert "application" in span
    assert "chrome open in the background" not in span


def test_opening_gate_rejects_desktop_as_scene_not_subject():
    config = _gated_config(opening_gate=True)
    chunks = [
        {
            "text": (
                "A Windows desktop is shown with a large black Windows "
                "PowerShell terminal window in the foreground."
            ),
            "vector": [0.0, 0.4] + [0.0] * 510,
            "position": 0,
            "is_background": False,
        },
        {
            "text": "The taskbar is visible along the bottom of the screen.",
            "vector": [0.0] * 512,
            "position": 1,
            "is_background": True,
        },
    ]
    judged = doc_match_judgement(
        "Windows desktop",
        {"search_document": chunks[0]["text"]},
        query_vector=[0.0, 0.4] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["high_generic"] is True
    assert judged["relevant"] is False


def test_opening_gate_rejects_incidental_background_opening():
    config = _gated_config(opening_gate=True)
    chunks = [
        {
            "text": "The Windows desktop wallpaper is visible in the background.",
            "vector": [0.0, 0.4] + [0.0] * 510,
            "position": 0,
            "is_background": True,
        },
    ]
    judged = doc_match_judgement(
        "Windows desktop",
        {"search_document": chunks[0]["text"]},
        query_vector=[0.0, 0.4] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["opening_relevant"] is False
    assert judged["relevant"] is False


def test_opening_gate_accepts_desktop_as_primary_subject():
    config = _gated_config(opening_gate=True)
    chunks = [
        {
            "text": (
                "Windows 11 desktop with a calm lake-and-mountains wallpaper "
                "and no open application windows."
            ),
            "vector": [0.0, 0.5] + [0.0] * 510,
            "position": 0,
            "is_background": False,
        },
    ]
    judged = doc_match_judgement(
        "Windows desktop",
        {"search_document": chunks[0]["text"]},
        query_vector=[0.0, 0.5] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["opening_relevant"] is True
    assert judged["relevant"] is True


def test_opening_gate_keeps_three_token_product_query():
    config = _gated_config(opening_gate=True, min_evidence=2)
    chunks = [
        {
            "text": (
                "A screenshot manager application showing an image gallery "
                "and a search box."
            ),
            "vector": [0.0, 0.6] + [0.0] * 510,
            "position": 0,
            "is_background": False,
        },
        {
            "text": "Thumbnails fill the image search results grid.",
            "vector": [0.0, 0.5] + [0.0] * 510,
            "position": 1,
            "is_background": False,
        },
    ]
    judged = doc_match_judgement(
        "image search application",
        {"search_document": " ".join(item["text"] for item in chunks)},
        query_vector=[0.0, 0.6] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["high_generic"] is True
    assert judged["relevant"] is True


def test_multi_evidence_rejects_semantic_only_generic_query():
    config = _gated_config(opening_gate=False, min_evidence=2)
    chunks = [
        {
            "text": "A code editor fills the screen with syntax highlighting.",
            "vector": [0.0, 0.2] + [0.0] * 510,
            "position": 0,
            "is_background": False,
        },
        {
            "text": "Line numbers and a file tree occupy the left pane.",
            "vector": [0.0, 0.15] + [0.0] * 510,
            "position": 1,
            "is_background": False,
        },
        {
            "text": "An image thumbnail sits in the corner of the window.",
            "vector": [0.0, 0.9] + [0.0] * 510,
            "position": 2,
            "is_background": False,
        },
    ]
    judged = doc_match_judgement(
        "image gallery",
        {"search_document": " ".join(item["text"] for item in chunks)},
        query_vector=[0.0, 0.9] + [0.0] * 510,
        chunks=chunks,
        config=config,
    )
    assert judged["high_generic"] is True
    assert judged["evidence_count"] < 2
    assert judged["relevant"] is False


def test_specific_object_query_is_not_density_gated():
    config = _gated_config(opening_gate=True, min_evidence=2)
    chunks = [
        {
            "text": "A sitting brown dog on grass.",
            "vector": [0.0, 0.0, 1.0] + [0.0] * 509,
            "position": 0,
            "is_background": False,
        },
    ]
    judged = doc_match_judgement(
        "dog",
        {"search_document": chunks[0]["text"]},
        query_vector=[0.0, 0.0, 1.0] + [0.0] * 509,
        chunks=chunks,
        config=config,
    )
    assert judged["high_generic"] is False
    assert judged["relevant"] is True


def test_fp_eval_configs_include_sent_top2_and_gates():
    names = [config.name for config in fp_eval_configs()]
    assert names[0] == "sent_top2_0.22"
    assert names[1] == "ovlp_ctx_0.20"
    assert "sent_open_gate" in names
    assert "sent_fp_all" in names
    assert "ovlp_fp_all" in names


def test_select_fp_gate_uses_dev_only_and_prefers_lower_broad_fp():
    baseline_dev = {"macro_recall": 0.69, "macro_f1": 0.60, "macro_precision": 0.53}
    dev_by_config = {
        "noisy": {
            "macro_precision": 0.30, "macro_recall": 0.75, "macro_f1": 0.43,
            "micro_fp": 400, "micro_fn": 20, "micro_tp": 40,
            "micro_precision": 0.09, "micro_recall": 0.67, "micro_f1": 0.16,
        },
        "gated": {
            "macro_precision": 0.55, "macro_recall": 0.72, "macro_f1": 0.62,
            "micro_fp": 180, "micro_fn": 24, "micro_tp": 36,
            "micro_precision": 0.17, "micro_recall": 0.60, "micro_f1": 0.26,
        },
    }
    selection = select_fp_gate_policies(
        dev_by_config=dev_by_config,
        chrome_by_config={"noisy": 12, "gated": 12},
        broad_fp_dev_by_config={"noisy": 120, "gated": 40},
        guard_recall_by_config={
            "noisy": {"dog": 1.0, "image search application": 0.8},
            "gated": {"dog": 1.0, "image search application": 0.8},
        },
        baseline_dev=baseline_dev,
        baseline_guard_recall={"dog": 1.0, "image search application": 0.38},
    )
    assert selection["selection_split"] == "dev"
    assert selection["holdout_used_for_retune"] is False
    assert selection["selected"] == "gated"


def test_fp_classifier_marks_environment_background():
    item = classify_doc_fp(
        query="Windows desktop",
        name="shot.png",
        judgement={
            "lex": 0.5,
            "txt": 0.3,
            "best_chunk": {
                "text_preview": "The Windows desktop wallpaper is visible in the background.",
                "is_background": True,
            },
        },
        record={"search_document": "Chrome is open. Desktop wallpaper in background."},
    )
    assert item["cause"] == FP_CAUSE_ENVIRONMENT
