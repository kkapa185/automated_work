# Requirements: `hey` HTTP load generator (Go)

## Product
`hey` is a Go (>=1.21, stdlib-only module) CLI that sends a configurable amount of HTTP load to a single URL using concurrent workers, records per-request timing (DNS, dial, request write, response wait, response read), and prints either a human-readable summary report or per-request CSV. Built with `go build -o hey .` from repo root.

## Acceptance criteria
R1. Flags: -n (200), -c (50), -q (0 = no limit, per worker), -z (duration; if >0 n ignored), -o ("" or "csv"), -m (default GET; any string passed through as given), -H (repeatable "Name: value"), -t (seconds, default 20, 0 = infinite), -A, -d, -D (body from file), -T (default "text/html"), -a (user:pass basic auth), -x (proxy host:port), -h2, -host, -disable-compression, -disable-keepalive, -disable-redirects, -cpus.
R2. Exactly one positional URL required; missing URL -> usage on stderr, exit 1. Flags may appear before the URL (Go flag semantics); flags after the URL are also accepted (re-parse remaining args).
R3. When -z not set: n < c -> error + usage to stderr, exit 1. n and c must be positive (n<=0/c<=0 invalid, exit 1). When -z set, the n>=c check is skipped.
R4. Bad header syntax (no `Name: value` form via regex `^([\w-]+):\s*(.+)`) -> error to stderr, exit 1.
R5. Basic auth -a "user:pass" must have a colon, else exit 1; sets Authorization Basic. -a overrides unless URL has userinfo (URL userinfo also used if -a absent).
R6. Request building: method as given; headers; Content-Type = -T (default text/html) always set unless -H overrides Content-Type; -A sets Accept; -host sets Host header (req.Host); body from -d, or -D file contents (file read error -> exit 1); User-Agent default "hey/0.0.1" appended to custom UA if provided in -H (default "hey/0.0.1" if none).
R7. Scheduler (n mode): exactly n requests are issued in total, split across c workers (n/c each; remainder distributed so total is exactly n). No more, no fewer.
R8. QPS throttling: with -q Q, each worker issues at most Q requests/sec (ticker at 1s/Q interval before each request). Total rate bounded by Q*c.
R9. Duration mode: -z D runs workers until D elapses (then stops; in-flight requests finish or are cancelled), n ignored; each worker loops requesting continuously.
R10. Ctrl-C/SIGINT stops early and still prints the report for completed requests.
R11. Transport: -disable-keepalive, -disable-compression, -disable-redirects (return ErrUseLastResponse so 3xx recorded), -x proxy, -h2 (ForceAttemptHTTP2 / TLS), -t per-request timeout (0 = none), -cpus -> GOMAXPROCS (default NumCPU). TLS verification skipped (InsecureSkipVerify) like a load tool.
R12. Per-request result: duration, status code, error, content length (body bytes read), DNS+dialup, DNS lookup, request write, response delay, response read, offset since start. Timings via httptrace. Body is fully read/discarded and counted.
R13. Summary output exactly in the section order/format of the ticket. Formats: `Summary:`; `  Total:\t%4.4f secs`; Slowest, Fastest, Average (same format); `  Requests/sec:\t%4.4f`; line `  ` (two spaces) ; `  Total data:\t%d bytes`; `  Size/request:\t%d bytes` (integer division total/len(successful responses); only printed when there are successful responses). Blank line between sections.
R14. Total = elapsed wall time of the run. Average = mean latency of successful requests; Requests/sec = successful count / total. Fastest/Slowest = min/max of successful latencies. Failed requests excluded from latencies/size.
R15. Histogram: 11 buckets spanning fastest..slowest: bucket width (slowest-fastest)/10, bucket i (0..9) upper bound = fastest + width*i... Concretely: buckets[i]=min+i*width for i=0..9 and buckets[10]=slowest; line "  %4.3f [%v]\t|%s"; a latency goes in the first bucket whose bound is >= it... Implemented as: for each latency find bucket index i such that lat <= buckets[i] (first match), counts[i]++ ; (the last bucket captures slowest). Bar = '■' repeated count*40/maxCount (integer division; max bucket => 40).
R16. Latency distribution: percentiles 10,25,50,75,90,95,99 on sorted latencies, index = len*p/100 clamped to len-1 (for p=99 index = len*99/100; if index>=len use len-1... standard: data[int(len*p/100)-1] floored at 0). Line format `  %v%% in %4.4f secs`. Only printed if there are latencies.
R17. Details section: "Details (average, fastest, slowest):" with lines `  DNS+dialup:\t%4.4f secs, %4.4f secs, %4.4f secs` (avg, min, max) for DNS+dialup, DNS-lookup, req write, resp wait, resp read.
R18. Status code distribution: `  [%d]\t%d responses`, sorted by code ascending. Error distribution (only if errors): `  [%d]\t%s` sorted by count descending, then message; message is the error string.
R19. CSV: header `response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset`; row per successful request: 4-decimal seconds for the six timings, integer status, offset 4 decimals. No summary printed. Errors omitted from CSV rows (they have no status).
R20. Output goes to stdout; usage/errors to stderr, exit 1. Normal completion exit 0.
R21. Unit tests for: arg parsing (flags, defaults, errors, repeatable -H, n<c), scheduler (exact count for n/c incl. non-divisible, QPS throttling timing, duration mode, cancellation), report (summary formatting with known numeric vectors computed by hand, histogram, percentiles, csv, error distribution), request construction, and an end-to-end test against httptest server.
R22. README with description, build/run/test, options, design.

## Assumptions
- Spec says "-o csv" only; any other -o value is an error (exit 1) — assumption: invalid output type exits 1.
- Latency "Average" excludes errors. Empty results (all errors) print Summary with zero values and Error distribution without histogram/latency sections.
- Percentile index: idx = int(p*len/100) - 1, min 0 (nearest-rank-ish floor); documented and tested with hand-computed vectors.
- Duration mode with -n ignored, c still applies.
- Flags after the URL are accepted.
- Remainder distribution: first (n mod c) workers get one extra request.

## Test strategy
- `config_test.go` (R1-R6): parse args via a pure `parseArgs(args) (*Config, error)`.
- `work_test.go` (R7-R9, R11-R12): scheduler with a stub request function plus httptest-based runs.
- `report_test.go` (R13-R19): hand-computed fixtures.
- `main_test.go`: build the binary and run end-to-end against httptest-like server for exit codes and output sections (R2, R3, R20).

## Plan
Files: go.mod, main.go (flags, run, signal), config.go (parseArgs, request build), worker.go (Runner: scheduler + http client + httptrace), report.go (summary/csv), tests, README.md. Data flow: parseArgs -> Config -> Runner.Run(ctx) -> results chan -> report.Print. Risks: exact-count under cancellation, QPS timing flakiness (use generous margins), histogram bucket exactness (hand-computed tests).
