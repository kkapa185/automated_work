"""Train Basic and Regex tokenizers (vocab 512 by default) and save them under models/."""
import argparse
import os
import time

from minbpe import BasicTokenizer, RegexTokenizer

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text_file", nargs="?", default=os.path.join(HERE, "data", "sample.txt"))
    ap.add_argument("--vocab-size", type=int, default=512)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "models"))
    args = ap.parse_args(argv)

    with open(args.text_file, "r", encoding="utf-8") as f:
        text = f.read()
    os.makedirs(args.out_dir, exist_ok=True)
    for name, cls in (("basic", BasicTokenizer), ("regex", RegexTokenizer)):
        tok = cls()
        t0 = time.time()
        tok.train(text, args.vocab_size)
        dt = time.time() - t0
        tok.save(os.path.join(args.out_dir, name))
        print(f"{name}: trained vocab_size={args.vocab_size} in {dt:.2f}s "
              f"-> {os.path.join(args.out_dir, name)}.model")


if __name__ == "__main__":
    main()
