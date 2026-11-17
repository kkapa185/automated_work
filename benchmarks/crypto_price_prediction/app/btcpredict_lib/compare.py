"""Markdown comparison table across runs."""
from __future__ import annotations

import json
import os

from . import data as D

COLS = ["val_rmse_usd", "val_mse_usd", "val_mse_scaled"]


def compare(runs, out: str) -> str:
    rows = []
    for r in runs:
        p = os.path.join(r, "metrics.json")
        if not os.path.exists(p):
            raise D.DataError(f"metrics.json not found in run: {r}")
        try:
            with open(p) as f:
                rows.append((r, json.load(f)))
        except json.JSONDecodeError as exc:
            raise D.DataError(f"invalid metrics.json in {r}: {exc}")
    need = {"model", "epochs", "n_train", "n_val", "best_epoch", "val_mse_scaled", "val_mse_usd", "val_rmse_usd"}
    for r, m in rows:
        if not need <= set(m):
            raise D.DataError(f"metrics.json in {r} lacks keys: {sorted(need - set(m))}")
    rows.sort(key=lambda t: t[1]["val_rmse_usd"])
    head = ["run", "model", "epochs", "n_train", "n_val", "best_epoch", "val_mse_scaled", "val_mse_usd", "val_rmse_usd"]
    lines = ["# Model comparison", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r, m in rows:
        lines.append("| " + " | ".join([
            os.path.basename(os.path.normpath(r)), str(m["model"]), str(m["epochs"]), str(m["n_train"]),
            str(m["n_val"]), str(m["best_epoch"]), f"{m['val_mse_scaled']:.6g}",
            f"{m['val_mse_usd']:.2f}", f"{m['val_rmse_usd']:.2f}"]) + " |")
    text = "\n".join(lines) + "\n"
    with open(out, "w") as f:
        f.write(text)
    return text
