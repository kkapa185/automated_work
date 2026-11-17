# Benchmarks: real GitHub projects rebuilt from a ticket

Each benchmark directory holds:
* `task.md`: the ticket the orchestrator receives. It describes *what* to build, never the reference code.
* `prepare.py` (optional): copies input data that a real user would hand over (datasets, source to assemble, API spec).
* `compare.py`: the hidden acceptance harness. It runs the **reference project** and the **generated
  application** on the same inputs and scores agreement. The orchestrator never sees it.
* `app/`: the final generated application (no dependencies, build output or input data).
* `report.md`: the analysis, plus any system changes the benchmark triggered.

Run with `python benchmarks/runner.py run [--only NAME]`; it is resumable and survives usage-limit pauses.
`python benchmarks/summarize.py` regenerates this table.

| benchmark | reference | status | score history | checks passed (last) | turns | cost |
|---|---|---|---|---|---|---|
| [crypto_price_prediction](crypto_price_prediction/report.md) | [khuangaf/CryptocurrencyPrediction](https://github.com/khuangaf/CryptocurrencyPrediction) | COMPLETED | 1.00 | 20/20 | 4 | $1.43 |
| [matlab_challenge_explorer](matlab_challenge_explorer/report.md) | [mathworks/MATLAB-Simulink-Challenge-Project-Hub](https://github.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub) | COMPLETED | 0.95 | 21/22 | 4 | $4.74 |
| [apollo11_agc_assembler](apollo11_agc_assembler/report.md) | [chrislgarry/Apollo-11](https://github.com/chrislgarry/Apollo-11) | COMPLETED | 0.98 | 6/8 | 4 | $33.29 |
| [micrograd_autograd](micrograd_autograd/report.md) | [karpathy/micrograd](https://github.com/karpathy/micrograd) | not run | – | – | – | – |
| [minbpe_tokenizer](minbpe_tokenizer/report.md) | [karpathy/minbpe](https://github.com/karpathy/minbpe) | COMPLETED | 1.00 | 16/16 | 4 | $1.07 |
| [pascal_interpreter](pascal_interpreter/report.md) | [rspivak/lsbasi](https://github.com/rspivak/lsbasi) | COMPLETED | 0.74 → 0.85 → 1.00 | 40/40 | 3 | $1.12 |
| [itsdangerous_signing](itsdangerous_signing/report.md) | [pallets/itsdangerous](https://github.com/pallets/itsdangerous) | COMPLETED | 0.96 → 0.71 → 1.00 | 52/52 | 4 | $2.09 |
| [slugify_js](slugify_js/report.md) | [sindresorhus/slugify](https://github.com/sindresorhus/slugify) | COMPLETED | 0.55 → 0.61 | 54/89 | 3 | $1.36 |
| [jsmn_c](jsmn_c/report.md) | [zserge/jsmn](https://github.com/zserge/jsmn) | COMPLETED | 0.64 | 7/11 | 4 | $2.92 |
| [hexyl_rust](hexyl_rust/report.md) | [sharkdp/hexyl](https://github.com/sharkdp/hexyl) | COMPLETED | 0.29 | 9/31 | 5 | $2.78 |
| [hey_go](hey_go/report.md) | [rakyll/hey](https://github.com/rakyll/hey) | not run | – | – | – | – |
| [realworld_api](realworld_api/report.md) | [gothinkster/realworld](https://github.com/gothinkster/realworld) | not run | – | – | – | – |
| [todomvc_frontend](todomvc_frontend/report.md) | [tastejs/todomvc](https://github.com/tastejs/todomvc) | not run | – | – | – | – |
