from .base import Tokenizer


class BasicTokenizer(Tokenizer):
    """BPE directly on the UTF-8 bytes of the whole text."""

    def train(self, text, vocab_size, verbose=False):
        self._train_chunks([list(text.encode("utf-8"))], vocab_size, verbose)

    def encode(self, text):
        return self._encode_chunk(text.encode("utf-8"))
