from __future__ import annotations

import math
import struct
from collections.abc import Iterable

EMBEDDING_DIMENSION = 768
EMBEDDING_FORMAT_VERSION = 1
SUPPORTED_EMBEDDING_DIMENSIONS = frozenset({512, 768})
EMBEDDING_BYTE_LENGTH = EMBEDDING_DIMENSION * 4
NORMALIZATION_TOLERANCE = 1e-3


class SemanticValidationError(ValueError):
    pass


def validate_values(values: Iterable[float], *, dimension: int = EMBEDDING_DIMENSION) -> tuple[float, ...]:
    if dimension not in SUPPORTED_EMBEDDING_DIMENSIONS:
        raise SemanticValidationError(f"Unsupported embedding dimension: {dimension}.")
    result = tuple(float(value) for value in values)
    if len(result) != dimension:
        raise SemanticValidationError(f"Expected {dimension} embedding values.")
    if not all(math.isfinite(value) for value in result):
        raise SemanticValidationError("Embedding contains a non-finite value.")
    norm = math.sqrt(sum(value * value for value in result))
    if not math.isfinite(norm) or abs(norm - 1.0) > NORMALIZATION_TOLERANCE:
        raise SemanticValidationError("Embedding is not L2 normalized.")
    return result


def encode_embedding(values: Iterable[float], *, dimension: int = EMBEDDING_DIMENSION) -> bytes:
    validated = validate_values(values, dimension=dimension)
    encoded = struct.pack(f"<{dimension}f", *validated)
    # Quantization to FP32 must not move the vector outside the contract.
    validate_embedding_blob(encoded, dimension=dimension)
    return encoded


def decode_embedding(blob: bytes | bytearray | memoryview, *, dimension: int = EMBEDDING_DIMENSION) -> tuple[float, ...]:
    raw = bytes(blob)
    if len(raw) != dimension * 4:
        raise SemanticValidationError(f"Expected {dimension * 4} embedding bytes.")
    try:
        values = struct.unpack(f"<{dimension}f", raw)
    except struct.error as exc:
        raise SemanticValidationError("Embedding cannot be decoded.") from exc
    return validate_values(values, dimension=dimension)


def validate_embedding_blob(blob: bytes | bytearray | memoryview, *, dimension: int = EMBEDDING_DIMENSION) -> bytes:
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise SemanticValidationError("Embedding must be a bytes-like value.")
    raw = bytes(blob)
    decode_embedding(raw, dimension=dimension)
    return raw
