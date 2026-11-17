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
| [apollo11_agc_assembler](apollo11_agc_assembler/report.md) | [chrislgarry/Apollo-11](https://github.com/chrislgarry/Apollo-11) | not run | – | – | – | – |
| [micrograd_autograd](micrograd_autograd/report.md) | [karpathy/micrograd](https://github.com/karpathy/micrograd) | not run | – | – | – | – |
| [minbpe_tokenizer](minbpe_tokenizer/report.md) | [karpathy/minbpe](https://github.com/karpathy/minbpe) | not run | – | – | – | – |
| [pascal_interpreter](pascal_interpreter/report.md) | [rspivak/lsbasi](https://github.com/rspivak/lsbasi) | not run | – | – | – | – |
| [itsdangerous_signing](itsdangerous_signing/report.md) | [pallets/itsdangerous](https://github.com/pallets/itsdangerous) | not run | – | – | – | – |
| [slugify_js](slugify_js/report.md) | [sindresorhus/slugify](https://github.com/sindresorhus/slugify) | not run | – | – | – | – |
| [jsmn_c](jsmn_c/report.md) | [zserge/jsmn](https://github.com/zserge/jsmn) | not run | – | – | – | – |
| [hexyl_rust](hexyl_rust/report.md) | [sharkdp/hexyl](https://github.com/sharkdp/hexyl) | not run | – | – | – | – |
| [hey_go](hey_go/report.md) | [rakyll/hey](https://github.com/rakyll/hey) | not run | – | – | – | – |
| [realworld_api](realworld_api/report.md) | [gothinkster/realworld](https://github.com/gothinkster/realworld) | not run | – | – | – | – |
| [todomvc_frontend](todomvc_frontend/report.md) | [tastejs/todomvc](https://github.com/tastejs/todomvc) | not run | – | – | – | – |
