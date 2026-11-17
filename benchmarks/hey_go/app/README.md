# hey — HTTP load generator

`hey` sends load to a web application with a configurable number of concurrent workers and prints
latency statistics (summary report) or per-request CSV. Standard library only, Go >= 1.21.

## Build, test, run
```
go build -o hey .
go test ./...
./hey -n 200 -c 50 http://localhost:8080/
./hey -z 10s -q 5 -o csv http://localhost:8080/ > out.csv
```
Run `./hey` with no arguments for the full option list (`-n -c -q -z -o -m -H -t -A -d -D -T -a -x -h2
-host -disable-compression -disable-keepalive -disable-redirects -cpus`). Invalid usage (no URL, n < c,
bad header or `-a` syntax, unknown `-o`) prints the error and usage to stderr and exits 1. Flags may also
follow the URL. The `-m` method string is passed through as given.

## Output
Summary sections: Summary, Response time histogram (11 buckets fastest..slowest; bar scaled to 40 ■),
Latency distribution (10/25/50/75/90/95/99%), Details (DNS+dialup, DNS-lookup, req write, resp wait,
resp read as avg/fastest/slowest), Status code distribution, Error distribution (only on failures).
`-o csv` prints `response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset`
and one row per successful request.

## Design
- `config.go` — flag parsing/validation (`parseArgs`) and request construction (`Config.NewRequest`).
- `worker.go` — `Runner`: c workers; n mode splits n across workers (first n mod c get one extra) so exactly
  n requests run; `-q` uses a per-worker ticker; `-z` runs until the deadline (n ignored) and discards requests
  aborted by the deadline/Ctrl-C. Timings gathered with `net/http/httptrace`.
- `report.go` — summary and CSV rendering. `main.go` — wiring and SIGINT handling (report still printed).

## Definitions / assumptions
- Failed requests are excluded from latency stats, total data, size/request and CSV; they appear in the error distribution.
- Requests/sec = successful responses / total elapsed. Size/request = total bytes / successful responses (integer).
- Histogram bounds: `fastest + i*(slowest-fastest)/10` for i=0..9, last bound = slowest; a latency counts in the first
  bucket whose bound is >= it.
- Percentile = sorted[max(0, len*p/100 - 1)].
- TLS certificates are not verified (load-testing tool). Default User-Agent `hey/0.0.1` (appended if `-H User-Agent` is given).
