# Benchmark report — khuangaf/CryptocurrencyPrediction

**Ticket:** [`task.md`](task.md) (QUANT-311). The system saw only the ticket and an offline hourly BTC-USD
dataset. Poloniex, the repo's data source, is not reachable from the sandbox.

**Reference execution:** [`reference_run.py`](reference_run.py) runs the repository's own `PastSampler` and
ports its CNN/LSTM/GRU definitions, MinMax-on-whole-series scaling, 80/20 split, batch 8, best-val-epoch
reporting, lag baseline and per-step linear regression to tf.keras 3. Both pipelines ran with 20 epochs,
seed 0, windows of 256→16 and stride 16.

## Result (attempt 1, system `d8b43d5`): score 1.00 (20/20)
| model | generated val RMSE (USD) | reference val RMSE (USD) | best epoch (gen / ref) |
|---|---|---|---|
| lag baseline | 270.7 | 270.7 | – |
| linear regression | 226.4 | 226.4 | – |
| CNN (2 layers) | 760.6 | 760.6 | 17 / 17 |
| LSTM (50, tanh, LeakyReLU) | 219.3 | 219.3 | 17 / 17 |
| GRU (50, tanh, ReLU) | 195.2 | 195.2 | 14 / 14 |

The generated pipeline reproduces the reference results to 6+ significant digits: same windows, split,
scaling and seeded training. The ranking matches the original README: recurrent models beat the baselines,
and the 2-layer CNN is worst. `predict` (16-step forecast after the last candle), `compare` (a markdown
table of the results) and the validation plots work.

**Process:** 4 turns on one session (`0c95828e…`): plan → implement → review (GAPS_FIXED) → review
(PASS). $0.47 (corrected: the CLI reports cumulative session cost), 21.5 min wall time. Most of that time went to the system's own verification contract,
which trains real models in its smoke runs.

**System observations:** no failures to fix. This run validated the requirements/verify-contract design:
Claude declared setup + pytest + compile + 4 real CLI smoke runs, and the review turn found and fixed
gaps before completion.
