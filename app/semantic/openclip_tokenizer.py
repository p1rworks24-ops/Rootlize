"""OpenAI CLIP byte-level BPE tokenizer without optional third-party deps.

ftfy and the ``regex`` package improve Unicode cleanup when installed, but
Meaning search must still load in a stock Python environment. Frozen builds
also omit those packages unless they are explicitly collected.
"""

from __future__ import annotations

import gzip
import html
import re as stdlib_re
from functools import lru_cache
from pathlib import Path

import numpy as np

try:
    import ftfy as _ftfy
except ImportError:
    _ftfy = None

try:
    import regex as _regex
except ImportError:
    _regex = None

_BPE_PATTERN_REGEX = (
    r"<start_of_text>|<end_of_text>|'s|'t|'re|'ve|'m|'ll|'d|"
    r"[\p{L}]+|[\p{N}]|[^\s\p{L}\p{N}]+"
)
_BPE_PATTERN_STDLIB = (
    r"<start_of_text>|<end_of_text>|'s|'t|'re|'ve|'m|'ll|'d|"
    r"[^\W\d_]+|\d|[^\s\w]+"
)


@lru_cache()
def bytes_to_unicode() -> dict[int, str]:
    values = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    characters = values[:]
    offset = 0
    for value in range(256):
        if value not in values:
            values.append(value)
            characters.append(256 + offset)
            offset += 1
    return dict(zip(values, map(chr, characters)))


def _pairs(word: tuple[str, ...]) -> set[tuple[str, str]]:
    return set(zip(word, word[1:]))


def compile_bpe_pattern(regex_module=None):
    """Compile the CLIP BPE split pattern with regex if available, else stdlib."""
    if regex_module is not None:
        return regex_module.compile(_BPE_PATTERN_REGEX, regex_module.IGNORECASE)
    return stdlib_re.compile(_BPE_PATTERN_STDLIB, stdlib_re.IGNORECASE)


def clean_clip_text(text: str, ftfy_module=None) -> str:
    source = ftfy_module.fix_text(text) if ftfy_module is not None else text
    return " ".join(html.unescape(html.unescape(source)).strip().split()).lower()


class SimpleTokenizer:
    context_length = 77

    def __init__(self, bpe_path: Path):
        self.byte_encoder = bytes_to_unicode()
        with gzip.open(bpe_path, "rt", encoding="utf-8") as stream:
            merges = stream.read().split("\n")[1:49152 - 256 - 2 + 1]
        merge_pairs = [tuple(item.split()) for item in merges if item]
        vocab = list(self.byte_encoder.values())
        vocab += [item + "</w>" for item in vocab]
        vocab += ["".join(item) for item in merge_pairs]
        vocab += ["<start_of_text>", "<end_of_text>"]
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.bpe_ranks = dict(zip(merge_pairs, range(len(merge_pairs))))
        self.cache = {token: token for token in ("<start_of_text>", "<end_of_text>")}
        self.sot = self.encoder["<start_of_text>"]
        self.eot = self.encoder["<end_of_text>"]
        self.pattern = compile_bpe_pattern(_regex)

    def bpe(self, token: str) -> str:
        cached = self.cache.get(token)
        if cached is not None:
            return cached
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = _pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            first, second = min(pairs, key=lambda item: self.bpe_ranks.get(item, float("inf")))
            if (first, second) not in self.bpe_ranks:
                break
            merged = []
            index = 0
            while index < len(word):
                try:
                    match = word.index(first, index)
                    merged.extend(word[index:match])
                    index = match
                except ValueError:
                    merged.extend(word[index:])
                    break
                if index < len(word) - 1 and word[index] == first and word[index + 1] == second:
                    merged.append(first + second)
                    index += 2
                else:
                    merged.append(word[index])
                    index += 1
            word = tuple(merged)
            if len(word) == 1:
                break
            pairs = _pairs(word)
        result = " ".join(word)
        self.cache[token] = result
        return result

    def encode(self, text: str) -> list[int]:
        clean = clean_clip_text(text, _ftfy)
        result = []
        for token in self.pattern.findall(clean):
            encoded = "".join(self.byte_encoder[value] for value in token.encode("utf-8"))
            result.extend(self.encoder[piece] for piece in self.bpe(encoded).split(" "))
        return result

    def __call__(self, texts: str | list[str]) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        output = np.zeros((len(texts), self.context_length), dtype=np.int64)
        for row, text in enumerate(texts):
            tokens = [self.sot, *self.encode(text), self.eot]
            if len(tokens) > self.context_length:
                tokens = tokens[:self.context_length]
                tokens[-1] = self.eot
            output[row, :len(tokens)] = tokens
        return output
