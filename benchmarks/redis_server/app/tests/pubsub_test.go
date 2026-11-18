package tests

import (
	"io"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func readRaw(t *testing.T, c *C, n int) string {
	t.Helper()
	buf := make([]byte, n)
	c.conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.ReadFull(c.r, buf); err != nil {
		t.Fatalf("raw read: %v", err)
	}
	return string(buf)
}

func TestPubSubExactWireFormat(t *testing.T) {
	s, sub := newSrv(t)
	pub := s.Client(t)
	sub.Raw("SUBSCRIBE foo\r\n")
	want := "*3\r\n$9\r\nsubscribe\r\n$3\r\nfoo\r\n:1\r\n"
	if got := readRaw(t, sub, len(want)); got != want {
		t.Fatalf("subscribe reply %q want %q", got, want)
	}
	expect(t, pub, 1, "PUBLISH", "foo", "hello")
	want = "*3\r\n$7\r\nmessage\r\n$3\r\nfoo\r\n$5\r\nhello\r\n"
	if got := readRaw(t, sub, len(want)); got != want {
		t.Fatalf("message %q want %q", got, want)
	}
	sub.Raw("PSUBSCRIBE f*\r\n")
	want = "*3\r\n$10\r\npsubscribe\r\n$2\r\nf*\r\n:2\r\n"
	if got := readRaw(t, sub, len(want)); got != want {
		t.Fatalf("psubscribe reply %q want %q", got, want)
	}
	expect(t, pub, 2, "PUBLISH", "foo", "x") // direct + pattern
	want = "*3\r\n$7\r\nmessage\r\n$3\r\nfoo\r\n$1\r\nx\r\n*4\r\n$8\r\npmessage\r\n$2\r\nf*\r\n$3\r\nfoo\r\n$1\r\nx\r\n"
	if got := readRaw(t, sub, len(want)); got != want {
		t.Fatalf("got %q want %q", got, want)
	}
	sub.Raw("UNSUBSCRIBE foo\r\n")
	want = "*3\r\n$11\r\nunsubscribe\r\n$3\r\nfoo\r\n:1\r\n"
	if got := readRaw(t, sub, len(want)); got != want {
		t.Fatalf("got %q want %q", got, want)
	}
	sub.Raw("PUNSUBSCRIBE f*\r\n")
	want = "*3\r\n$12\r\npunsubscribe\r\n$2\r\nf*\r\n:0\r\n"
	if got := readRaw(t, sub, len(want)); got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestSubscribeUnsubscribeCounts(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Send("SUBSCRIBE", "a", "b", "a")
	if g := c.Read(); !equal(g, arr("subscribe", "a", 1)) {
		t.Fatal(g)
	}
	if g := c.Read(); !equal(g, arr("subscribe", "b", 2)) {
		t.Fatal(g)
	}
	if g := c.Read(); !equal(g, arr("subscribe", "a", 2)) { // duplicate does not add
		t.Fatal(g)
	}
	c.Send("PSUBSCRIBE", "x*", "y?")
	c.Read()
	if g := c.Read(); !equal(g, arr("psubscribe", "y?", 4)) {
		t.Fatal(g)
	}
	expect(t, p, 2, "PUBSUB", "NUMPAT")
	c.Send("UNSUBSCRIBE", "a", "never-subscribed")
	if g := c.Read(); !equal(g, arr("unsubscribe", "a", 3)) {
		t.Fatal(g)
	}
	if g := c.Read(); !equal(g, arr("unsubscribe", "never-subscribed", 3)) {
		t.Fatal(g)
	}
	c.Send("UNSUBSCRIBE") // all remaining channels
	if g := c.Read(); !equal(g, arr("unsubscribe", "b", 2)) {
		t.Fatal(g)
	}
	c.Send("PUNSUBSCRIBE")
	c.Read()
	if g := c.Read(); !equal(g, arr("punsubscribe", "y?", 0)) {
		t.Fatal(g)
	}
	// nothing subscribed: unsubscribe replies with a nil channel
	c.Send("UNSUBSCRIBE")
	if g := c.Read(); !equal(g, arr("unsubscribe", nil, 0)) {
		t.Fatalf("%#v", g)
	}
	c.Send("PUNSUBSCRIBE")
	if g := c.Read(); !equal(g, arr("punsubscribe", nil, 0)) {
		t.Fatalf("%#v", g)
	}
	expect(t, c, Simple("PONG"), "PING") // back to normal mode
}

func TestPatternDelivery(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Send("PSUBSCRIBE", "news.*", "h[ae]llo", "*")
	c.Read()
	c.Read()
	c.Read()
	expect(t, p, 2, "PUBLISH", "news.sports", "goal") // news.* and *
	got := map[string]bool{}
	for i := 0; i < 2; i++ {
		v := c.Read().([]any)
		got[v[1].(string)] = true
		if len(v) != 4 || v[0] != "pmessage" || v[2] != "news.sports" || v[3] != "goal" {
			t.Fatalf("%v", v)
		}
	}
	if !got["news.*"] || !got["*"] {
		t.Fatal(got)
	}
	expect(t, p, 2, "PUBLISH", "hallo", "m")
	c.Read()
	c.Read()
	expect(t, p, 1, "PUBLISH", "other", "m") // only "*"
	c.Read()
}

func TestSubscribedModeRestrictions(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SUBSCRIBE", "a")
	expect(t, c, Err("ERR Can't execute 'get': only (P|S)SUBSCRIBE / (P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context"), "GET", "k")
	expect(t, c, Err("ERR Can't execute 'set': only (P|S)SUBSCRIBE / (P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context"), "SET", "k", "v")
	expect(t, c, arr("pong", ""), "PING")
	expect(t, c, arr("pong", "hi"), "PING", "hi")
	c.Send("SUBSCRIBE", "b") // more subscriptions are allowed
	if g := c.Read(); !equal(g, arr("subscribe", "b", 2)) {
		t.Fatal(g)
	}
	c.Send("RESET")
	if g := c.Read(); g != Simple("RESET") {
		t.Fatalf("%#v", g)
	}
	expect(t, c, Nil, "GET", "k") // normal mode again
	expect(t, c, arr(), "PUBSUB", "CHANNELS")
}

func TestPublishNoSubscribers(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 0, "PUBLISH", "nobody", "x")
	expect(t, c, Err("ERR wrong number of arguments for 'publish' command"), "PUBLISH", "a")
}

func TestPubSubIntrospection(t *testing.T) {
	s, c := newSrv(t)
	s1, s2 := s.Client(t), s.Client(t)
	s1.Send("SUBSCRIBE", "alpha", "beta")
	s1.Read()
	s1.Read()
	s2.Do("SUBSCRIBE", "alpha")
	s2.Do("PSUBSCRIBE", "p*")
	expect(t, c, arr("alpha", "beta"), "PUBSUB", "CHANNELS")
	expect(t, c, arr("alpha"), "PUBSUB", "CHANNELS", "al*")
	expect(t, c, arr(), "PUBSUB", "CHANNELS", "zzz*")
	expect(t, c, arr("alpha", 2, "beta", 1, "none", 0), "PUBSUB", "NUMSUB", "alpha", "beta", "none")
	expect(t, c, arr(), "PUBSUB", "NUMSUB")
	expect(t, c, 1, "PUBSUB", "NUMPAT")
	expect(t, c, Err("ERR unknown subcommand 'bogus'. Try PUBSUB HELP."), "PUBSUB", "bogus")
	// disconnect cleans up subscriptions
	s1.conn.Close()
	s2.conn.Close()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if len(c.Do("PUBSUB", "CHANNELS").([]any)) == 0 && c.Do("PUBSUB", "NUMPAT") == int64(0) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("subscriptions leaked after disconnect")
}

func TestPubSubBinaryAndLargePayloads(t *testing.T) {
	s, c := newSrv(t)
	p := s.Client(t)
	c.Do("SUBSCRIBE", "ch\x00")
	payload := "a\r\n\x00\xffb"
	expect(t, p, 1, "PUBLISH", "ch\x00", payload)
	if g := c.Read(); !equal(g, arr("message", "ch\x00", payload)) {
		t.Fatalf("%#v", g)
	}
	big := strings.Repeat("z", 2<<20)
	expect(t, p, 1, "PUBLISH", "ch\x00", big)
	v := c.Read().([]any)
	if v[2] != big {
		t.Fatal("large message corrupted")
	}
}

func TestPubSubOrderingAndFanOut(t *testing.T) {
	s, _ := newSrv(t)
	p := s.Client(t)
	const subs, msgs = 50, 200
	var cs []*C
	for i := 0; i < subs; i++ {
		c := s.Client(t)
		c.Do("SUBSCRIBE", "fan")
		cs = append(cs, c)
	}
	for i := 0; i < msgs; i++ {
		p.Send("PUBLISH", "fan", i)
	}
	for i := 0; i < msgs; i++ {
		if got := p.Read(); got != int64(subs) {
			t.Fatalf("publish %d reached %v", i, got)
		}
	}
	var wg sync.WaitGroup
	for _, c := range cs {
		wg.Add(1)
		go func(c *C) {
			defer wg.Done()
			for i := 0; i < msgs; i++ {
				v, err := c.TryRead(5 * time.Second)
				if err != nil {
					t.Error(err)
					return
				}
				m := v.([]any)
				if m[2] != strings.TrimSpace(itoa(i)) {
					t.Errorf("out of order: got %v want %d", m[2], i)
					return
				}
			}
		}(c)
	}
	wg.Wait()
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	var b []byte
	for ; i > 0; i /= 10 {
		b = append([]byte{byte('0' + i%10)}, b...)
	}
	return string(b)
}

func TestSlowSubscriberDoesNotBlockPublisher(t *testing.T) {
	s, _ := newSrv(t)
	slow, fast, pub := s.Client(t), s.Client(t), s.Client(t)
	slow.Do("SUBSCRIBE", "big")
	fast.Do("SUBSCRIBE", "big")
	msg := strings.Repeat("m", 100*1024)
	const n = 300 // 30MB to a subscriber that never reads
	done := make(chan struct{})
	go func() {
		defer close(done)
		for i := 0; i < n; i++ {
			pub.Send("PUBLISH", "big", msg)
			if _, err := pub.TryRead(10 * time.Second); err != nil {
				t.Error(err)
				return
			}
		}
	}()
	var got atomic.Int64
	go func() {
		for got.Load() < n {
			if _, err := fast.TryRead(10 * time.Second); err != nil {
				return
			}
			got.Add(1)
		}
	}()
	select {
	case <-done:
	case <-time.After(20 * time.Second):
		t.Fatal("publisher blocked by slow subscriber")
	}
	// other clients are still served
	expect(t, s.Client(t), Simple("PONG"), "PING")
	deadline := time.Now().Add(5 * time.Second)
	for got.Load() < n && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got.Load() != n {
		t.Fatalf("fast subscriber got %d/%d", got.Load(), n)
	}
}

func TestSubscribeInsideMultiAndPublishFromTx(t *testing.T) {
	s, c := newSrv(t)
	sub := s.Client(t)
	sub.Do("SUBSCRIBE", "t")
	c.Do("MULTI")
	c.Do("PUBLISH", "t", "one")
	c.Do("PUBLISH", "t", "two")
	expect(t, c, arr(1, 1), "EXEC")
	for _, w := range []string{"one", "two"} {
		if g := sub.Read(); !equal(g, arr("message", "t", w)) {
			t.Fatalf("%#v", g)
		}
	}
}
