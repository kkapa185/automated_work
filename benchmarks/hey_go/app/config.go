package main

import (
	"encoding/base64"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"runtime"
	"strings"
	"time"
)

const (
	version   = "hey/0.0.1"
	usageText = `Usage: hey [options...] <url>

Options:
  -n  Number of requests to run. Default is 200.
  -c  Number of workers to run concurrently. Total number of requests cannot
      be smaller than the concurrency level. Default is 50.
  -q  Rate limit, in queries per second (QPS) per worker. Default is no rate limit.
  -z  Duration of application to send requests. When duration is reached,
      application stops and exits. If duration is specified, n is ignored.
      Examples: -z 10s -z 3m.
  -o  Output type. If none provided, a summary is printed.
      "csv" is the only supported alternative. Dumps the response
      metrics in comma-separated values format.

  -m  HTTP method, one of GET, POST, PUT, DELETE, HEAD, OPTIONS.
  -H  Custom HTTP header. You can specify as many as needed by repeating the flag.
      For example, -H "Accept: text/html" -H "Content-Type: application/xml" .
  -t  Timeout for each request in seconds. Default is 20, use 0 for infinite.
  -A  HTTP Accept header.
  -d  HTTP request body.
  -D  HTTP request body from file. For example, /home/user/file.txt or ./file.txt.
  -T  Content-type, defaults to "text/html".
  -a  Basic authentication, username:password.
  -x  HTTP Proxy address as host:port.
  -h2 Enable HTTP/2.

  -host	HTTP Host header.

  -disable-compression  Disable compression.
  -disable-keepalive    Disable keep-alive, prevents re-use of TCP
                        connections between different HTTP requests.
  -disable-redirects    Disable following of HTTP redirects
  -cpus                 Number of used cpu cores.
                        (default for current machine is %d cores)
`
)

// Config holds all parsed options.
type Config struct {
	URL                string
	N, C               int
	QPS                float64
	Duration           time.Duration
	Output             string
	Method             string
	Headers            http.Header // custom headers from -H
	Timeout            int
	Accept             string
	Body               []byte
	ContentType        string
	User, Pass         string
	HasAuth            bool
	Proxy              string
	H2                 bool
	Host               string
	DisableCompression bool
	DisableKeepAlive   bool
	DisableRedirects   bool
	CPUs               int
}

type headerFlags []string

func (h *headerFlags) String() string     { return strings.Join(*h, ";") }
func (h *headerFlags) Set(v string) error { *h = append(*h, v); return nil }

var headerRe = regexp.MustCompile(`^([\w-]+):\s*(.+)`)
var authRe = regexp.MustCompile(`^([\w-\.]+):(.+)`)

func usage() string { return fmt.Sprintf(usageText, runtime.NumCPU()) }

func parseArgs(args []string) (*Config, error) {
	fs := flag.NewFlagSet("hey", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	var (
		hs                              headerFlags
		method, output, accept, bodyStr string
		bodyFile, ctype, auth, proxy    string
		host                            string
		n, c, timeout, cpus             int
		q                               float64
		z                               time.Duration
		h2, dc, dk, dr                  bool
	)
	fs.StringVar(&method, "m", "GET", "")
	fs.Var(&hs, "H", "")
	fs.StringVar(&output, "o", "", "")
	fs.StringVar(&accept, "A", "", "")
	fs.StringVar(&bodyStr, "d", "", "")
	fs.StringVar(&bodyFile, "D", "", "")
	fs.StringVar(&ctype, "T", "text/html", "")
	fs.StringVar(&auth, "a", "", "")
	fs.StringVar(&proxy, "x", "", "")
	fs.StringVar(&host, "host", "", "")
	fs.IntVar(&n, "n", 200, "")
	fs.IntVar(&c, "c", 50, "")
	fs.IntVar(&timeout, "t", 20, "")
	fs.IntVar(&cpus, "cpus", runtime.NumCPU(), "")
	fs.Float64Var(&q, "q", 0, "")
	fs.DurationVar(&z, "z", 0, "")
	fs.BoolVar(&h2, "h2", false, "")
	fs.BoolVar(&dc, "disable-compression", false, "")
	fs.BoolVar(&dk, "disable-keepalive", false, "")
	fs.BoolVar(&dr, "disable-redirects", false, "")

	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	var pos []string
	for {
		rest := fs.Args()
		if len(rest) == 0 {
			break
		}
		pos = append(pos, rest[0])
		if err := fs.Parse(rest[1:]); err != nil {
			return nil, err
		}
	}
	if len(pos) == 0 {
		return nil, errors.New("missing url")
	}
	if len(pos) > 1 {
		return nil, errors.New("too many arguments: expected exactly one url")
	}
	cfg := &Config{
		URL: pos[0], N: n, C: c, QPS: q, Duration: z, Output: output, Method: method,
		Timeout: timeout, Accept: accept, ContentType: ctype, Proxy: proxy, H2: h2, Host: host,
		DisableCompression: dc, DisableKeepAlive: dk, DisableRedirects: dr, CPUs: cpus,
		Headers: http.Header{},
	}
	if output != "" && output != "csv" {
		return nil, errors.New(`invalid output type; only "csv" is supported`)
	}
	if z <= 0 {
		if n <= 0 || c <= 0 {
			return nil, errors.New("-n and -c cannot be smaller than 1")
		}
		if n < c {
			return nil, errors.New("-n cannot be less than -c")
		}
	} else if c <= 0 {
		return nil, errors.New("-c cannot be smaller than 1")
	}
	if z < 0 || q < 0 || timeout < 0 {
		return nil, errors.New("-z, -q and -t cannot be negative")
	}
	if cpus < 1 {
		return nil, errors.New("-cpus cannot be smaller than 1")
	}
	for _, h := range hs {
		m := headerRe.FindStringSubmatch(h)
		if m == nil {
			return nil, fmt.Errorf("invalid header %q: expected \"Name: value\"", h)
		}
		cfg.Headers.Add(m[1], m[2])
	}
	if auth != "" {
		m := authRe.FindStringSubmatch(auth)
		if m == nil {
			return nil, fmt.Errorf("invalid -a %q: expected username:password", auth)
		}
		cfg.User, cfg.Pass, cfg.HasAuth = m[1], m[2], true
	}
	u, err := url.Parse(cfg.URL)
	if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
		return nil, fmt.Errorf("invalid url %q", cfg.URL)
	}
	if proxy != "" {
		if _, err := url.Parse("http://" + proxy); err != nil {
			return nil, fmt.Errorf("invalid proxy %q", proxy)
		}
	}
	if bodyFile != "" {
		b, err := os.ReadFile(bodyFile)
		if err != nil {
			return nil, err
		}
		cfg.Body = b
	} else if bodyStr != "" {
		cfg.Body = []byte(bodyStr)
	}
	return cfg, nil
}

// NewRequest builds a fresh request from the config.
func (c *Config) NewRequest() (*http.Request, error) {
	var body io.Reader
	if c.Body != nil {
		body = strings.NewReader(string(c.Body))
	}
	req, err := http.NewRequest(c.Method, c.URL, body)
	if err != nil {
		return nil, err
	}
	hdr := http.Header{}
	hdr.Set("Content-Type", c.ContentType)
	if c.Accept != "" {
		hdr.Set("Accept", c.Accept)
	}
	for k, v := range c.Headers {
		hdr[k] = append([]string(nil), v...)
	}
	if ua := hdr.Get("User-Agent"); ua == "" {
		hdr.Set("User-Agent", version)
	} else {
		hdr.Set("User-Agent", ua+" "+version)
	}
	req.Header = hdr
	if c.Host != "" {
		req.Host = c.Host
	}
	if c.HasAuth {
		req.Header.Set("Authorization", "Basic "+base64.StdEncoding.EncodeToString([]byte(c.User+":"+c.Pass)))
	}
	return req, nil
}
