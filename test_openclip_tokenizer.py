from pathlib import Path
import os

import pytest

from app.semantic.openclip_tokenizer import (
    SimpleTokenizer,
    clean_clip_text,
    compile_bpe_pattern,
)


def _installed_openclip_bpe() -> Path | None:
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if not local:
        return None
    root = Path(local) / "Capixe" / "semantic-models" / "openclip-v1" / "bpe_simple_vocab_16e6.txt.gz"
    return root if root.is_file() else None


def test_stdlib_bpe_pattern_keeps_ascii_and_cjk():
    pattern = compile_bpe_pattern(None)
    assert pattern.findall("dog") == ["dog"]
    assert pattern.findall("犬") == ["犬"]
    tokens = pattern.findall("Windowsデスクトップ")
    assert tokens
    joined = "".join(tokens).lower()
    assert "windows" in joined
    assert "デスクトップ" in joined


def test_clean_clip_text_does_not_require_ftfy():
    assert clean_clip_text("  Dog\nPicture  ", None) == "dog picture"


def test_simple_tokenizer_encodes_meaning_queries_without_optional_deps():
    bpe = _installed_openclip_bpe()
    if bpe is None:
        pytest.skip("OpenCLIP BPE file is not installed")
    tokenizer = SimpleTokenizer(bpe)
    for query in ("dog", "犬", "Windows desktop"):
        ids = tokenizer.encode(query)
        assert ids, query
        matrix = tokenizer(query)
        assert matrix.shape == (1, 77)
        assert int(matrix[0, 0]) == tokenizer.sot
        assert tokenizer.eot in set(int(value) for value in matrix[0] if value)
