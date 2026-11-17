# QUANT-311 requirements

## Product
An offline, reproducible Python (Keras 3 / TensorFlow 2.21 backend, numpy, pandas, matplotlib) data/ML CLI, `./btcpredict`,
that loads hourly BTC-USD candles from CSV, builds windowed supervised samples from the min-max scaled `Close`
series, trains CNN / LSTM / GRU models and `lag` / `linear` baselines, reports validation metrics in scaled and USD
units, forecasts beyond the last candle, and compares runs in a markdown table.

## Acceptance criteria
R1. `./btcpredict` executable at workspace root with subcommands `train`, `predict`, `compare`; `--help` works; bad args exit non-zero with message.
R2. Loading: read `Date,Symbol,Open,High,Low,Close,...`; parse Date; drop rows with missing Date/Close (or non-numeric Close); sort chronologically (ascending) regardless of file order; missing columns -> clear error.
R3. Scaling: min-max to [0,1] fitted on entire Close series; constant series handled (no division by zero -> zeros); inverse transform exact round-trip.
R4. Windowing: sample i has input = scaled[o:o+I], target = scaled[o+I:o+I+O], o = i*stride, for all o with o+I+O <= N. Shapes X (n,I,1), y (n,O). Too-short series -> clear error. Invalid params (<=0) -> error.
R5. Split: n_train = floor(0.8*n), chronological; rest validation. Need n_train>=1 and n_val>=1 else clear error.
R6. Models (loss MSE, Adam, batch 8, single feature channel):
    cnn: Conv1D(8,k20,s3,relu)->Dropout(.5)->Conv1D(1,k16,s4) -> output (O,); for non-default I/O the 2nd conv kernel is adapted so output length == O (default config exactly as spec).
    lstm: LSTM(50)->tanh->Dropout(.2)->Dense(O)->LeakyReLU.
    gru: GRU(50)->tanh->Dropout(.2)->Dense(O)->ReLU.
    Output shape (batch, O) for each.
R7. lag baseline: prediction = last O input values (requires O<=I; else error). linear baseline: OLS (with intercept) per output step on raw (scaled) input window, fit on train only, via least squares (min-norm if underdetermined).
R8. Training runs `--epochs` epochs, per-epoch train/val loss recorded; metrics from epoch with lowest val loss (first on ties); the best weights are restored and saved. Baselines: best_epoch=0, no training.
R9. Metrics: val_mse_scaled; val_mse_usd and val_rmse_usd after inverse scaling (mse_usd = mse_scaled*(max-min)^2); n_train, n_val, best_epoch; plus model, epochs, input_steps, output_steps, stride (and seed) in `<out>/metrics.json`.
R10. `train` outputs in `--out`: metrics.json, model (`model.keras` for NN; `model.npz` for linear; `model.json` for lag), `history.csv` (epoch,loss,val_loss; baselines one row epoch 0 with val_loss), `val_predictions.png` (validation predictions vs ground truth), run config incl. scaler min/max (stored in `config.json`).
R11. Reproducibility: same seed + data + args -> identical metrics.json values (seeds python/numpy/TF, deterministic ops enabled).
R12. `predict --run --data --out forecast.csv`: loads run, takes last input_steps closes (using stored scaler), forecasts next output_steps values in USD; CSV columns `Date,Close` with timestamps continuing at the data's hourly step after the last candle; errors if data shorter than input_steps.
R13. `compare --runs ... --out report.md`: markdown table, one row per run (run name, model, epochs, n_train, n_val, best_epoch, val_mse_scaled, val_mse_usd, val_rmse_usd) sorted by val_rmse_usd ascending; missing/invalid run dir -> clear error.
R14. Defaults: input-steps 256, output-steps 16, stride 16, epochs 30, seed 0.
R15. Tests (pytest) for R2–R14; README documents install/run/test/design; requirements.txt pins deps; works offline.

## Assumptions
- Keras 3 with TensorFlow backend is installed (torch absent); `Sort` is stable; duplicate timestamps are kept.
- "raw input window" for linear = scaled input window values (no engineered features), with intercept.
- Val loss computed in inference mode (dropout off) over the full validation set; val_mse_scaled = that loss at best epoch.
- Forecast timestamps step = median spacing of last timestamps (fallback 1h).
- Baselines record `epochs` as given but do not train.

## Test strategy
Unit: data loading/scaling/windowing/split (R2–R5), baselines on synthetic series (R7), model shapes (R6), metrics math (R9). Integration: CLI end-to-end on small synthetic CSV for each model with 2 epochs, predict, compare, reproducibility (R1,R8,R10–R13). Manual run on the real data file.
