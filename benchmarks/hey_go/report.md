# Benchmark report — rakyll/hey

**Ticket:** [`task.md`](task.md) (PERF-17). It asks for an HTTP load generator CLI in Go with the summary and
CSV report formats.

**Reference execution:** the hidden harness [`compare.py`](compare.py) builds the reference and the generated
`hey`, then runs both against an instrumented local HTTP server through 8 scenarios: default summary,
custom method/headers/body, basic auth + Host, HEAD, 500 errors, disabled keep-alive, and redirects
followed or disabled. It compares:
- the requests the server actually received: counts, methods, paths, bodies, headers;
- TCP connection counts;
- report sections, status-code distribution, data totals and CSV structure.

It also measures `-q` rate limiting and `-z` duration mode, and checks usage edge cases against the reference.

## Result (attempt 1): score 0.96 (65/68)
The three differences are reference quirks:
1. For `HEAD`, the reference counts the `Content-Length` header as "data" (123 bytes/response) although no
   body is read. The generated tool reports 0, which matches the ticket's "sum of response body sizes".
2. When no request succeeds (`-disable-redirects` on a 302), the reference omits the data lines; the
   generated tool prints zeros.
3. One header-set difference in the basic-auth scenario.

Throttling (`-q`), duration mode (`-z`), keep-alive reuse, one-connection-per-request without
keep-alive, the 11-bucket histogram and CSV all match.

**Process:** 3 turns on one session: plan → implement → review (PASS). $0.53, 4 min.
