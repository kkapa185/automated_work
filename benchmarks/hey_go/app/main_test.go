package main

import (
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// R2, R3, R4, R20: invalid usage exits 1 with usage on stderr, nothing on stdout.
func TestRunInvalid(t *testing.T) {
	for _, args := range [][]string{{}, {"-n", "1", "-c", "2", "http://a/"}, {"-H", "bad", "http://a/"}} {
		var out, errb bytes.Buffer
		if code := run(args, &out, &errb); code != 1 || out.Len() != 0 || !strings.Contains(errb.String(), "Usage: hey") {
			t.Errorf("%v: code=%d stderr=%q", args, code, errb.String())
		}
	}
}

// R13, R18, R20: end-to-end summary.
func TestRunSummary(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "abcde") }))
	defer srv.Close()
	var out, errb bytes.Buffer
	if code := run([]string{"-n", "30", "-c", "3", srv.URL}, &out, &errb); code != 0 {
		t.Fatal(code, errb.String())
	}
	s := out.String()
	order := []string{"Summary:", "  Total:\t", "  Slowest:\t", "  Fastest:\t", "  Average:\t", "  Requests/sec:\t",
		"  Total data:\t150 bytes", "  Size/request:\t5 bytes", "Response time histogram:", "Latency distribution:",
		"Details (average, fastest, slowest):", "  DNS+dialup:\t", "  DNS-lookup:\t", "  req write:\t", "  resp wait:\t",
		"  resp read:\t", "Status code distribution:", "  [200]\t30 responses"}
	pos := 0
	for _, o := range order {
		i := strings.Index(s[pos:], o)
		if i < 0 {
			t.Fatalf("missing/out of order %q in\n%s", o, s)
		}
		pos += i
	}
	if strings.Contains(s, "Error distribution") {
		t.Fatal("unexpected errors")
	}
}

// R19: end-to-end CSV.
func TestRunCSV(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404) }))
	defer srv.Close()
	var out, errb bytes.Buffer
	if code := run([]string{"-n", "5", "-c", "1", "-o", "csv", srv.URL}, &out, &errb); code != 0 {
		t.Fatal(code, errb.String())
	}
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 6 || lines[0] != "response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset" {
		t.Fatal(out.String())
	}
	for _, l := range lines[1:] {
		if f := strings.Split(l, ","); len(f) != 8 || f[6] != "404" {
			t.Fatal(l)
		}
	}
}

// R18: unreachable host yields error distribution, exit 0.
func TestRunErrors(t *testing.T) {
	var out, errb bytes.Buffer
	if code := run([]string{"-n", "2", "-c", "1", "http://127.0.0.1:1/"}, &out, &errb); code != 0 {
		t.Fatal(code)
	}
	if !strings.Contains(out.String(), "Error distribution:\n  [2]\t") {
		t.Fatal(out.String())
	}
}
