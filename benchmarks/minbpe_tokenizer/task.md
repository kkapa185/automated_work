# NLP-48: Byte-level BPE tokenizer library (`minbpe` API)

Build a Python package `minbpe` implementing byte-level Byte Pair Encoding (as used by GPT-2/GPT-4
tokenizers), with an API compatible with the popular `minbpe` teaching library:

* `BasicTokenizer()` — BPE directly on the UTF-8 bytes of the text.
* `RegexTokenizer(pattern=None)` — first splits text into chunks with a regex split pattern (default: the
  GPT-4 pattern `'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+`,
  requiring the third-party `regex` module); merges never cross chunk boundaries.
  `register_special_tokens(dict[str, int])`; `encode(text, allowed_special="none_raise"|"all"|"none"|set)`;
  `encode_ordinary(text)`.
* Common API: `train(text, vocab_size, verbose=False)` (vocab_size >= 256; performs `vocab_size-256`
  merges; at each step merge the most frequent adjacent pair — counted over all chunks — and on ties choose
  the pair that occurs first when scanning the training data in order; new token ids are 256, 257, ...),
  `encode(text) -> list[int]` (greedily apply merges in the order they were learned, i.e. always merge the
  eligible pair with the lowest merge index first), `decode(ids) -> str` (UTF-8 with `errors="replace"`),
  attributes `merges: dict[tuple[int,int], int]`, `vocab: dict[int, bytes]`, `special_tokens`, `pattern`.
* `save(file_prefix)` writes `<prefix>.model`:
  line 1 `minbpe v1`, line 2 the pattern (empty for Basic), line 3 number of special tokens, then one line
  `<token> <id>` per special token, then one line `<id1> <id2>` per merge in learning order; and a
  human-readable `<prefix>.vocab`. `load(model_file)` restores a tokenizer from `.model`.
* A `train.py` script training both tokenizers on a text file with vocab size 512 and saving them under `models/`,
  printing the training time.

Requirements: `decode(encode(x)) == x` for any Unicode text (including emoji, CJK, control characters);
reasonable training speed (vocab 512 on ~185 kB of text in well under a minute); tests for all of the above.
