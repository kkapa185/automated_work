# QUANT-311: Deep-learning Bitcoin price forecaster (CNN / LSTM / GRU) with baselines

## Context
Research wants a reproducible pipeline that forecasts the next part of the Bitcoin close-price curve from
its recent history, and compares deep models against naive baselines. A historical hourly BTC-USD candle
file is provided at `data/btc_1h.csv` (columns `Date,Symbol,Open,High,Low,Close,VolumeFrom,VolumeTo`, rows
NOT guaranteed to be in chronological order). External market APIs are not reachable from the build
environment, so everything must work offline from this file.

## Modelling protocol (must be followed exactly so results are comparable across experiments)
1. Use the `Close` series in chronological order. Drop rows with missing values.
2. Scale the series to [0, 1] with min-max scaling fitted on the **entire** series.
3. Supervised samples: each sample is `input_steps` consecutive scaled values (default 256) followed by the
   next `output_steps` values (default 16) as the target. Sample start offsets are `0, stride, 2*stride, ...`
   (default stride 16) for as long as a full window fits.
4. Split samples chronologically: the first 80% (floor) are training, the rest validation.
5. Models (single feature channel; loss = MSE on the scaled values; Adam optimiser; batch size 8):
   * `cnn`: 1-D CNN — Conv1D(8 filters, kernel 20, stride 3, ReLU) → Dropout(0.5) → Conv1D(1 filter,
     kernel 16, stride 4) producing the `output_steps` values.
   * `lstm`: LSTM(50 units) → tanh → Dropout(0.2) → Dense(output_steps) → LeakyReLU.
   * `gru`: GRU(50 units) → tanh → Dropout(0.2) → Dense(output_steps) → ReLU.
   * `lag` baseline: predict that the next `output_steps` values equal the last `output_steps` input values.
   * `linear` baseline: one ordinary-least-squares linear regression per output step on the raw input window.
6. Train for `--epochs` epochs; report the metrics of the epoch with the lowest validation loss.
7. Metrics on the validation set: `val_mse_scaled` (MSE in scaled units) and, after inverting the scaling
   back to USD, `val_mse_usd` and `val_rmse_usd`. Also `n_train`, `n_val`, `best_epoch`.

## Deliverables
A command-line tool runnable from the workspace root:
```
./btcpredict train --model {cnn,lstm,gru,lag,linear} --data data/btc_1h.csv \
    [--input-steps 256] [--output-steps 16] [--stride 16] [--epochs 30] [--seed 0] --out runs/<name>
./btcpredict predict --run runs/<name> --data data/btc_1h.csv --out forecast.csv   # forecast after the last candle
./btcpredict compare --runs runs/a runs/b ... --out report.md                        # results table
```
`train` writes `<out>/metrics.json` (keys above plus `model`, `epochs`, `input_steps`, `output_steps`,
`stride`), the trained model, a per-epoch history CSV, and a PNG plot of validation predictions vs ground
truth. Seeds must make runs reproducible. Include automated tests (windowing/scaling/split correctness,
baselines on synthetic series, model shapes, CLI end-to-end on a small synthetic file) and a README.
