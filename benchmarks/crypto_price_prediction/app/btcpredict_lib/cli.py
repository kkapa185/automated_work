"""Command line interface."""
from __future__ import annotations

import argparse
import json
import sys

from .data import DataError
from .models import ALL_MODELS


def build_parser():
    p = argparse.ArgumentParser(prog="btcpredict", description="BTC close-price forecaster")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="train a model or fit a baseline")
    t.add_argument("--model", required=True, choices=ALL_MODELS)
    t.add_argument("--data", required=True)
    t.add_argument("--input-steps", type=int, default=256)
    t.add_argument("--output-steps", type=int, default=16)
    t.add_argument("--stride", type=int, default=16)
    t.add_argument("--epochs", type=int, default=30)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--out", required=True)
    pr = sub.add_parser("predict", help="forecast after the last candle")
    pr.add_argument("--run", required=True)
    pr.add_argument("--data", required=True)
    pr.add_argument("--out", required=True)
    c = sub.add_parser("compare", help="compare runs in a markdown table")
    c.add_argument("--runs", nargs="+", required=True)
    c.add_argument("--out", required=True)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "train":
            from .train import train_run
            m = train_run(args.model, args.data, args.input_steps, args.output_steps, args.stride,
                          args.epochs, args.seed, args.out)
            print(json.dumps(m, indent=2))
        elif args.cmd == "predict":
            from .predict import forecast
            df = forecast(args.run, args.data, args.out)
            print(f"wrote {len(df)} forecast rows to {args.out}")
        else:
            from .compare import compare
            print(compare(args.runs, args.out))
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
