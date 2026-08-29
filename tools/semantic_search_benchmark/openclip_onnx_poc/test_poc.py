import json
from pathlib import Path

import onnx

HERE = Path(__file__).resolve().parent


def test_export_contracts():
    expected = {"image_encoder.onnx": (["batch", 3, 224, 224], ["batch", 512]),
                "text_encoder.onnx": (["batch", 77], ["batch", 512])}
    for name, (input_shape, output_shape) in expected.items():
        model = onnx.load(str(HERE / "bundle" / name)); onnx.checker.check_model(model)
        shape = lambda value: [d.dim_param or d.dim_value for d in value.type.tensor_type.shape.dim]
        assert shape(model.graph.input[0]) == input_shape
        assert shape(model.graph.output[0]) == output_shape


def test_real_image_parity():
    result = json.loads((HERE / "comparison_results.json").read_text(encoding="utf-8"))
    assert result["images"] == 98 and result["queries"] == 24
    assert result["comparison"]["image_cosine"]["min"] > .99999
    assert result["comparison"]["text_cosine"]["min"] > .99999
    for key in ("top_1", "top_3", "top_5", "top_10", "mrr"):
        assert result["pytorch_metrics"][key] == result["onnx_metrics"][key]
    important = {q["query"]: q["relevant_ranks"] for q in result["onnx_metrics"]["queries"]}
    assert sorted(important["Windows desktop"].values()) == [1, 2, 3, 4]
    assert sorted(important["Windows desktop screenshot"].values()) == [1, 2, 3, 4]
    for query in ("dog", "a dog", "dog photo"):
        assert sorted(important[query].values()) == [1, 2]
