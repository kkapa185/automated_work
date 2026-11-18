"""Command-line interface: prepare / train / sample."""
import argparse
import sys

from .data import DataError, prepare
from .train import train


def build_parser():
    p = argparse.ArgumentParser(prog="nanogpt", description="Character-level GPT pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("prepare", help="tokenise a text file at character level")
    sp.add_argument("--input", required=True)
    sp.add_argument("--out", required=True)

    tp = sub.add_parser("train", help="train a GPT model")
    tp.add_argument("--data", required=True)
    tp.add_argument("--out", required=True)
    for name, typ in [("n-layer", int), ("n-head", int), ("n-embd", int), ("block-size", int),
                      ("batch-size", int), ("max-iters", int), ("eval-interval", int), ("eval-iters", int),
                      ("learning-rate", float), ("min-lr", float), ("warmup-iters", int),
                      ("lr-decay-iters", int), ("dropout", float), ("weight-decay", float),
                      ("beta1", float), ("beta2", float), ("grad-clip", float), ("seed", int),
                      ("device", str)]:
        tp.add_argument("--" + name, type=typ, default=None)
    tp.add_argument("--resume", action="store_true", help="continue from <out>/ckpt.pt")

    gp = sub.add_parser("sample", help="sample text from a trained model")
    gp.add_argument("--out", required=True)
    gp.add_argument("--start", default="\n")
    gp.add_argument("--num-samples", type=int, default=1)
    gp.add_argument("--max-new-tokens", type=int, default=500)
    gp.add_argument("--temperature", type=float, default=0.8)
    gp.add_argument("--top-k", type=int, default=None)
    gp.add_argument("--seed", type=int, default=1337)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            v, tr, va = prepare(args.input, args.out)
            print(f"vocab size: {v:,}")
            print(f"train has {tr:,} tokens")
            print(f"val has {va:,} tokens")
        elif args.command == "train":
            keys = ["n_layer", "n_head", "n_embd", "block_size", "batch_size", "max_iters", "eval_interval",
                    "eval_iters", "learning_rate", "min_lr", "warmup_iters", "lr_decay_iters", "dropout",
                    "weight_decay", "beta1", "beta2", "grad_clip", "seed", "device"]
            train(args.data, args.out, {k: getattr(args, k) for k in keys}, resume=args.resume,
                  log=lambda s: print(s, flush=True))
        else:
            from .sample import SEPARATOR, sample
            if args.num_samples < 1 or args.max_new_tokens < 0 or (args.top_k is not None and args.top_k < 1):
                raise DataError("invalid sampling options")
            outs = sample(args.out, args.start, args.num_samples, args.max_new_tokens, args.temperature,
                          args.top_k, args.seed)
            print(("\n" + SEPARATOR + "\n").join(outs))
    except (DataError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0
