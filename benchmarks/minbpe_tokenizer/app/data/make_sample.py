"""Deterministically generate data/sample.txt (~185 kB) without network access."""
import os
import random

WORDS = """the of and to in is that it was for on are as with his they at be this from
have or by one had not but what all were when we there can an your which their said if do
will each about how up out them then she many some so these would other into has more her
two like him see time could no make than first been its who now people my made over did down
only way find use may water long little very after words called just where most know
tokenizer byte pair encoding merge vocabulary language model text training unicode""".split()
PUNCT = [".", ".", ".", ",", ";", "!", "?"]
EXTRA = ["café", "naïve", "東京", "你好", "\U0001F600", "1234", "42", "don't", "we'll"]


def main(path=None, size=185_000, seed=1234):
    rng = random.Random(seed)
    out, n = [], 0
    while n < size:
        sent = []
        for i in range(rng.randint(5, 18)):
            w = rng.choice(EXTRA) if rng.random() < 0.03 else rng.choice(WORDS)
            sent.append(w.capitalize() if i == 0 else w)
        s = " ".join(sent) + rng.choice(PUNCT) + ("\n\n" if rng.random() < 0.1 else " ")
        out.append(s)
        n += len(s.encode())
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(out))


if __name__ == "__main__":
    main()
