# PERF-17: `hey` — HTTP load generator CLI in Go

Write a Go (>= 1.21, module-based) command-line tool `hey` that sends load to a web application and
prints statistics. Build with `go build -o hey .` from the repository root. Usage:
```
hey [options...] <url>
  -n  Number of requests to run. Default is 200.
  -c  Number of workers to run concurrently (n must be >= c). Default is 50.
  -q  Rate limit, in queries per second (QPS) per worker. Default is no rate limit.
  -z  Duration of application to send requests (e.g. -z 10s, -z 3m); if set, n is ignored.
  -o  Output type. If none provided, a summary is printed. "csv" dumps per-request metrics.
  -m  HTTP method, one of GET, POST, PUT, DELETE, HEAD, OPTIONS.
  -H  Custom HTTP header, repeatable, e.g. -H "Accept: text/html" -H "X-Id: 1".
  -t  Timeout for each request in seconds. Default is 20, use 0 for infinite.
  -A  HTTP Accept header.        -d  HTTP request body.        -D  HTTP request body from file.
  -T  Content-type, defaults to "text/html".   -a  Basic authentication, username:password.
  -x  HTTP Proxy address as host:port.         -h2 Enable HTTP/2.        -host HTTP Host header.
  -disable-compression   -disable-keepalive (no TCP connection re-use)   -disable-redirects
  -cpus  Number of used cpu cores.
```
Invalid usage (no URL, n < c, bad header syntax) prints the usage/error to stderr and exits 1; the method
string is passed through as given.

## Summary output (default)
Sections in this order, durations in seconds with 4 decimals:
```
Summary:
  Total:	<t> secs
  Slowest:	<t> secs
  Fastest:	<t> secs
  Average:	<t> secs
  Requests/sec:	<r>
  
  Total data:	<bytes> bytes
  Size/request:	<bytes> bytes

Response time histogram:
  <bucket upper bound, 3 decimals> [<count>]	|<bar of ■ scaled to 40 chars for the max bucket>
  ... (11 buckets spanning fastest..slowest)

Latency distribution:
  10% in <t> secs   (lines for 10, 25, 50, 75, 90, 95, 99 percentiles)

Details (average, fastest, slowest):
  DNS+dialup:	<avg> secs, <min> secs, <max> secs
  DNS-lookup:	...
  req write:	...
  resp wait:	...
  resp read:	...

Status code distribution:
  [<code>]	<count> responses

Error distribution:            (only if any request failed)
  [<count>]	<error message>
```
"Total data" is the sum of response body sizes; "Size/request" = total data / number of successful responses.
## CSV output (`-o csv`)
Header `response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset` then
one row per request (4-decimal seconds, status code, offset since start).

Deliverables: the Go module, unit tests (`go test ./...`) for argument parsing, the request
scheduler (exact request count with n/c, QPS throttling, duration mode) and report generation, and a README.
