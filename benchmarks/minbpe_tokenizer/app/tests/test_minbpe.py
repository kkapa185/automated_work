import os
import random
import subprocess
import sys
import time

import pytest

from minbpe import BasicTokenizer, RegexTokenizer, GPT4_SPLIT_PATTERN
from minbpe.base import merge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEXTS = [
    "", "a", "hello world", "aaabdaaabac", "  leading and trailing  \n\n",
    "emoji 😀🎉 and CJK 東京你好 and café", "ctrl \x00\x01\x1f\x7f\t\r\n end",
    "I'm sure we'll've seen it. 12345 numbers!!!", "​﻿ zero width",
]
BOTH = [BasicTokenizer, RegexTokenizer]


def reference_train(chunks, n_merges):
    """Brute-force trainer: full recount each step, tie -> first occurrence."""
    chunks = [list(c) for c in chunks]
    merges = {}
    for step in range(n_merges):
        counts = {}
        for c in chunks:
            for p in zip(c, c[1:]):
                counts[p] = counts.get(p, 0) + 1
        if not counts:
            break
        best = max(counts.values())
        pair = next(p for p, v in counts.items() if v == best)  # insertion = first seen
        merges[pair] = 256 + step
        chunks = [merge(c, pair, 256 + step) for c in chunks]
    return merges


def rand_text(rng, n):
    alphabet = "abcab ab,.\n\n12 é東😀"
    return "".join(rng.choice(alphabet) for _ in range(n))


# R1
@pytest.mark.parametrize("cls", BOTH)
def test_r1_initial_state(cls):
    t = cls()
    assert t.merges == {} and len(t.vocab) == 256
    assert t.vocab[65] == b"A" and t.special_tokens == {}
    assert BasicTokenizer().pattern == "" and RegexTokenizer().pattern == GPT4_SPLIT_PATTERN


# R2
@pytest.mark.parametrize("cls", BOTH)
def test_r2_train_sizes(cls):
    t = cls()
    with pytest.raises(ValueError):
        t.train("abc", 255)
    t.train("abc", 256)
    assert t.merges == {}
    t.train("aaabdaaabac " * 5, 260)
    assert len(t.merges) == 4 and sorted(t.merges.values()) == [256, 257, 258, 259]
    t.train("", 300)  # nothing to merge: stops without error
    assert t.merges == {}
    t.train("a", 300)
    assert t.merges == {}


# R3/R4
def test_r3_known_example_and_ties():
    t = BasicTokenizer()
    t.train("aaabdaaabac", 259)
    a, b, d = ord("a"), ord("b"), ord("d")
    assert t.merges == {(a, a): 256, (256, a): 257, (257, b): 258}
    assert t.vocab[258] == b"aaab"
    assert t.encode("aaabdaaabac") == [258, d, 258, ord("a"), ord("c")]
    # tie: "ab" and "cd" both occur once; ab occurs first
    t = BasicTokenizer()
    t.train("xabycd", 257)
    assert t.merges == {(ord("x"), ord("a")): 256}
    t = BasicTokenizer()
    t.train("cdab" "abcd", 257)  # cd:2 ab:2 ; cd first
    assert t.merges == {(ord("c"), ord("d")): 256}


def test_r3_counts_across_chunks_and_tie_order():
    t = RegexTokenizer()
    t.train("ab ab ab", 257)  # chunks "ab"," ab"," ab"; (a,b) count 3
    assert t.merges == {(97, 98): 256}


@pytest.mark.parametrize("seed", range(8))
def test_r3_matches_bruteforce_reference(seed):
    rng = random.Random(seed)
    text = rand_text(rng, 400)
    t = BasicTokenizer()
    t.train(text, 300)
    assert t.merges == reference_train([text.encode()], 44)
    r = RegexTokenizer()
    r.train(text, 300)
    chunks = [c.encode() for c in r.compiled_pattern.findall(text)]
    assert r.merges == reference_train(chunks, 44)
    for (a, b), idx in r.merges.items():
        assert r.vocab[idx] == r.vocab[a] + r.vocab[b]  # R4


# R5
def test_r5_encode_uses_lowest_merge_index():
    t = BasicTokenizer()
    t.merges = {(98, 99): 256, (97, 98): 257}  # bc learned first
    t.vocab = t._build_vocab()
    assert t.encode("abc") == [97, 256]
    assert t.encode("") == [] and t.encode("a") == [97]


# R6
def test_r6_decode():
    t = BasicTokenizer()
    assert t.decode([0xff]) == "�"
    assert t.decode([]) == ""
    with pytest.raises(ValueError):
        t.decode([999])


# R7
@pytest.mark.parametrize("cls", BOTH)
@pytest.mark.parametrize("text", TEXTS)
def test_r7_roundtrip(cls, text):
    t = cls()
    t.train("hello world, aaabdaaabac 東京 😀 café\n\n" * 3, 300)
    assert t.decode(t.encode(text)) == text
    untrained = cls()
    assert untrained.decode(untrained.encode(text)) == text


@pytest.mark.parametrize("cls", BOTH)
def test_r7_fuzz(cls):
    rng = random.Random(7)
    t = cls()
    t.train(rand_text(rng, 2000), 320)
    for _ in range(30):
        s = "".join(chr(rng.choice([rng.randint(0, 0x2FF), rng.randint(0x4E00, 0x4F00),
                                     rng.randint(0x1F600, 0x1F64F)]))
                    for _ in range(rng.randint(0, 40)))
        assert t.decode(t.encode(s)) == s


# R8
def test_r8_chunk_boundaries_and_custom_pattern():
    t = RegexTokenizer()
    t.train("a b a b a b" * 10, 270)
    for (a, b) in t.merges:  # no token contains a space plus another word
        assert t.vocab[256 + list(t.merges).index((a, b))].count(b" ") <= 1
    ids = t.encode("ab ab")
    assert t.decode(ids) == "ab ab"
    c = RegexTokenizer(pattern=r"\d+|\D+")
    c.train("12 34 12 34", 258)
    assert c.pattern == r"\d+|\D+"
    assert c.decode(c.encode("12 34")) == "12 34"
    # merges never cross chunks: "a" "b" separate chunks under pattern "a|b"
    d = RegexTokenizer(pattern="a|b")
    d.train("abababab", 260)
    assert d.merges == {}


# R9
def test_r9_special_tokens():
    t = RegexTokenizer()
    t.train("hello world " * 20, 270)
    sp = {"<|endoftext|>": 1000, "<|pad|>": 1001}
    t.register_special_tokens(sp)
    text = "hello<|endoftext|> world"
    with pytest.raises(ValueError):
        t.encode(text)
    ids = t.encode(text, allowed_special="all")
    assert 1000 in ids and t.decode(ids) == text
    plain = t.encode(text, allowed_special="none")
    assert 1000 not in plain and t.decode(plain) == text
    assert t.encode(text, allowed_special={"<|endoftext|>"}) == ids
    assert 1001 not in t.encode("<|pad|>", allowed_special={"<|endoftext|>"})
    assert t.encode_ordinary(text) == plain
    with pytest.raises(ValueError):
        t.encode(text, allowed_special={"<|nope|>"})
    assert t.encode("no specials here") == t.encode_ordinary("no specials here")
    assert t.encode("<|endoftext|>", allowed_special="all") == [1000]


# R10/R11
@pytest.mark.parametrize("cls", BOTH)
def test_r10_r11_save_load(cls, tmp_path):
    t = cls()
    t.train("hello world 東京 😀 \x01 hello world\n" * 5, 290)
    if cls is RegexTokenizer:
        t.register_special_tokens({"<|endoftext|>": 290})
    prefix = str(tmp_path / "m")
    t.save(prefix)
    lines = open(prefix + ".model", encoding="utf-8").read().split("\n")
    assert lines[0] == "minbpe v1"
    assert lines[1] == t.pattern
    nsp = int(lines[2])
    assert nsp == len(t.special_tokens)
    merge_lines = [l for l in lines[3 + nsp:] if l]
    assert [tuple(map(int, l.split())) for l in merge_lines] == list(t.merges)
    if nsp:
        assert lines[3] == "<|endoftext|> 290"
    vocab_txt = open(prefix + ".vocab", encoding="utf-8").read()
    assert len(vocab_txt.strip().split("\n")) == len(t.vocab)
    assert "->" in vocab_txt
    t2 = cls()
    t2.load(prefix + ".model")
    assert t2.merges == t.merges and t2.vocab == t.vocab
    assert t2.special_tokens == t.special_tokens and t2.pattern == t.pattern
    s = "hello 東京 😀 world"
    assert t2.encode(s) == t.encode(s)
    if cls is RegexTokenizer:
        assert t2.encode("a<|endoftext|>", allowed_special="all")[-1] == 290


def test_load_errors(tmp_path):
    with pytest.raises(ValueError):
        BasicTokenizer().load(str(tmp_path / "x.txt"))
    p = tmp_path / "bad.model"
    p.write_text("minbpe v2\n\n0\n")
    with pytest.raises(ValueError):
        BasicTokenizer().load(str(p))


# R12
def test_r12_train_script(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("the quick brown fox jumps over the lazy dog. " * 50, encoding="utf-8")
    out = tmp_path / "models"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "train.py"), str(src),
                        "--out-dir", str(out), "--vocab-size", "300"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert "in " in r.stdout and "s" in r.stdout
    for n in ("basic", "regex"):
        assert (out / f"{n}.model").exists() and (out / f"{n}.vocab").exists()
    t = RegexTokenizer()
    t.load(str(out / "regex.model"))
    assert 256 < len(t.vocab) <= 300  # stops early if no pairs remain


# R13
def test_r13_speed_regex_on_sample():
    with open(os.path.join(ROOT, "data", "sample.txt"), encoding="utf-8") as f:
        text = f.read()
    t0 = time.time()
    t = RegexTokenizer()
    t.train(text, 512)
    assert time.time() - t0 < 30
    assert len(t.merges) == 256
    assert t.decode(t.encode(text[:5000])) == text[:5000]


# R2 (verbose) / R7 on trained shipped sample
def test_r2_verbose_prints_each_merge(capsys):
    t = BasicTokenizer()
    t.train("aaabdaaabac" * 3, 259, verbose=True)
    out = capsys.readouterr().out
    assert out.count("merge ") == 3


def test_r7_roundtrip_sample_regex_and_basic():
    text = open(os.path.join(ROOT, "data", "sample.txt"), encoding="utf-8").read()[:20000]
    for cls in BOTH:
        t = cls()
        t.train(text, 300)
        assert t.decode(t.encode(text)) == text
