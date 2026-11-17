"""Shared tokenizer machinery: BPE training, encoding, decoding, persistence."""
from __future__ import annotations

import unicodedata
from collections import defaultdict

MODEL_VERSION = "minbpe v1"


def get_stats(ids, counts=None):
    """Count adjacent pairs in ``ids`` (optionally accumulating into ``counts``)."""
    counts = {} if counts is None else counts
    for pair in zip(ids, ids[1:]):
        counts[pair] = counts.get(pair, 0) + 1
    return counts


def merge(ids, pair, idx):
    """Replace every non-overlapping (left to right) occurrence of ``pair`` by ``idx``."""
    a, b = pair
    out = []
    i, n = 0, len(ids)
    while i < n:
        if i < n - 1 and ids[i] == a and ids[i + 1] == b:
            out.append(idx)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out


def _first_pos(word, pair):
    a, b = pair
    for i in range(len(word) - 1):
        if word[i] == a and word[i + 1] == b:
            return i
    return -1


def _escape(s):
    """Render a decoded token so control characters are visible."""
    return "".join(
        ch if unicodedata.category(ch)[0] != "C" else f"\\u{ord(ch):04x}" for ch in s
    )


def _render(tok):
    return _escape(tok.decode("utf-8", errors="replace"))


class Tokenizer:
    def __init__(self):
        self.merges = {}          # (int, int) -> int
        self.pattern = ""
        self.special_tokens = {}  # str -> int
        self.vocab = self._build_vocab()

    # ---- vocab -------------------------------------------------------
    def _build_vocab(self):
        vocab = {i: bytes([i]) for i in range(256)}
        for (a, b), idx in self.merges.items():
            vocab[idx] = vocab[a] + vocab[b]
        for tok, idx in self.special_tokens.items():
            vocab[idx] = tok.encode("utf-8")
        return vocab

    # ---- training ----------------------------------------------------
    def _train_chunks(self, chunks, vocab_size, verbose=False):
        """Train on ``chunks`` (list of byte-lists, in data order)."""
        if vocab_size < 256:
            raise ValueError("vocab_size must be >= 256")
        num_merges = vocab_size - 256

        # Deduplicate chunks, keeping first-appearance order.
        index = {}
        words, freqs = [], []
        for c in chunks:
            key = tuple(c)
            j = index.get(key)
            if j is None:
                index[key] = len(words)
                words.append(list(key))
                freqs.append(1)
            else:
                freqs[j] += 1

        counts = defaultdict(int)
        where = defaultdict(set)  # pair -> word indices containing it
        for w, word in enumerate(words):
            for pair in zip(word, word[1:]):
                counts[pair] += freqs[w]
                where[pair].add(w)

        merges = {}
        vocab = {i: bytes([i]) for i in range(256)}
        for step in range(num_merges):
            if not counts:
                break
            best = max(counts.values())
            if best <= 0:
                break
            cands = [p for p, c in counts.items() if c == best]
            if len(cands) == 1:
                pair = cands[0]
            else:  # tie: earliest occurrence in data order
                def first_occ(p):
                    w = min(where[p])
                    return (w, _first_pos(words[w], p))
                pair = min(cands, key=first_occ)
            idx = 256 + step
            merges[pair] = idx
            vocab[idx] = vocab[pair[0]] + vocab[pair[1]]
            for w in list(where[pair]):
                word, f = words[w], freqs[w]
                for p in zip(word, word[1:]):
                    counts[p] -= f
                    if counts[p] <= 0:
                        del counts[p]
                new = merge(word, pair, idx)
                words[w] = new
                for p in zip(new, new[1:]):
                    counts[p] += f
                    where[p].add(w)
                # refresh membership of pairs that vanished from this word
                present = set(zip(new, new[1:]))
                for p in set(zip(word, word[1:])):
                    if p not in present:
                        where[p].discard(w)
            where.pop(pair, None)
            if verbose:
                print(f"merge {step + 1}/{num_merges}: {pair} -> {idx} "
                      f"({vocab[idx]!r}) had {best} occurrences")
        self.merges = merges
        self.vocab = self._build_vocab()

    # ---- encoding / decoding ----------------------------------------
    def _encode_chunk(self, chunk_bytes):
        ids = list(chunk_bytes)
        merges = self.merges
        while len(ids) >= 2:
            best, best_rank = None, None
            for p in zip(ids, ids[1:]):
                r = merges.get(p)
                if r is not None and (best_rank is None or r < best_rank):
                    best, best_rank = p, r
            if best is None:
                break
            ids = merge(ids, best, best_rank)
        return ids

    def decode(self, ids):
        inv_special = {v: k for k, v in self.special_tokens.items()}
        parts = []
        for i in ids:
            if i in self.vocab:
                parts.append(self.vocab[i])
            elif i in inv_special:
                parts.append(inv_special[i].encode("utf-8"))
            else:
                raise ValueError(f"invalid token id: {i}")
        return b"".join(parts).decode("utf-8", errors="replace")

    # ---- persistence -------------------------------------------------
    def save(self, file_prefix):
        with open(file_prefix + ".model", "w", encoding="utf-8") as f:
            f.write(MODEL_VERSION + "\n")
            f.write(f"{self.pattern}\n")
            f.write(f"{len(self.special_tokens)}\n")
            for tok, idx in self.special_tokens.items():
                f.write(f"{tok} {idx}\n")
            for a, b in self.merges:  # insertion order == learning order
                f.write(f"{a} {b}\n")

        inverted = {idx: pair for pair, idx in self.merges.items()}
        with open(file_prefix + ".vocab", "w", encoding="utf-8") as f:
            for idx, tok in sorted(self.vocab.items()):
                if idx in inverted:
                    a, b = inverted[idx]
                    f.write(f"[{_render(self.vocab[a])}][{_render(self.vocab[b])}]"
                            f" -> [{_render(tok)}] {idx}\n")
                else:
                    f.write(f"[{_render(tok)}] {idx}\n")

    def load(self, model_file):
        if not model_file.endswith(".model"):
            raise ValueError("model file must end with .model")
        merges, specials = {}, {}
        with open(model_file, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        if not lines or lines[0] != MODEL_VERSION:
            raise ValueError(f"unsupported model file version (expected {MODEL_VERSION!r})")
        self.pattern = lines[1]
        n_special = int(lines[2])
        pos = 3
        for _ in range(n_special):
            tok, idx = lines[pos].rsplit(" ", 1)
            specials[tok] = int(idx)
            pos += 1
        idx = 256
        for line in lines[pos:]:
            if not line.strip():
                continue
            a, b = map(int, line.split())
            merges[(a, b)] = idx
            idx += 1
        self.merges = merges
        self.special_tokens = specials
        self.vocab = self._build_vocab()
