package tests

import (
	"testing"
	"time"
)

func TestBLPopImmediate(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l1", "a")
	c.Do("RPUSH", "l2", "b", "c")
	expect(t, c, arr("l1", "a"), "BLPOP", "l1", "l2", 1)
	expect(t, c, arr("l2", "b"), "BLPOP", "l1", "l2", 1)
	expect(t, c, arr("l2", "c"), "BRPOP", "l1", "l2", 1)
	expect(t, c, 0, "EXISTS", "l2")
	c.Do("SET", "s", "x")
	expect(t, c, wrongType, "BLPOP", "s", 1)
}

func TestBLPopTimeout(t *testing.T) {
	_, c := newSrv(t)
	start := time.Now()
	expect(t, c, Nil, "BLPOP", "nokey", "0.2")
	if d := time.Since(start); d < 150*time.Millisecond || d > 2*time.Second {
		t.Fatalf("timeout after %v", d)
	}
	start = time.Now()
	expect(t, c, Nil, "BRPOP", "a", "b", 1)
	if d := time.Since(start); d < 900*time.Millisecond {
		t.Fatalf("1s timeout fired after %v", d)
	}
	// connection still usable and in sync
	expect(t, c, Simple("PONG"), "PING")
}

func TestBlockingArgErrors(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Err("ERR timeout is not a float or out of range"), "BLPOP", "k", "abc")
	expect(t, c, Err("ERR timeout is negative"), "BLPOP", "k", -1)
	expect(t, c, Err("ERR wrong number of arguments for 'blpop' command"), "BLPOP", "k")
}

func TestBLPopWakeup(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Send("BLPOP", "q", 5)
	time.Sleep(100 * time.Millisecond)
	expect(t, p, 1, "RPUSH", "q", "job")
	if got := c.Read(); !equal(got, arr("q", "job")) {
		t.Fatalf("got %#v", got)
	}
	expect(t, p, 0, "EXISTS", "q") // element consumed by the waiter
	expect(t, c, Simple("PONG"), "PING")
}

func TestBlockingFIFO(t *testing.T) {
	s, _ := newSrv(t)
	p := s.Client(t)
	var cs []*C
	for i := 0; i < 3; i++ {
		c := s.Client(t)
		c.Send("BLPOP", "q", 0)
		cs = append(cs, c)
		time.Sleep(60 * time.Millisecond) // fix the queue order
	}
	expect(t, p, 3, "RPUSH", "q", "1", "2", "3")
	for i, c := range cs {
		want := arr("q", string(rune('1'+i)))
		if got := c.Read(); !equal(got, want) {
			t.Fatalf("client %d got %#v want %#v", i, got, want)
		}
	}
	expect(t, p, 0, "EXISTS", "q")
}

func TestBlockingMultiKeyAndBRPop(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Send("BRPOP", "a", "b", 0)
	time.Sleep(80 * time.Millisecond)
	p.Do("RPUSH", "b", "x", "y")
	if got := c.Read(); !equal(got, arr("b", "y")) {
		t.Fatalf("got %#v", got)
	}
	expect(t, p, arr("x"), "LRANGE", "b", 0, -1)
}

func TestBlockingServedBySingleCommandWithManyWaiters(t *testing.T) {
	s, _ := newSrv(t)
	p := s.Client(t)
	w1, w2 := s.Client(t), s.Client(t)
	w1.Send("BLPOP", "q", 0)
	time.Sleep(50 * time.Millisecond)
	w2.Send("BLPOP", "q", 0)
	time.Sleep(50 * time.Millisecond)
	expect(t, p, 1, "LPUSH", "q", "one")
	if got := w1.Read(); !equal(got, arr("q", "one")) {
		t.Fatal(got)
	}
	if _, err := w2.TryRead(200 * time.Millisecond); err == nil {
		t.Fatal("second waiter must keep waiting")
	}
	_ = p
}

func TestBLMoveAndBRPopLPush(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Send("BRPOPLPUSH", "src", "dst", 0)
	time.Sleep(80 * time.Millisecond)
	p.Do("LPUSH", "src", "v")
	if got := c.Read(); got != "v" {
		t.Fatal(got)
	}
	expect(t, p, arr("v"), "LRANGE", "dst", 0, -1)
	c.Send("BLMOVE", "src", "dst", "LEFT", "RIGHT", "0.1")
	if got := c.Read(); got != nil {
		t.Fatalf("timeout should reply nil bulk: %#v", got)
	}
	p.Do("RPUSH", "src", "a", "b")
	expect(t, c, "a", "BLMOVE", "src", "dst", "LEFT", "RIGHT", 1)
	expect(t, c, arr("v", "a"), "LRANGE", "dst", 0, -1)
}

func TestBlockedClientDisconnectDoesNotEatElement(t *testing.T) {
	s, _ := newSrv(t)
	p := s.Client(t)
	w := s.Client(t)
	w.Send("BLPOP", "q", 0)
	time.Sleep(80 * time.Millisecond)
	w.conn.Close()
	time.Sleep(150 * time.Millisecond)
	expect(t, p, 1, "RPUSH", "q", "keep")
	expect(t, p, arr("keep"), "LRANGE", "q", 0, -1)
	info, _ := p.Do("INFO", "clients").(string)
	if !contains(info, "blocked_clients:0") {
		t.Fatalf("blocked client leaked: %s", info)
	}
}

func TestBlockedClientPipelineOrdering(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Raw(string(enc([]any{"SET", "x", 1})) + string(enc([]any{"BLPOP", "q", 0})) + string(enc([]any{"GET", "x"})))
	if c.Read() != OK {
		t.Fatal("set")
	}
	time.Sleep(80 * time.Millisecond)
	p.Do("RPUSH", "q", "v")
	if got := c.Read(); !equal(got, arr("q", "v")) {
		t.Fatal(got)
	}
	if got := c.Read(); got != "1" {
		t.Fatalf("command after blocking one must run afterwards: %#v", got)
	}
}
