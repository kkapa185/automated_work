package tests

import (
	"strconv"
	"sync"
	"testing"
	"time"
)

var queued = Simple("QUEUED")

func TestMultiExecBasic(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "MULTI")
	expect(t, c, queued, "SET", "a", 1)
	expect(t, c, queued, "INCR", "a")
	expect(t, c, queued, "GET", "a")
	expect(t, c, queued, "LPUSH", "l", "x", "y")
	expect(t, c, queued, "LRANGE", "l", 0, -1)
	expect(t, c, arr(OK, 2, "2", 2, arr("y", "x")), "EXEC")
	// empty transaction
	expect(t, c, OK, "MULTI")
	expect(t, c, arr(), "EXEC")
}

func TestQueuedCommandsNotVisibleBeforeExec(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	expect(t, c, OK, "MULTI")
	expect(t, c, queued, "SET", "later", 1)
	expect(t, o, Nil, "GET", "later")
	expect(t, c, arr(OK), "EXEC")
	expect(t, o, "1", "GET", "later")
}

func TestExecRuntimeErrorDoesNotAbort(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "MULTI")
	expect(t, c, queued, "SET", "s", "x")
	expect(t, c, queued, "INCR", "s")
	expect(t, c, queued, "SET", "t", "y")
	expect(t, c, queued, "LPUSH", "s", "a")
	expect(t, c, arr(OK, Err("ERR value is not an integer or out of range"), OK, wrongType), "EXEC")
	expect(t, c, "y", "GET", "t")
}

func TestExecAbortOnQueueErrors(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "MULTI")
	expect(t, c, queued, "SET", "a", 1)
	expect(t, c, Err("ERR unknown command 'FOOBAR', with args beginning with: 'x' "), "FOOBAR", "x")
	expect(t, c, queued, "SET", "b", 2)
	expect(t, c, Err("EXECABORT Transaction discarded because of previous errors."), "EXEC")
	expect(t, c, Nil, "GET", "a")
	expect(t, c, Nil, "GET", "b")
	// arity error also poisons the transaction
	expect(t, c, OK, "MULTI")
	expect(t, c, Err("ERR wrong number of arguments for 'get' command"), "GET")
	expect(t, c, Err("EXECABORT Transaction discarded because of previous errors."), "EXEC")
	// and the connection is back to normal afterwards
	expect(t, c, OK, "SET", "a", 1)
	expect(t, c, Err("ERR EXEC without MULTI"), "EXEC")
}

func TestMultiMisuse(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Err("ERR EXEC without MULTI"), "EXEC")
	expect(t, c, Err("ERR DISCARD without MULTI"), "DISCARD")
	expect(t, c, OK, "MULTI")
	expect(t, c, Err("ERR MULTI calls can not be nested"), "MULTI")
	expect(t, c, Err("ERR WATCH inside MULTI is not allowed"), "WATCH", "k")
	expect(t, c, queued, "SET", "k", "v")
	expect(t, c, arr(OK), "EXEC") // misuse errors did not poison the transaction
	expect(t, c, OK, "MULTI")
	expect(t, c, queued, "SET", "z", "v")
	expect(t, c, OK, "DISCARD")
	expect(t, c, Nil, "GET", "z")
	expect(t, c, Err("ERR EXEC without MULTI"), "EXEC")
	expect(t, c, OK, "UNWATCH")
	expect(t, c, Err("ERR wrong number of arguments for 'watch' command"), "WATCH")
}

func TestWatchAbortsOnChange(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	expect(t, c, OK, "SET", "k", "orig")
	expect(t, c, OK, "WATCH", "k")
	expect(t, o, OK, "SET", "k", "changed")
	expect(t, c, OK, "MULTI")
	expect(t, c, queued, "SET", "k", "mine")
	expect(t, c, Nil, "EXEC") // nil multi-bulk
	expect(t, c, "changed", "GET", "k")
	// transaction state is cleared: a fresh one works even though k changes later
	expect(t, c, OK, "MULTI")
	expect(t, o, OK, "SET", "k", "again")
	expect(t, c, queued, "SET", "k", "mine")
	expect(t, c, arr(OK), "EXEC")
	expect(t, c, "mine", "GET", "k")
}

func TestWatchUnchangedSucceeds(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	c.Do("SET", "k", "v")
	c.Do("WATCH", "k", "other")
	o.Do("SET", "unrelated", 1)
	o.Do("GET", "k")
	o.Do("DEL", "nonexistent")
	c.Do("MULTI")
	c.Do("INCR", "ctr")
	expect(t, c, arr(1), "EXEC")
}

func TestWatchModificationKinds(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	setup := func() {
		o.Do("FLUSHALL")
		o.Do("SET", "str", "v")
		o.Do("RPUSH", "list", "a")
		o.Do("HSET", "hash", "f", "v")
		o.Do("SADD", "set", "m")
		o.Do("ZADD", "z", 1, "m")
	}
	cases := []struct {
		name string
		key  string
		mod  []any
	}{
		{"set same value", "str", []any{"SET", "str", "v"}},
		{"append", "str", []any{"APPEND", "str", "x"}},
		{"setrange in place", "str", []any{"SETRANGE", "str", 0, "x"}},
		{"incr new", "nokey", []any{"INCR", "nokey"}},
		{"del", "str", []any{"DEL", "str"}},
		{"expire", "str", []any{"EXPIRE", "str", 100}},
		{"rename away", "str", []any{"RENAME", "str", "other"}},
		{"lpush", "list", []any{"LPUSH", "list", "b"}},
		{"lset", "list", []any{"LSET", "list", 0, "z"}},
		{"lpop empties", "list", []any{"LPOP", "list"}},
		{"hset same value", "hash", []any{"HSET", "hash", "f", "v"}},
		{"hdel", "hash", []any{"HDEL", "hash", "f"}},
		{"sadd new", "set", []any{"SADD", "set", "n"}},
		{"srem", "set", []any{"SREM", "set", "m"}},
		{"zadd new", "z", []any{"ZADD", "z", 2, "n"}},
		{"zincrby", "z", []any{"ZINCRBY", "z", 1, "m"}},
		{"flushall", "str", []any{"FLUSHALL"}},
		{"flushdb", "list", []any{"FLUSHDB"}},
		{"move", "str", []any{"MOVE", "str", 3}},
		{"getdel", "str", []any{"GETDEL", "str"}},
	}
	for _, tc := range cases {
		setup()
		expect(t, c, OK, "WATCH", tc.key)
		o.Do(tc.mod...)
		c.Do("MULTI")
		c.Do("PING")
		if got := c.Do("EXEC"); got != nil {
			t.Errorf("%s: EXEC should abort, got %#v", tc.name, got)
		}
	}
	_ = s
}

func TestWatchNoopWritesDoNotAbort(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	o.Do("SADD", "set", "m")
	o.Do("ZADD", "z", 1, "m")
	o.Do("SET", "str", "v")
	c.Do("WATCH", "set", "z", "str", "nokey")
	o.Do("SADD", "set", "m")         // already a member
	o.Do("ZADD", "z", 1, "m")        // same score
	o.Do("SET", "str", "x", "NX")    // NX fails
	o.Do("DEL", "nokey")             // nothing to delete
	o.Do("SREM", "set", "notmember") // nothing removed
	c.Do("MULTI")
	c.Do("PING")
	expect(t, c, arr(Simple("PONG")), "EXEC")
}

func TestWatchExpiredKey(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "k", "v", "PX", 100)
	c.Do("WATCH", "k")
	time.Sleep(200 * time.Millisecond)
	c.Do("MULTI")
	c.Do("PING")
	expect(t, c, Nil, "EXEC")
}

func TestWatchOwnWriteAndUnwatchDiscard(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	c.Do("WATCH", "k")
	c.Do("SET", "k", "mine")
	c.Do("MULTI")
	expect(t, c, Nil, "EXEC")
	c.Do("WATCH", "k")
	o.Do("SET", "k", "x")
	expect(t, c, OK, "UNWATCH")
	c.Do("MULTI")
	expect(t, c, arr(), "EXEC")
	c.Do("WATCH", "k")
	o.Do("SET", "k", "y")
	c.Do("MULTI")
	c.Do("DISCARD") // discards watches too
	c.Do("MULTI")
	expect(t, c, arr(), "EXEC")
}

func TestWatchIsPerDatabase(t *testing.T) {
	s, c := newSrv(t)
	o := s.Client(t)
	c.Do("WATCH", "k")
	o.Do("SELECT", 1)
	o.Do("SET", "k", "other-db")
	c.Do("MULTI")
	expect(t, c, arr(), "EXEC")
	c.Do("SELECT", 2)
	c.Do("WATCH", "k")
	o.Do("SELECT", 2)
	o.Do("SET", "k", "v")
	c.Do("MULTI")
	expect(t, c, Nil, "EXEC")
}

func TestExecWithBlockingAndSelect(t *testing.T) {
	_, c := newSrv(t)
	c.Do("MULTI")
	c.Do("BLPOP", "q", 0)
	c.Do("RPUSH", "q", "v")
	c.Do("BLPOP", "q", 0)
	c.Do("BRPOPLPUSH", "none", "dst", 0)
	c.Do("SELECT", 3)
	c.Do("SET", "k", "in3")
	start := time.Now()
	expect(t, c, arr(Nil, 1, arr("q", "v"), Nil, OK, OK), "EXEC")
	if time.Since(start) > time.Second {
		t.Fatal("blocking command blocked inside MULTI")
	}
	expect(t, c, "in3", "GET", "k") // SELECT took effect for the connection
}

func TestTransactionPipelinedInOnePacket(t *testing.T) {
	_, c := newSrv(t)
	var raw string
	for _, a := range [][]any{{"MULTI"}, {"SET", "a", 1}, {"INCR", "a"}, {"EXEC"}, {"GET", "a"}} {
		raw += string(enc(a))
	}
	c.Raw(raw)
	for _, want := range []any{OK, queued, queued, arr(OK, 2), "2"} {
		if got := c.Read(); !equal(got, want) {
			t.Fatalf("got %#v want %#v", got, want)
		}
	}
}

func TestTransactionAtomicity(t *testing.T) {
	s, c := newSrv(t)
	var wg sync.WaitGroup
	stop := make(chan struct{})
	for i := 0; i < 8; i++ {
		w := s.Client(t)
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 100; j++ {
				w.Do("MULTI")
				w.Do("INCR", "x")
				w.Do("INCR", "y")
				w.Do("EXEC")
			}
		}()
	}
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	_ = stop
	for {
		select {
		case <-done:
			expect(t, c, "800", "GET", "x")
			expect(t, c, "800", "GET", "y")
			return
		default:
		}
		c.Do("MULTI")
		c.Do("GET", "x")
		c.Do("GET", "y")
		r := c.Do("EXEC").([]any)
		if r[0] != r[1] && !(r[0] == nil || r[1] == nil) {
			t.Fatalf("transaction observed a partial update: %v", r)
		}
	}
}

func TestOptimisticLockingCounter(t *testing.T) {
	s, c := newSrv(t)
	c.Do("SET", "n", 0)
	const clients, per = 10, 30
	var wg sync.WaitGroup
	for i := 0; i < clients; i++ {
		w := s.Client(t)
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < per; j++ {
				for {
					w.Do("WATCH", "n")
					v, _ := strconv.Atoi(w.Do("GET", "n").(string))
					w.Do("MULTI")
					w.Do("SET", "n", v+1)
					if w.Do("EXEC") != nil {
						break
					}
				}
			}
		}()
	}
	wg.Wait()
	expect(t, c, strconv.Itoa(clients*per), "GET", "n")
}

func TestResetClearsTransaction(t *testing.T) {
	_, c := newSrv(t)
	c.Do("MULTI")
	c.Do("SET", "a", 1)
	expect(t, c, Simple("RESET"), "RESET")
	expect(t, c, Err("ERR EXEC without MULTI"), "EXEC")
	expect(t, c, Nil, "GET", "a")
}
