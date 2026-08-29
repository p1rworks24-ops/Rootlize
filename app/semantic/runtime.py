"""Manifest-driven Torch-free SigLIP 2 / OpenCLIP ONNX adapter."""

from __future__ import annotations

import json
from pathlib import Path

from .bundle import ModelBundle
from .image_decode import decode_semantic_image
from .worker_errors import SemanticWorkerError
from app.utils.logger import setup_logger


logger = setup_logger()


class SemanticRuntime:
    def __init__(self, bundle: ModelBundle):
        self.bundle = bundle
        self.image_session = None
        self.text_session = None
        self.tokenizer = None

    @property
    def adapter(self) -> str:
        return str(self.bundle.manifest.get("adapter", "siglip2"))

    @property
    def loaded(self) -> list[str]:
        result = []
        if self.image_session is not None: result.append("image_encoder")
        if self.text_session is not None: result.append("text_encoder")
        return result

    @staticmethod
    def _options():
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return options

    def load(self, components: list[str]) -> None:
        try:
            import onnxruntime as ort
            try: runtime_version=tuple(int(part) for part in ort.__version__.split(".")[:2])
            except (AttributeError,ValueError): runtime_version=(0,0)
            if runtime_version < (1,28):
                raise SemanticWorkerError("Semantic runtime is incompatible.", code="MODEL_INCOMPATIBLE")
            for component in components:
                if component == "image_encoder" and self.image_session is None:
                    self.image_session = ort.InferenceSession(str(self.bundle.files[component]), sess_options=self._options(), providers=["CPUExecutionProvider"])
                elif component == "text_encoder" and self.text_session is None:
                    self.text_session = ort.InferenceSession(str(self.bundle.files[component]), sess_options=self._options(), providers=["CPUExecutionProvider"])
                    if self.adapter == "openclip":
                        from .openclip_tokenizer import SimpleTokenizer
                        self.tokenizer = SimpleTokenizer(self.bundle.files["tokenizer"])
                    else:
                        from tokenizers import Tokenizer
                        config = json.loads(self.bundle.files["tokenizer_config"].read_text(encoding="utf-8"))
                        self.tokenizer = Tokenizer.from_file(str(self.bundle.files["tokenizer"]))
                        maximum = int(self.bundle.manifest["text"]["max_length"])
                        pad_token = config.get("pad_token", "<pad>"); pad_id = self.tokenizer.token_to_id(pad_token)
                        if pad_id is None: raise ValueError("Tokenizer pad token is missing.")
                        self.tokenizer.enable_truncation(max_length=maximum)
                        self.tokenizer.enable_padding(length=maximum, pad_id=pad_id, pad_token=pad_token)
                elif component not in {"image_encoder", "text_encoder"}:
                    raise SemanticWorkerError("Unknown model component.", code="INVALID_REQUEST")
        except SemanticWorkerError:
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            logger.exception("Semantic runtime dependency import failed")
            raise SemanticWorkerError("Semantic runtime is not installed.", code="MODEL_LOAD_FAILED") from exc
        except Exception as exc:
            logger.exception("Semantic model load failed")
            raise SemanticWorkerError("Semantic model could not be loaded.", code="MODEL_LOAD_FAILED") from exc

    def _normalized(self, row) -> list[float]:
        import numpy as np
        vector = np.asarray(row, dtype=np.float32).reshape(-1)
        if vector.size != self.bundle.identity.dimension or not np.isfinite(vector).all():
            raise SemanticWorkerError("Model returned an invalid embedding.", code="INFERENCE_FAILED")
        norm = float(np.linalg.norm(vector))
        if not norm:
            raise SemanticWorkerError("Model returned an invalid embedding.", code="INFERENCE_FAILED")
        return (vector / np.float32(norm)).astype("<f4", copy=False).tolist()

    def embed_image(self, path: Path) -> list[float]:
        self.load(["image_encoder"])
        try:
            import numpy as np
            from PIL import Image
            config = json.loads(self.bundle.files["preprocess_config"].read_text(encoding="utf-8"))
            size = config["size"]; resample = Image.Resampling(config.get("resample", Image.Resampling.BICUBIC))
            with decode_semantic_image(path) as source:
                width, height = int(size["width"]), int(size["height"])
                if config.get("resize_mode") == "shortest_center_crop":
                    scale = max(width / source.width, height / source.height)
                    resized = source.resize((round(source.width * scale), round(source.height * scale)), resample)
                    left = (resized.width - width) // 2; top = (resized.height - height) // 2
                    image = resized.crop((left, top, left + width, top + height))
                else:
                    image = source.resize((width, height), resample)
                values = np.asarray(image, dtype=np.float32) * np.float32(config.get("rescale_factor", 1 / 255))
            mean = np.asarray(config.get("image_mean", [.5, .5, .5]), dtype=np.float32)
            std = np.asarray(config.get("image_std", [.5, .5, .5]), dtype=np.float32)
            pixels = ((values - mean) / std).transpose(2, 0, 1)[None].astype(np.float32, copy=False)
            output = self.image_session.run(["embedding"], {"pixel_values": pixels})[0][0]
            return self._normalized(output)
        except SemanticWorkerError: raise
        except Exception as exc: raise SemanticWorkerError("Image inference failed.", code="INFERENCE_FAILED", retryable=True) from exc

    def embed_text(self, text: str) -> list[float]:
        self.load(["text_encoder"])
        try:
            import numpy as np
            if self.adapter == "openclip":
                ids = self.tokenizer(text)
            else:
                ids = np.asarray([self.tokenizer.encode(text, add_special_tokens=True).ids], dtype=np.int64)
            output = self.text_session.run(["embedding"], {"input_ids": ids})[0][0]
            return self._normalized(output)
        except SemanticWorkerError: raise
        except Exception as exc: raise SemanticWorkerError("Text inference failed.", code="TOKENIZER_FAILED") from exc
