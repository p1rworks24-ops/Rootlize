from app.semantic.query_embedding import (
    DEFAULT_QUERY_EMBEDDING,
    QUERY_EMBEDDING_RAW,
    QUERY_EMBEDDING_TEMPLATE_ENSEMBLE,
    QUERY_TEMPLATES,
    combine_normalized_embeddings,
    normalize_query_embedding_method,
    query_texts,
)


def test_raw_and_ensemble_are_shared_across_queries():
    assert DEFAULT_QUERY_EMBEDDING == QUERY_EMBEDDING_RAW
    assert query_texts("dog", QUERY_EMBEDDING_RAW) == ("dog",)
    assert query_texts("icon", QUERY_EMBEDDING_RAW) == ("icon",)
    dog = query_texts("dog", QUERY_EMBEDDING_TEMPLATE_ENSEMBLE)
    icon = query_texts("icon", QUERY_EMBEDDING_TEMPLATE_ENSEMBLE)
    assert dog == (
        "dog",
        "an image of dog",
        "a screenshot related to dog",
    )
    assert icon == (
        "icon",
        "an image of icon",
        "a screenshot related to icon",
    )
    assert QUERY_TEMPLATES == ("{q}", "an image of {q}", "a screenshot related to {q}")
    assert all("{q}" in template for template in QUERY_TEMPLATES)


def test_unknown_query_embedding_method_falls_back_to_default():
    assert normalize_query_embedding_method("nope") == DEFAULT_QUERY_EMBEDDING
    assert query_texts("dog", "per-query-special") == ("dog",)


def test_mean_pool_then_renormalize_is_query_agnostic():
    first = (1.0, 0.0, 0.0)
    second = (0.0, 1.0, 0.0)
    combined = combine_normalized_embeddings((first, second))
    assert combined[0] == combined[1]
    assert combined[2] == 0.0
    assert abs(sum(value * value for value in combined) - 1.0) < 1e-6
    assert combine_normalized_embeddings((first,)) == first
