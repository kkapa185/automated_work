package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// R1: defaults.
func TestDefaults(t *testing.T) {
	c, err := parseArgs([]string{"http://localhost:1/"})
	if err != nil {
		t.Fatal(err)
	}
	if c.N != 200 || c.C != 50 || c.QPS != 0 || c.Duration != 0 || c.Method != "GET" ||
		c.Timeout != 20 || c.ContentType != "text/html" || c.Output != "" || c.H2 {
		t.Fatalf("%+v", c)
	}
}

// R1, R2: all flags, and flags after the URL.
func TestAllFlags(t *testing.T) {
	f := filepath.Join(t.TempDir(), "b.txt")
	os.WriteFile(f, []byte("filebody"), 0o644)
	c, err := parseArgs([]string{"-n", "10", "-c", "2", "-q", "5", "-m", "POST", "-H", "Accept: a/b", "-H", "X-Id: 1",
		"-t", "0", "-A", "text/plain", "-D", f, "-T", "app/json", "-a", "u:p", "-x", "127.0.0.1:8080", "-h2",
		"-host", "example.com", "-disable-compression", "-disable-keepalive", "-disable-redirects", "-cpus", "2",
		"-o", "csv", "http://localhost/", "-z", "3s"})
	if err != nil {
		t.Fatal(err)
	}
	if c.N != 10 || c.C != 2 || c.QPS != 5 || c.Method != "POST" || c.Timeout != 0 || c.Accept != "text/plain" ||
		string(c.Body) != "filebody" || c.ContentType != "app/json" || c.User != "u" || c.Pass != "p" ||
		c.Proxy != "127.0.0.1:8080" || !c.H2 || c.Host != "example.com" || !c.DisableCompression ||
		!c.DisableKeepAlive || !c.DisableRedirects || c.CPUs != 2 || c.Output != "csv" ||
		c.Duration != 3*time.Second || c.URL != "http://localhost/" {
		t.Fatalf("%+v", c)
	}
	if c.Headers.Get("X-Id") != "1" || c.Headers.Get("Accept") != "a/b" {
		t.Fatal(c.Headers)
	}
}

// R2-R4
func TestInvalid(t *testing.T) {
	cases := map[string][]string{
		"no url":      {},
		"two urls":    {"http://a/", "http://b/"},
		"n<c":         {"-n", "5", "-c", "10", "http://a/"},
		"n zero":      {"-n", "0", "-c", "1", "http://a/"},
		"bad header":  {"-H", "nocolon", "http://a/"},
		"bad auth":    {"-a", "nocolon", "http://a/"},
		"bad output":  {"-o", "json", "http://a/"},
		"bad url":     {"notaurl"},
		"missing -D":  {"-D", "/nonexistent/file", "http://a/"},
		"unknown flg": {"-bogus", "http://a/"},
	}
	for name, args := range cases {
		if _, err := parseArgs(args); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
}

// R3: n<c is fine in duration mode.
func TestDurationSkipsNC(t *testing.T) {
	if _, err := parseArgs([]string{"-n", "1", "-c", "5", "-z", "1s", "http://a/"}); err != nil {
		t.Fatal(err)
	}
}

// R1: method string is passed through unchanged.
func TestMethodPassthrough(t *testing.T) {
	c, _ := parseArgs([]string{"-m", "PATCH", "http://a/"})
	req, err := c.NewRequest()
	if err != nil || req.Method != "PATCH" {
		t.Fatal(err, req)
	}
}

// R6: request construction.
func TestNewRequest(t *testing.T) {
	c, err := parseArgs([]string{"-m", "POST", "-d", "hello", "-H", "Accept: x/y", "-H", "X-A: 1", "-H", "X-A: 2",
		"-host", "h.example", "-a", "user:pw", "http://localhost/p"})
	if err != nil {
		t.Fatal(err)
	}
	req, _ := c.NewRequest()
	if req.Header.Get("Content-Type") != "text/html" || req.Header.Get("Accept") != "x/y" ||
		req.Header.Get("User-Agent") != "hey/0.0.1" || req.Host != "h.example" ||
		len(req.Header["X-A"]) != 2 {
		t.Fatalf("%v host=%s", req.Header, req.Host)
	}
	if u, p, ok := req.BasicAuth(); !ok || u != "user" || p != "pw" {
		t.Fatal("auth")
	}
	b := make([]byte, 10)
	n, _ := req.Body.Read(b)
	if string(b[:n]) != "hello" {
		t.Fatal("body")
	}
	// body reader is fresh per request
	r2, _ := c.NewRequest()
	n, _ = r2.Body.Read(b)
	if string(b[:n]) != "hello" {
		t.Fatal("body2")
	}
}

func TestHeaderOverridesAndUA(t *testing.T) {
	c, _ := parseArgs([]string{"-A", "a/a", "-H", "Content-Type: c/c", "-H", "Accept: b/b", "-H", "User-Agent: mine", "http://localhost/"})
	req, _ := c.NewRequest()
	if req.Header.Get("Content-Type") != "c/c" || req.Header.Get("Accept") != "b/b" ||
		req.Header.Get("User-Agent") != "mine hey/0.0.1" {
		t.Fatal(req.Header)
	}
}
