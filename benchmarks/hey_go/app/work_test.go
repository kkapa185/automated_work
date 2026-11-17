package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func stub(count *int64) func(context.Context) Result {
	return func(context.Context) Result {
		atomic.AddInt64(count, 1)
		return Result{StatusCode: 200, Duration: time.Millisecond}
	}
}

// R7: exact request count, including n not divisible by c.
func TestExactCount(t *testing.T) {
	for _, tc := range [][2]int{{200, 50}, {10, 3}, {7, 7}, {101, 10}, {1, 1}, {13, 5}} {
		var cnt int64
		r := &Runner{Cfg: &Config{N: tc[0], C: tc[1]}, Do: stub(&cnt)}
		res, _ := r.Run(context.Background())
		if len(res) != tc[0] || int(cnt) != tc[0] {
			t.Errorf("n=%d c=%d: got %d results, %d calls", tc[0], tc[1], len(res), cnt)
		}
	}
}

// R7: concurrency bounded by c, and c workers actually run concurrently.
func TestConcurrency(t *testing.T) {
	var cur, peak int64
	r := &Runner{Cfg: &Config{N: 20, C: 4}, Do: func(context.Context) Result {
		v := atomic.AddInt64(&cur, 1)
		for {
			p := atomic.LoadInt64(&peak)
			if v <= p || atomic.CompareAndSwapInt64(&peak, p, v) {
				break
			}
		}
		time.Sleep(20 * time.Millisecond)
		atomic.AddInt64(&cur, -1)
		return Result{StatusCode: 200}
	}}
	r.Run(context.Background())
	if peak != 4 {
		t.Fatalf("peak=%d", peak)
	}
}

// R8: per-worker QPS. 1 worker, 5 QPS, 3 requests => >= ~0.6s (ticks at 0.2,0.4,0.6).
func TestQPSThrottle(t *testing.T) {
	var cnt int64
	r := &Runner{Cfg: &Config{N: 3, C: 1, QPS: 5}, Do: stub(&cnt)}
	_, total := r.Run(context.Background())
	if total < 550*time.Millisecond || total > 1500*time.Millisecond {
		t.Fatalf("total=%v", total)
	}
	// 2 workers double the aggregate rate: 6 requests also ~0.6s.
	r = &Runner{Cfg: &Config{N: 6, C: 2, QPS: 5}, Do: stub(&cnt)}
	_, total = r.Run(context.Background())
	if total < 550*time.Millisecond || total > 1500*time.Millisecond {
		t.Fatalf("2 workers total=%v", total)
	}
}

// R9: duration mode ignores n and stops after the duration.
func TestDurationMode(t *testing.T) {
	var cnt int64
	r := &Runner{Cfg: &Config{N: 1, C: 2, Duration: 300 * time.Millisecond}, Do: func(ctx context.Context) Result {
		atomic.AddInt64(&cnt, 1)
		time.Sleep(10 * time.Millisecond)
		return Result{StatusCode: 200, Duration: 10 * time.Millisecond}
	}}
	res, total := r.Run(context.Background())
	if len(res) < 10 || total < 290*time.Millisecond || total > 1500*time.Millisecond {
		t.Fatalf("results=%d total=%v", len(res), total)
	}
}

// R9: in-flight requests cancelled at the deadline are discarded.
func TestDurationDiscardsCancelled(t *testing.T) {
	r := &Runner{Cfg: &Config{N: 1, C: 3, Duration: 100 * time.Millisecond}, Do: func(ctx context.Context) Result {
		<-ctx.Done()
		return Result{Err: ctx.Err()}
	}}
	res, total := r.Run(context.Background())
	if len(res) != 0 || total > time.Second {
		t.Fatal(len(res), total)
	}
}

// R10: cancellation stops early and keeps finished results.
func TestCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var cnt int64
	r := &Runner{Cfg: &Config{N: 1000, C: 2}, Do: func(context.Context) Result {
		if atomic.AddInt64(&cnt, 1) == 10 {
			cancel()
		}
		return Result{StatusCode: 200}
	}}
	res, _ := r.Run(ctx)
	if len(res) < 10 || len(res) >= 1000 {
		t.Fatal(len(res))
	}
}

func newServer(h http.HandlerFunc) *httptest.Server { return httptest.NewServer(h) }

func cfgFor(t *testing.T, args ...string) *Config {
	c, err := parseArgs(args)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// R11, R12: real HTTP run: count, status, body size, headers, method, body.
func TestRealHTTP(t *testing.T) {
	var mu sync.Mutex
	var gotMethod, gotBody, gotHost, gotCT string
	srv := newServer(func(w http.ResponseWriter, r *http.Request) {
		b := make([]byte, 100)
		n, _ := r.Body.Read(b)
		mu.Lock()
		gotMethod, gotBody, gotHost, gotCT = r.Method, string(b[:n]), r.Host, r.Header.Get("Content-Type")
		mu.Unlock()
		fmt.Fprint(w, "0123456789")
	})
	defer srv.Close()
	cfg := cfgFor(t, "-n", "20", "-c", "4", "-m", "PUT", "-d", "payload", "-host", "foo.test", "-T", "x/y", srv.URL)
	res, _ := NewRunner(cfg).Run(context.Background())
	if len(res) != 20 {
		t.Fatalf("got %d", len(res))
	}
	for _, r := range res {
		if r.Err != nil || r.StatusCode != 200 || r.ContentLength != 10 || r.Duration <= 0 {
			t.Fatalf("%+v", r)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if gotMethod != "PUT" || gotBody != "payload" || gotHost != "foo.test" || gotCT != "x/y" {
		t.Fatal(gotMethod, gotBody, gotHost, gotCT)
	}
}

// R11: redirects followed by default, not with -disable-redirects.
func TestRedirects(t *testing.T) {
	srv := newServer(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" {
			http.Redirect(w, r, "/dest", http.StatusFound)
			return
		}
		w.WriteHeader(201)
	})
	defer srv.Close()
	res, _ := NewRunner(cfgFor(t, "-n", "1", "-c", "1", srv.URL)).Run(context.Background())
	if res[0].StatusCode != 201 {
		t.Fatal(res[0])
	}
	res, _ = NewRunner(cfgFor(t, "-n", "1", "-c", "1", "-disable-redirects", srv.URL)).Run(context.Background())
	if res[0].StatusCode != 302 {
		t.Fatal(res[0])
	}
}

// R11: -disable-keepalive opens a connection per request; default reuses.
func TestKeepAlive(t *testing.T) {
	count := func(args ...string) int64 {
		var conns int64
		srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
		srv.Config.ConnState = func(_ net.Conn, s http.ConnState) {
			if s == http.StateNew {
				atomic.AddInt64(&conns, 1)
			}
		}
		srv.Start()
		defer srv.Close()
		NewRunner(cfgFor(t, append(args, srv.URL)...)).Run(context.Background())
		return atomic.LoadInt64(&conns)
	}
	if c := count("-n", "10", "-c", "1"); c != 1 {
		t.Errorf("keepalive conns=%d", c)
	}
	if c := count("-n", "10", "-c", "1", "-disable-keepalive"); c != 10 {
		t.Errorf("no-keepalive conns=%d", c)
	}
}

// R11, R18: timeout and connection errors become Result.Err.
func TestTimeoutAndErrors(t *testing.T) {
	srv := newServer(func(w http.ResponseWriter, r *http.Request) { time.Sleep(1500 * time.Millisecond) })
	defer srv.Close()
	res, _ := NewRunner(cfgFor(t, "-n", "1", "-c", "1", "-t", "1", srv.URL)).Run(context.Background())
	if len(res) != 1 || res[0].Err == nil {
		t.Fatalf("%+v", res)
	}
	res, _ = NewRunner(cfgFor(t, "-n", "2", "-c", "1", "http://127.0.0.1:1/")).Run(context.Background())
	if len(res) != 2 || res[0].Err == nil {
		t.Fatalf("%+v", res)
	}
}
