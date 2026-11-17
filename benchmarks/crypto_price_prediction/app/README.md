# btcpredict — BTC close-price forecaster (CNN / LSTM / GRU vs. baselines)

Offline, reproducible pipeline that forecasts the next `output_steps` hourly closes from the previous
`input_steps`, and compares deep models with naive baselines. Everything works from `data/btc_1h.csv`
(columns `Date,Symbol,Open,High,Low,Close,VolumeFrom,VolumeTo`, any row order); no network is needed.

## Install
```
pip install -r requirements.txt     # numpy, pandas, matplotlib, keras 3 + TensorFlow, pytest
```

## Use
```
./btcpredict train --model {cnn,lstm,gru,lag,linear} --data data/btc_1h.csv \
    [--input-steps 256] [--output-steps 16] [--stride 16] [--epochs 30] [--seed 0] --out runs/<name>
./btcpredict predict --run runs/<name> --data data/btc_1h.csv --out forecast.csv
./btcpredict compare --runs runs/a runs/b ... --out report.md
```
`train` writes to `--out`: `metrics.json` (model, epochs, input_steps, output_steps, stride, seed, n_train, n_val,
best_epoch, val_mse_scaled, val_mse_usd, val_rmse_usd), `config.json` (metrics + scaler min/max),
`history.csv` (epoch, loss, val_loss), the model (`model.keras` / `model.npz` for linear / `model.json` for lag)
and `val_predictions.png`. `predict` writes `Date,Close` (USD) for the `output_steps` hours after the last candle.
`compare` writes a markdown table sorted by `val_rmse_usd`.

## Test
```
python -m pytest -q
```

## Design / protocol
- `btcpredict_lib/data.py`: load (drop missing, sort chronologically), min-max scaler fitted on the whole series,
  windowing (offsets 0, stride, 2·stride, … while a full window fits), chronological 80 % (floor) / 20 % split.
- `models.py`: Keras CNN (Conv1D 8×20/3 ReLU → Dropout .5 → Conv1D 1×16/4), LSTM(50) → tanh → Dropout .2 → Dense → LeakyReLU,
  GRU(50) → tanh → Dropout .2 → Dense → ReLU; MSE loss, Adam, batch 8. Baselines: `lag` (repeat last `output_steps`
  inputs) and `linear` (per-step OLS with intercept on the input window, train set only).
- `train.py`: the epoch with the lowest validation loss is selected, its weights restored/saved, and metrics
  computed with it. Baselines are not iteratively trained (`best_epoch` = 0). USD metrics invert the scaling.
- Reproducibility: Python/NumPy/Keras seeds plus TensorFlow op determinism; same seed gives identical metrics.

## Assumptions
- For non-default input/output sizes the CNN's second conv kernel/stride is adapted so the output length equals `output_steps`
  (default sizes use exactly kernel 16 / stride 4).
- Forecast timestamps continue at the median spacing of the last candles (hourly for the provided data).
- TensorFlow may print harmless warnings on stderr.
