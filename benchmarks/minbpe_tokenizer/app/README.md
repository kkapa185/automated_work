# minbpe

Byte-level Byte Pair Encoding tokenizers (GPT-2/GPT-4 style) in pure Python.

* `BasicTokenizer()` – BPE on the raw UTF-8 bytes of the text.
* `RegexTokenizer(pattern=None)` – regex pre-split (default GPT-4 pattern, needs `regex`), merges never cross chunks; special tokens via `register_special_tokens`, `encode(text, allowed_special="none_raise"|"all"|"none"|set)`, `encode_ordinary`.
* Common: `train(text, vocab_size, verbose=False)`, `encode`, `decode`, `save(prefix)`, `load(prefix + ".model")`; attributes `merges`, `vocab`, `special_tokens`, `pattern`.

## Install / test / run
```
pip install -r requirements.txt
python -m pytest
python data/make_sample.py     # regenerates data/sample.txt (deterministic, offline)
python train.py [text_file]    # trains both at vocab 512 -> models/{basic,regex}.{model,vocab}, prints time
```

```python
from minbpe import RegexTokenizer
t = RegexTokenizer(); t.train(open("data/sample.txt").read(), 512)
ids = t.encode("hello world"); assert t.decode(ids) == "hello world"
t.save("models/regex"); t.load("models/regex.model")
```

## Design
Training deduplicates chunks (with counts, first-appearance order), keeps pair counts and a pair→chunks index, and updates incrementally after each merge. Ties on frequency go to the pair occurring first in the data (lowest chunk index, then position). Encoding repeatedly merges the eligible pair with the lowest merge index. `decode` uses `errors="replace"`.

Model file: `minbpe v1`, pattern, number of special tokens, `<token> <id>` lines, then `<id1> <id2>` per merge in learning order. A human-readable `.vocab` is written next to it.
Sample data is generated locally; no network is needed.
