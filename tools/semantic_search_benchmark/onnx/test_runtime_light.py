from pathlib import Path

import numpy as np
from PIL import Image

from runtime_light import LightweightTokenizer, preprocess_images


def test_module_is_torch_and_transformers_free():
    source = Path(__file__).with_name("runtime_light.py").read_text(encoding="utf-8")
    assert "import torch" not in source
    assert "import transformers" not in source


def test_preprocessing_contract(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "preprocessor_config.json").write_text('{"size":{"height":224,"width":224},"resample":2,"image_mean":[0.5,0.5,0.5],"image_std":[0.5,0.5,0.5],"rescale_factor":0.00392156862745098}', encoding="utf-8")
    image_path = tmp_path / "rgb.png"
    Image.new("RGB", (400, 200), (255, 128, 0)).save(image_path)
    values = preprocess_images([image_path], model_dir)
    assert values.shape == (1, 3, 224, 224)
    assert values.dtype == np.float32
    assert np.isclose(values[0, 0, 0, 0], 1.0)


def test_tokenizer_contract_when_model_is_cached():
    snapshots = list((Path(__file__).parents[1] / "cache" / "models" / "google--siglip2-base-patch16-224").glob("models--*/snapshots/*"))
    if not snapshots:
        return
    ids = LightweightTokenizer(snapshots[0]).encode(["日本語の設定画面", "a terminal error"])
    assert ids.shape == (2, 64)
    assert ids.dtype == np.int64
