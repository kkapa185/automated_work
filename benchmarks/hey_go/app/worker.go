package main

import (
	"context"
	"crypto/tls"
	"io"
	"net/http"
	"net/http/httptrace"
	"net/url"
	"sort"
	"sync"
	"time"
)

// Result is the measurement of one request.
type Result struct {
	Err           error
	StatusCode    int
	Duration      time.Duration
	ConnDuration  time.Duration // DNS+dialup
	DnsDuration   time.Duration
	ReqDuration   time.Duration
	DelayDuration time.Duration
	ResDuration   time.Duration
	ContentLength int64
	Offset        time.Duration
}

// Runner schedules requests across workers.
type Runner struct {
	Cfg *Config
	Do  func(ctx context.Context) Result
}

// NewRunner creates a runner that performs real HTTP requests.
func NewRunner(cfg *Config) *Runner {
	r := &Runner{Cfg: cfg}
	client := newClient(cfg)
	r.Do = func(ctx context.Context) Result { return doRequest(ctx, client, cfg) }
	return r
}

func newClient(cfg *Config) *http.Client {
	tr := &http.Transport{
		TLSClientConfig:     &tls.Config{InsecureSkipVerify: true},
		DisableCompression:  cfg.DisableCompression,
		DisableKeepAlives:   cfg.DisableKeepAlive,
		MaxIdleConnsPerHost: cfg.C,
		ForceAttemptHTTP2:   cfg.H2,
	}
	if cfg.Proxy != "" {
		if pu, err := url.Parse("http://" + cfg.Proxy); err == nil {
			tr.Proxy = http.ProxyURL(pu)
		}
	}
	cl := &http.Client{Transport: tr, Timeout: time.Duration(cfg.Timeout) * time.Second}
	if cfg.DisableRedirects {
		cl.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	}
	return cl
}

func doRequest(ctx context.Context, cl *http.Client, cfg *Config) Result {
	req, err := cfg.NewRequest()
	if err != nil {
		return Result{Err: err}
	}
	var start, connStart, dnsStart, dnsDone, connDone, gotConn, wrote, firstByte time.Time
	trace := &httptrace.ClientTrace{
		DNSStart:             func(httptrace.DNSStartInfo) { dnsStart = time.Now() },
		DNSDone:              func(httptrace.DNSDoneInfo) { dnsDone = time.Now() },
		ConnectStart:         func(string, string) { connStart = time.Now() },
		ConnectDone:          func(string, string, error) { connDone = time.Now() },
		GotConn:              func(httptrace.GotConnInfo) { gotConn = time.Now() },
		WroteRequest:         func(httptrace.WroteRequestInfo) { wrote = time.Now() },
		GotFirstResponseByte: func() { firstByte = time.Now() },
	}
	req = req.WithContext(httptrace.WithClientTrace(ctx, trace))
	start = time.Now()
	res := Result{}
	resp, err := cl.Do(req)
	if err == nil {
		var n int64
		n, err = io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		res.ContentLength = n
		res.StatusCode = resp.StatusCode
	}
	end := time.Now()
	res.Duration = end.Sub(start)
	if err != nil {
		res.Err = err
		return res
	}
	if !dnsStart.IsZero() && !dnsDone.IsZero() {
		res.DnsDuration = dnsDone.Sub(dnsStart)
	}
	if !connDone.IsZero() {
		first := connStart
		if !dnsStart.IsZero() {
			first = dnsStart
		}
		if !first.IsZero() {
			res.ConnDuration = connDone.Sub(first)
		}
	}
	if !gotConn.IsZero() && !wrote.IsZero() {
		res.ReqDuration = wrote.Sub(gotConn)
	}
	if !wrote.IsZero() && !firstByte.IsZero() {
		res.DelayDuration = firstByte.Sub(wrote)
	}
	if !firstByte.IsZero() {
		res.ResDuration = end.Sub(firstByte)
	}
	return res
}

// Run executes the load and returns results (sorted by offset) and elapsed time.
// Requests that fail only because ctx was cancelled are discarded.
func (r *Runner) Run(ctx context.Context) ([]Result, time.Duration) {
	cfg := r.Cfg
	start := time.Now()
	if cfg.Duration > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, cfg.Duration)
		defer cancel()
	}
	var wg sync.WaitGroup
	parts := make([][]Result, cfg.C)
	for i := 0; i < cfg.C; i++ {
		count := -1 // unlimited (duration mode)
		if cfg.Duration <= 0 {
			count = cfg.N / cfg.C
			if i < cfg.N%cfg.C {
				count++
			}
		}
		wg.Add(1)
		go func(i, count int) {
			defer wg.Done()
			parts[i] = r.worker(ctx, start, count)
		}(i, count)
	}
	wg.Wait()
	total := time.Since(start)
	var all []Result
	for _, p := range parts {
		all = append(all, p...)
	}
	sort.SliceStable(all, func(a, b int) bool { return all[a].Offset < all[b].Offset })
	return all, total
}

func (r *Runner) worker(ctx context.Context, start time.Time, count int) []Result {
	var out []Result
	var tick <-chan time.Time
	if r.Cfg.QPS > 0 {
		d := time.Duration(float64(time.Second) / r.Cfg.QPS)
		if d < 1 {
			d = 1
		}
		t := time.NewTicker(d)
		defer t.Stop()
		tick = t.C
	}
	for i := 0; count < 0 || i < count; i++ {
		if ctx.Err() != nil {
			break
		}
		if tick != nil {
			select {
			case <-tick:
			case <-ctx.Done():
				return out
			}
		}
		t0 := time.Now()
		res := r.Do(ctx)
		if res.Err != nil && ctx.Err() != nil {
			break
		}
		res.Offset = t0.Sub(start)
		out = append(out, res)
	}
	return out
}
