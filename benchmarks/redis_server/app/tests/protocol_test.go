package tests

import (
	"strings"
	"testing"
	"time"
)

func TestPingEcho(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Simple("PONG"), "PING")
	expect(t, c, "hello", "PING", "hello")
	expect(t, c, "hi there", "ECHO", "hi there")
	expect(t, c, Err("ERR wrong number of arguments for 'echo' command"), "ECHO")
	expect(t, c, Err("ERR wrong number of arguments for 'ping' command"), "PING", "a", "b")
}

func TestErrorsFromTicket(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Err("ERR wrong number of arguments for 'get' command"), "GET")
	expect(t, c, Err("ERR wrong number of arguments for 'get' command"), "get", "a", "b")
	expect(t, c, OK, "SET", "k", "v")
	// the WRONGTYPE example from the ticket is asserted in lists_test.go once other types exist
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCR", "k")
}

func TestUnknownCommand(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Err("ERR unknown command 'FOO', with args beginning with: 'a' 'b' "), "FOO", "a", "b")
	expect(t, c, Err("ERR unknown command 'foo', with args beginning with: "), "foo")
}

func TestCaseInsensitive(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "sEt", "k", "v", "nX")
	expect(t, c, "v", "GeT", "k")
}

func TestInlineCommands(t *testing.T) {
	_, c := newSrv(t)
	c.Raw("PING\r\n")
	if got := c.Read(); got != Simple("PONG") {
		t.Fatal(got)
	}
	c.Raw("SET foo bar\r\nGET foo\r\n")
	if c.Read() != OK || c.Read() != "bar" {
		t.Fatal("inline pipeline")
	}
	c.Raw("SET \"a b\" 'c d'\n")
	if c.Read() != OK {
		t.Fatal("quoted")
	}
	expect(t, c, "c d", "GET", "a b")
	c.Raw("SET esc \"x\\x41\\n\\\"y\"\r\n")
	c.Read()
	expect(t, c, "xA\n\"y", "GET", "esc")
	c.Raw("\r\n\r\n   \r\nECHO hi\r\n") // blank lines ignored
	if got := c.Read(); got != "hi" {
		t.Fatal(got)
	}
	c.Raw("ECHO \"unbalanced\r\n")
	if got := c.Read(); got != Err("ERR Protocol error: unbalanced quotes in request") {
		t.Fatal(got)
	}
}

func TestPipelining(t *testing.T) {
	_, c := newSrv(t)
	var sb strings.Builder
	for i := 0; i < 1000; i++ {
		sb.Write(enc([]any{"INCR", "ctr"}))
	}
	c.Raw(sb.String())
	for i := 1; i <= 1000; i++ {
		if got := c.Read(); got != int64(i) {
			t.Fatalf("reply %d: %v", i, got)
		}
	}
}

func TestSplitPackets(t *testing.T) {
	_, c := newSrv(t)
	msg := string(enc([]any{"SET", "split", "value"}))
	for _, ch := range msg {
		c.Raw(string(ch))
		time.Sleep(time.Millisecond)
	}
	if c.Read() != OK {
		t.Fatal("split set")
	}
	// partial command followed by completion of a previous reply
	c.Raw(string(enc([]any{"GET", "split"})) + "*2\r\n$4\r\nECHO\r\n")
	if got := c.Read(); got != "value" {
		t.Fatalf("reply before partial command must arrive: %v", got)
	}
	c.Raw("$2\r\nok\r\n")
	if got := c.Read(); got != "ok" {
		t.Fatal(got)
	}
}

func TestBinarySafeAndLarge(t *testing.T) {
	_, c := newSrv(t)
	bin := "a\x00b\r\nc\xff"
	expect(t, c, OK, "SET", "bin", bin)
	expect(t, c, bin, "GET", "bin")
	expect(t, c, 7, "STRLEN", "bin")
	big := strings.Repeat("x", 3<<20)
	expect(t, c, OK, "SET", "big", big)
	expect(t, c, int64(len(big)), "STRLEN", "big")
	if got := c.Do("GET", "big"); got != big {
		t.Fatal("large value mismatch")
	}
	expect(t, c, Nil, "GET", "missing")
}

func TestEmptyArg(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "SET", "", "")
	expect(t, c, "", "GET", "")
	expect(t, c, 1, "EXISTS", "")
}

func TestProtocolErrors(t *testing.T) {
	cases := map[string]string{
		"*abc\r\n":             "ERR Protocol error: invalid multibulk length",
		"*1\r\nfoo\r\n":        "ERR Protocol error: expected '$', got 'f'",
		"*1\r\n$abc\r\n":       "ERR Protocol error: invalid bulk length",
		"*1\r\n$-5\r\n":        "ERR Protocol error: invalid bulk length",
		"*1\r\n$600000000\r\n": "ERR Protocol error: invalid bulk length",
		"*2000000\r\n":         "ERR Protocol error: invalid multibulk length",
	}
	s, _ := newSrv(t)
	for in, want := range cases {
		c := s.Client(t)
		c.Raw(in)
		if got := c.Read(); got != Err(want) {
			t.Errorf("%q: got %#v want %q", in, got, want)
		}
		if _, err := c.TryRead(time.Second); err == nil {
			t.Errorf("%q: connection should be closed", in)
		}
	}
	// the server keeps serving other clients
	expect(t, s.Client(t), Simple("PONG"), "PING")
}

func TestNullMultibulkIgnored(t *testing.T) {
	_, c := newSrv(t)
	c.Raw("*0\r\n*-1\r\n")
	expect(t, c, Simple("PONG"), "PING")
}

func TestQuit(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "QUIT")
	if _, err := c.TryRead(time.Second); err == nil {
		t.Fatal("expected close after QUIT")
	}
}

func TestSelectAndDBs(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "SET", "k", "db0")
	expect(t, c, OK, "SELECT", 15)
	expect(t, c, Nil, "GET", "k")
	expect(t, c, OK, "SET", "k", "db15")
	expect(t, c, 1, "DBSIZE")
	expect(t, c, Err("ERR DB index is out of range"), "SELECT", 16)
	expect(t, c, Err("ERR DB index is out of range"), "SELECT", -1)
	expect(t, c, Err("ERR invalid DB index"), "SELECT", "abc")
	expect(t, c, OK, "SELECT", 0)
	expect(t, c, "db0", "GET", "k")
	expect(t, c, OK, "FLUSHDB")
	expect(t, c, 0, "DBSIZE")
	expect(t, c, OK, "SELECT", 15)
	expect(t, c, 1, "DBSIZE")
	expect(t, c, OK, "FLUSHALL")
	expect(t, c, 0, "DBSIZE")
	expect(t, c, OK, "FLUSHALL", "ASYNC")
	expect(t, c, Err("ERR syntax error"), "FLUSHDB", "bogus")
}

func TestServerCommands(t *testing.T) {
	_, c := newSrv(t)
	info, ok := c.Do("INFO").(string)
	if !ok || !strings.Contains(info, "# Server") || !strings.Contains(info, "redis_version:") {
		t.Fatalf("INFO: %q", info)
	}
	c.Do("SET", "a", 1)
	ks, _ := c.Do("INFO", "keyspace").(string)
	if !strings.Contains(ks, "db0:keys=1,expires=0") {
		t.Fatalf("keyspace: %q", ks)
	}
	if strings.Contains(ks, "# Server") {
		t.Fatal("section filter ignored")
	}
	tm := c.Do("TIME").([]any)
	if len(tm) != 2 {
		t.Fatal(tm)
	}
	if n, ok := c.Do("COMMAND", "COUNT").(int64); !ok || n < 50 {
		t.Fatalf("COMMAND COUNT %v", n)
	}
	if v := c.Do("COMMAND").([]any); len(v) < 50 {
		t.Fatal("COMMAND list")
	}
	expect(t, c, OK, "CONFIG", "SET", "maxmemory", "100")
	expect(t, c, arr("maxmemory", "100"), "CONFIG", "GET", "maxmemory")
	if v := c.Do("CONFIG", "GET", "*max*").([]any); len(v) < 4 || len(v)%2 != 0 {
		t.Fatal(v)
	}
	expect(t, c, arr(), "CONFIG", "GET", "nonexistent-param")
	if _, ok := c.Do("LASTSAVE").(int64); !ok {
		t.Fatal("LASTSAVE")
	}
	expect(t, c, Err("ERR unknown subcommand 'zzz'. Try CONFIG HELP."), "CONFIG", "zzz")
	expect(t, c, OK, "CLIENT", "SETNAME", "bob")
	expect(t, c, "bob", "CLIENT", "GETNAME")
}

func TestOversizedInlineRequest(t *testing.T) {
	s, _ := newSrv(t)
	c := s.Client(t)
	c.Raw(strings.Repeat("A", 70000)) // no newline: must be rejected, not buffered forever
	if got := c.Read(); got != Err("ERR Protocol error: too big inline request") {
		t.Fatalf("got %#v", got)
	}
	if _, err := c.TryRead(time.Second); err == nil {
		t.Fatal("connection should be closed")
	}
	expect(t, s.Client(t), Simple("PONG"), "PING")
}
