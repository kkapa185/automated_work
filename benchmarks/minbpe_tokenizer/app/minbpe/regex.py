import regex as re

from .base import Tokenizer

GPT4_SPLIT_PATTERN = (
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}"""
    r"""| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""
)


class RegexTokenizer(Tokenizer):
    """BPE with a regex pre-split; merges never cross chunk boundaries."""

    def __init__(self, pattern=None):
        super().__init__()
        self.pattern = GPT4_SPLIT_PATTERN if pattern is None else pattern
        self.compiled_pattern = re.compile(self.pattern)
        self.inverse_special_tokens = {}

    def load(self, model_file):
        super().load(model_file)
        self.compiled_pattern = re.compile(self.pattern)
        self.inverse_special_tokens = {v: k for k, v in self.special_tokens.items()}

    def train(self, text, vocab_size, verbose=False):
        chunks = [list(c.encode("utf-8")) for c in self.compiled_pattern.findall(text)]
        self._train_chunks(chunks, vocab_size, verbose)

    def register_special_tokens(self, special_tokens):
        self.special_tokens = dict(special_tokens)
        self.inverse_special_tokens = {v: k for k, v in self.special_tokens.items()}
        self.vocab = self._build_vocab()

    def encode_ordinary(self, text):
        ids = []
        for chunk in self.compiled_pattern.findall(text):
            ids.extend(self._encode_chunk(chunk.encode("utf-8")))
        return ids

    def encode(self, text, allowed_special="none_raise"):
        if allowed_special == "all":
            special = self.special_tokens
        elif allowed_special == "none":
            special = {}
        elif allowed_special == "none_raise":
            special = {}
            for tok in self.special_tokens:
                if tok in text:
                    raise ValueError(f"special token {tok!r} found in text but not allowed")
        elif isinstance(allowed_special, (set, frozenset, list, tuple)):
            unknown = set(allowed_special) - set(self.special_tokens)
            if unknown:
                raise ValueError(f"unregistered special tokens: {sorted(unknown)}")
            special = {k: v for k, v in self.special_tokens.items() if k in allowed_special}
        else:
            raise ValueError(f"invalid allowed_special: {allowed_special!r}")
        if not special:
            return self.encode_ordinary(text)
        # longest first so overlapping specials resolve deterministically
        alt = "|".join(re.escape(k) for k in sorted(special, key=len, reverse=True))
        ids = []
        for part in re.split("(" + alt + ")", text):
            if part in special:
                ids.append(special[part])
            elif part:
                ids.extend(self.encode_ordinary(part))
        return ids
