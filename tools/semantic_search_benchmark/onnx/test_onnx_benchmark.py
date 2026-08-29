import importlib.util
from pathlib import Path

import numpy as np
import onnx

MODULE = Path(__file__).with_name("benchmark_onnx.py")
spec = importlib.util.spec_from_file_location("benchmark_onnx", MODULE)
benchmark = importlib.util.module_from_spec(spec); spec.loader.exec_module(benchmark)


def test_similarity_identity():
    values=np.array([[1.0,0.0],[0.0,1.0]],dtype=np.float32)
    result=benchmark.similarity(values,values)
    assert result["cosine_min"] == 1.0
    assert result["l2_mean"] == 0.0


def test_cache_is_ignored():
    ignore=(benchmark.ROOT/".gitignore").read_text(encoding="utf-8")
    assert "onnx/cache/" in ignore


def test_exported_graph_contract_when_cached():
    image=benchmark.FP32/"image_encoder.onnx"; text=benchmark.FP32/"text_encoder.onnx"
    if not image.exists() or not text.exists():
        return
    image_model=onnx.load(image,load_external_data=False)
    text_model=onnx.load(text,load_external_data=False)
    onnx.checker.check_model(image_model); onnx.checker.check_model(text_model)
    assert [x.name for x in image_model.graph.input] == ["pixel_values"]
    assert [x.name for x in text_model.graph.input] == ["input_ids"]
    assert image_model.graph.output[0].name == text_model.graph.output[0].name == "embedding"
