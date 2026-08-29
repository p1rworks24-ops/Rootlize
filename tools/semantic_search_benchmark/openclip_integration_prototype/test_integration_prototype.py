from pathlib import Path

import numpy as np

from runtime import preprocess_image
from tokenizer import SimpleTokenizer

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent / "openclip_onnx_poc" / "bundle"


def test_tokenizer_contract_and_known_tokens():
    tokenizer = SimpleTokenizer(BUNDLE / "bpe_simple_vocab_16e6.txt.gz")
    values = tokenizer(["Windows desktop", "dog"])
    assert values.shape == (2, 77) and values.dtype == np.int64
    assert values[0, 0] == tokenizer.sot and tokenizer.eot in values[0]
    assert len(tokenizer.encoder) == 49408


def test_preprocessing_contract(tmp_path):
    from PIL import Image
    path = tmp_path / "wide.png"
    Image.new("RGB", (400, 200), (10, 20, 30)).save(path)
    values = preprocess_image(path)
    assert values.shape == (1, 3, 224, 224) and values.dtype == np.float32
    assert np.isfinite(values).all()
