package tests

import (
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// minRate relaxes throughput floors 10x when everything runs under the race
// detector (KV_RACE=1), which slows both client and server considerably.
func minRate(r float64) float64 {
	if os.Getenv("KV_RACE") != "" {
		return r / 10
	}
	return r
}

func TestThroughputSingleClient(t *testing.T) {
	_, c := newSrv(t)
	const n = 20000
	start := time.Now()
	for i := 0; i < n; i++ {
		if i%2 == 0 {
			c.Do("SET", "k", i)
		} else {
			c.Do("GET", "k")
		}
	}
	rate := float64(n) / time.Since(start).Seconds()
	t.Logf("%.0f req/s", rate)
	if rate < minRate(10000) {
		t.Fatalf("too slow: %.0f req/s", rate)
	}
}

func TestConcurrentIncr(t *testing.T) {
	s, c := newSrv(t)
	const clients, per = 50, 200
	var wg sync.WaitGroup
	for i := 0; i < clients; i++ {
		wg.Add(1)
		cc := s.Client(t)
		go func() {
			defer wg.Done()
			for j := 0; j < per; j++ {
				cc.Send("INCR", "ctr")
				if _, err := cc.TryRead(5 * time.Second); err != nil {
					t.Error(err)
					return
				}
			}
		}()
	}
	wg.Wait()
	expect(t, c, "10000", "GET", "ctr")
}

// Worst-case shapes: big collections must not turn operations quadratic.
func TestCollectionScalability(t *testing.T) {
	_, c := newSrv(t)
	const n = 100000
	pipe := func(args func(i int) []any, count int) {
		for i := 0; i < count; i += 1000 {
			end := min(i+1000, count)
			for j := i; j < end; j++ {
				c.Send(args(j)...)
			}
			for j := i; j < end; j++ {
				c.Read()
			}
		}
	}
	limit := func(name string, d time.Duration, max time.Duration) {
		t.Logf("%s: %v", name, d)
		if d > max {
			t.Fatalf("%s too slow: %v (limit %v)", name, d, max)
		}
	}
	st := time.Now()
	pipe(func(i int) []any { return []any{"LPUSH", "l", i} }, n)
	pipe(func(i int) []any { return []any{"RPUSH", "l", i} }, n)
	limit("200k pushes at both ends", time.Since(st), 15*time.Second)
	st = time.Now()
	pipe(func(i int) []any { return []any{"LPOP", "l"} }, n)
	pipe(func(i int) []any { return []any{"RPOP", "l"} }, n)
	limit("200k pops", time.Since(st), 15*time.Second)
	expect(t, c, 0, "EXISTS", "l")

	st = time.Now()
	pipe(func(i int) []any { return []any{"SADD", "s", i} }, n)
	pipe(func(i int) []any { return []any{"SADD", "s2", i * 2} }, n)
	pipe(func(i int) []any { return []any{"SPOP", "s"} }, n/2)
	pipe(func(i int) []any { return []any{"HSET", "h", i, i} }, n)
	pipe(func(i int) []any { return []any{"HDEL", "h", i} }, n-1)
	limit("set/hash churn", time.Since(st), 25*time.Second)
	expect(t, c, 1, "HLEN", "h")
	st = time.Now()
	c.Do("SINTERSTORE", "i", "s", "s2")
	c.Do("SUNIONSTORE", "u", "s", "s2")
	c.Do("SDIFF", "s", "s2")
	limit("set algebra on 100k members", time.Since(st), 15*time.Second)
	st = time.Now()
	for i := 0; i < 50; i++ {
		c.Do("SRANDMEMBER", "s", 5)
		c.Do("SPOP", "s2", 5)
	}
	limit("random sampling from large sets", time.Since(st), 2*time.Second)
}

func TestThroughputPipelined(t *testing.T) {
	_, c := newSrv(t)
	const n, batch = 200000, 2000
	st := time.Now()
	for i := 0; i < n; i += batch {
		var raw []byte
		for j := i; j < i+batch; j++ {
			if j%2 == 0 {
				raw = append(raw, enc([]any{"SET", "key" + itoa(j%1000), "v"})...)
			} else {
				raw = append(raw, enc([]any{"GET", "key" + itoa(j%1000)})...)
			}
		}
		c.conn.Write(raw)
		for j := 0; j < batch; j++ {
			c.Read()
		}
	}
	rate := float64(n) / time.Since(st).Seconds()
	t.Logf("pipelined: %.0f req/s", rate)
	if rate < minRate(100000) {
		t.Fatalf("pipelined throughput too low: %.0f req/s", rate)
	}
}

func TestThroughputManyClients(t *testing.T) {
	s, _ := newSrv(t)
	const clients, per = 50, 1000
	var wg sync.WaitGroup
	st := time.Now()
	for i := 0; i < clients; i++ {
		c := s.Client(t)
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := "k" + itoa(i)
			for j := 0; j < per; j++ {
				c.Send("SET", key, j)
				if _, err := c.TryRead(10 * time.Second); err != nil {
					t.Error(err)
					return
				}
				c.Send("GET", key)
				if v, err := c.TryRead(10 * time.Second); err != nil || v != itoa(j) {
					t.Errorf("client %d: got %v err %v want %d", i, v, err, j)
					return
				}
			}
		}(i)
	}
	wg.Wait()
	rate := float64(clients*per*2) / time.Since(st).Seconds()
	t.Logf("50 clients: %.0f req/s", rate)
	if rate < minRate(10000) {
		t.Fatalf("too slow: %.0f req/s", rate)
	}
}

// 50 clients run a mixed workload over every data type, each verifying its
// own private keys against a local model while sharing counters.
func TestConcurrentMixedWorkloadCorrectness(t *testing.T) {
	s, c := newSrv(t)
	const clients, iters = 50, 60
	var wg sync.WaitGroup
	for i := 0; i < clients; i++ {
		cc := s.Client(t)
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			p := "c" + itoa(id) + ":"
			fail := func(format string, a ...any) { t.Errorf("client %d: "+format, append([]any{id}, a...)...) }
			for j := 0; j < iters; j++ {
				v := itoa(j)
				if cc.Do("SET", p+"s", v) != OK || cc.Do("GET", p+"s") != v {
					fail("string mismatch")
					return
				}
				if cc.Do("RPUSH", p+"l", v) != int64(j+1) {
					fail("list length")
					return
				}
				if cc.Do("HSET", p+"h", v, v) != int64(1) || cc.Do("HLEN", p+"h") != int64(j+1) {
					fail("hash")
					return
				}
				if cc.Do("SADD", p+"set", v) != int64(1) || cc.Do("SCARD", p+"set") != int64(j+1) {
					fail("set")
					return
				}
				if cc.Do("ZADD", p+"z", j, v) != int64(1) || cc.Do("ZRANK", p+"z", v) != int64(j) {
					fail("zset")
					return
				}
				cc.Do("INCR", "shared:counter")
				cc.Do("ZINCRBY", "shared:z", 1, "m")
				cc.Do("SADD", "shared:set", id)
				cc.Do("LPUSH", "shared:list", id)
			}
			if r := cc.Do("LRANGE", p+"l", -1, -1); !equal(r, arr(itoa(iters-1))) {
				fail("lrange tail %v", r)
			}
		}(i)
	}
	wg.Wait()
	expect(t, c, itoa(clients*iters), "GET", "shared:counter")
	expect(t, c, itoa(clients*iters), "ZSCORE", "shared:z", "m")
	expect(t, c, clients, "SCARD", "shared:set")
	expect(t, c, clients*iters, "LLEN", "shared:list")
	expect(t, c, 5*clients+4, "DBSIZE")
}

func TestManyIdleConnectionsAndChurn(t *testing.T) {
	s, c := newSrv(t)
	var idle []*C
	for i := 0; i < 300; i++ {
		idle = append(idle, s.Client(t))
	}
	expect(t, c, Simple("PONG"), "PING")
	idle[150].Do("SET", "k", "v")
	expect(t, c, "v", "GET", "k")
	for i := 0; i < 500; i++ { // connect, use, disconnect
		cc := s.Client(t)
		cc.Do("INCR", "churn")
		cc.conn.Close()
	}
	expect(t, c, "500", "GET", "churn")
	info := c.Do("INFO", "clients").(string)
	if !strings.Contains(info, "connected_clients:") {
		t.Fatal(info)
	}
}

// A client that writes a huge pipeline before reading anything must not
// deadlock the server (replies are buffered server-side).
func TestHugePipelineWithoutReading(t *testing.T) {
	s, _ := newSrv(t)
	c := s.Client(t)
	const n = 100000
	go func() {
		var raw []byte
		for i := 0; i < n; i++ {
			raw = append(raw, enc([]any{"ECHO", strings.Repeat("x", 100)})...)
			if len(raw) > 1<<20 {
				c.conn.Write(raw)
				raw = raw[:0]
			}
		}
		c.conn.Write(raw)
	}()
	time.Sleep(500 * time.Millisecond)
	for i := 0; i < n; i++ {
		if _, err := c.TryRead(10 * time.Second); err != nil {
			t.Fatalf("reply %d: %v", i, err)
		}
	}
	expect(t, s.Client(t), Simple("PONG"), "PING")
}

// Worst-case glob shapes must stay fast (no exponential backtracking).
func TestGlobPathologicalPatterns(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", strings.Repeat("a", 200), 1)
	st := time.Now()
	c.Do("KEYS", strings.Repeat("a*", 30)+"b")
	c.Do("KEYS", strings.Repeat("*", 1000)+"b")
	d := time.Since(st)
	t.Logf("pathological KEYS: %v", d)
	if d > 5*time.Second {
		t.Fatalf("glob matching is super-linear: %v", d)
	}
}
