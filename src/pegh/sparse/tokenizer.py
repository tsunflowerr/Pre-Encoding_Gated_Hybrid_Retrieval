from __future__ import annotations

import re

from pegh.sparse.config import BM25Config


class TechnicalTokenizer:
    def __init__(self, config: BM25Config):
        self.config = config
        self.pattern = re.compile(config.token_pattern)

    @property
    def fingerprint(self) -> str:
        return self.config.fingerprint

    def tokenize(self, text: str) -> list[str]:
        if not isinstance(text, str):
            raise TypeError("tokenizer input must be a string")
        tokens = self.pattern.findall(text)
        return [token.casefold() for token in tokens] if self.config.lowercase else tokens
