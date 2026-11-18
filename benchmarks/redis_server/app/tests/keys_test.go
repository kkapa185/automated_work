package tests

import (
	"sort"
	"testing"
	"time"
)

func TestDelExistsType(t *testing.T) {
	_, c := newSrv(t)
	c.Do("MSET", "a", 1, "b", 2, "c", 3)
	expect(t, c, 2, "EXISTS", "a", "b", "zz")
	expect(t, c, 2, "EXISTS", "a", "a")
	expect(t, c, Simple("string"), "TYPE", "a")
	expect(t, c, Simple("none"), "TYPE", "nope")
	expect(t, c, 2, "DEL", "a", "b", "nope")
	expect(t, c, 1, "UNLINK", "c")
	expect(t, c, 0, "DBSIZE")
	expect(t, c, Err("ERR wrong number of arguments for 'del' command"), "DEL")
}

func TestKeysGlob(t *testing.T) {
	_, c := newSrv(t)
	for _, k := range []string{"hello", "hallo", "hxllo", "heello", "h[llo", "world", "a*b"} {
		c.Do("SET", k, 1)
	}
	check := func(pat string, want ...string) {
		t.Helper()
		got := strs(t, c.Do("KEYS", pat))
		sort.Strings(got)
		sort.Strings(want)
		if len(got) != len(want) {
			t.Fatalf("KEYS %q = %v want %v", pat, got, want)
		}
		for i := range got {
			if got[i] != want[i] {
				t.Fatalf("KEYS %q = %v want %v", pat, got, want)
			}
		}
	}
	check("*", "hello", "hallo", "hxllo", "heello", "h[llo", "world", "a*b")
	check("h?llo", "hello", "hallo", "hxllo", "h[llo")
	check("h*llo", "hello", "hallo", "hxllo", "heello", "h[llo")
	check("h[ae]llo", "hello", "hallo")
	check("h[^e]llo", "hallo", "hxllo", "h[llo")
	check("h[a-b]llo", "hallo")
	check(`h\[llo`, "h[llo")
	check(`a\*b`, "a*b")
	check("nomatch*")
	check("w*d", "world")
}

func TestScan(t *testing.T) {
	_, c := newSrv(t)
	want := map[string]bool{}
	for i := 0; i < 250; i++ {
		k := "key:" + string(rune('a'+i%26)) + "-" + time.Duration(i).String()
		c.Do("SET", k, i)
		want[k] = true
	}
	c.Do("SET", "other", "x")
	seen := map[string]bool{}
	cur := "0"
	iters := 0
	for {
		r := c.Do("SCAN", cur, "COUNT", 17).([]any)
		cur = r[0].(string)
		for _, k := range strs(t, r[1]) {
			seen[k] = true
		}
		iters++
		if cur == "0" {
			break
		}
		if iters > 1000 {
			t.Fatal("scan does not terminate")
		}
	}
	for k := range want {
		if !seen[k] {
			t.Fatalf("missing %s", k)
		}
	}
	if iters < 10 {
		t.Fatalf("COUNT ignored: %d iterations", iters)
	}
	// MATCH
	seen = map[string]bool{}
	cur = "0"
	for {
		r := c.Do("SCAN", cur, "MATCH", "oth*", "COUNT", 1000).([]any)
		cur = r[0].(string)
		for _, k := range strs(t, r[1]) {
			seen[k] = true
		}
		if cur == "0" {
			break
		}
	}
	if len(seen) != 1 || !seen["other"] {
		t.Fatalf("MATCH: %v", seen)
	}
	// TYPE
	r := c.Do("SCAN", 0, "COUNT", 1000, "TYPE", "string").([]any)
	if len(strs(t, r[1])) != 251 {
		t.Fatalf("TYPE string: %d", len(strs(t, r[1])))
	}
	r = c.Do("SCAN", 0, "COUNT", 1000, "TYPE", "hash").([]any)
	if len(strs(t, r[1])) != 0 || r[0] != "0" {
		t.Fatalf("TYPE hash: %v", r)
	}
	expect(t, c, Err("ERR invalid cursor"), "SCAN", "abc")
	expect(t, c, Err("ERR syntax error"), "SCAN", 0, "COUNT", 0)
	expect(t, c, Err("ERR value is not an integer or out of range"), "SCAN", 0, "COUNT", "x")
	expect(t, c, Err("ERR syntax error"), "SCAN", 0, "BOGUS", 1)
	expect(t, c, arr("0", arr()), "SCAN", 0, "MATCH", "zzz*", "COUNT", 10000)
}

func TestScanWithDeletionsDuringIteration(t *testing.T) {
	_, c := newSrv(t)
	for i := 0; i < 100; i++ {
		c.Do("SET", "k"+time.Duration(i).String(), 1)
	}
	keep := map[string]bool{}
	for i := 50; i < 100; i++ {
		keep["k"+time.Duration(i).String()] = true
	}
	seen := map[string]bool{}
	cur := "0"
	for step := 0; ; step++ {
		r := c.Do("SCAN", cur, "COUNT", 7).([]any)
		cur = r[0].(string)
		for _, k := range strs(t, r[1]) {
			seen[k] = true
		}
		if step < 50 { // delete the low half while scanning
			c.Do("DEL", "k"+time.Duration(step).String())
		}
		if cur == "0" {
			break
		}
	}
	for k := range keep {
		if !seen[k] {
			t.Fatalf("key %s present throughout was not returned", k)
		}
	}
}

func TestRename(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Err("ERR no such key"), "RENAME", "a", "b")
	c.Do("SET", "a", 1)
	c.Do("SET", "b", 2)
	c.Do("EXPIRE", "a", 100)
	expect(t, c, OK, "RENAME", "a", "b")
	expect(t, c, Nil, "GET", "a")
	expect(t, c, "1", "GET", "b")
	if ttl := c.Do("TTL", "b").(int64); ttl < 98 || ttl > 100 {
		t.Fatalf("ttl moved with rename: %d", ttl)
	}
	expect(t, c, OK, "RENAME", "b", "b")
	c.Do("SET", "x", 9)
	expect(t, c, 0, "RENAMENX", "b", "x")
	expect(t, c, 1, "RENAMENX", "b", "y")
	expect(t, c, "1", "GET", "y")
	expect(t, c, Err("ERR no such key"), "RENAMENX", "nope", "z")
	expect(t, c, 2, "DBSIZE")
}

func TestMove(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "k", "v")
	c.Do("EXPIRE", "k", 100)
	expect(t, c, 1, "MOVE", "k", 1)
	expect(t, c, Nil, "GET", "k")
	expect(t, c, 0, "MOVE", "k", 1)
	c.Do("SET", "k", "new")
	expect(t, c, 0, "MOVE", "k", 1)
	expect(t, c, Err("ERR source and destination objects are the same"), "MOVE", "k", 0)
	expect(t, c, Err("ERR DB index is out of range"), "MOVE", "k", 99)
	c.Do("SELECT", 1)
	expect(t, c, "v", "GET", "k")
	if ttl := c.Do("TTL", "k").(int64); ttl < 98 {
		t.Fatalf("ttl lost on MOVE: %d", ttl)
	}
}

func TestRandomKey(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Nil, "RANDOMKEY")
	c.Do("MSET", "a", 1, "b", 2, "c", 3)
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		seen[c.Do("RANDOMKEY").(string)] = true
	}
	if len(seen) != 3 {
		t.Fatalf("RANDOMKEY not random over keys: %v", seen)
	}
}

func TestExpireFamily(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 0, "EXPIRE", "none", 10)
	c.Do("SET", "k", "v")
	expect(t, c, -1, "TTL", "k")
	expect(t, c, -2, "TTL", "none")
	expect(t, c, -1, "PTTL", "k")
	expect(t, c, 1, "EXPIRE", "k", 100)
	if v := c.Do("TTL", "k").(int64); v != 100 && v != 99 {
		t.Fatal(v)
	}
	if v := c.Do("PTTL", "k").(int64); v < 99000 || v > 100000 {
		t.Fatal(v)
	}
	expect(t, c, 1, "PERSIST", "k")
	expect(t, c, 0, "PERSIST", "k")
	expect(t, c, -1, "TTL", "k")
	expect(t, c, 1, "PEXPIRE", "k", 50000)
	expect(t, c, 1, "PERSIST", "k")
	now := time.Now().Unix()
	expect(t, c, 1, "EXPIREAT", "k", now+1000)
	if v := c.Do("TTL", "k").(int64); v < 999 || v > 1000 {
		t.Fatal(v)
	}
	expect(t, c, now+1000, "EXPIRETIME", "k")
	expect(t, c, 1, "PEXPIREAT", "k", (now+2000)*1000)
	expect(t, c, (now+2000)*1000, "PEXPIRETIME", "k")
	// non-positive -> deleted
	expect(t, c, 1, "EXPIRE", "k", 0)
	expect(t, c, Nil, "GET", "k")
	c.Do("SET", "k", "v")
	expect(t, c, 1, "EXPIREAT", "k", 1)
	expect(t, c, 0, "EXISTS", "k")
	expect(t, c, Err("ERR value is not an integer or out of range"), "EXPIRE", "k", "abc")
	expect(t, c, Err("ERR value is not an integer or out of range"), "EXPIRE", "k", "+5")
	c.Do("SET", "k", "v")
	expect(t, c, Err("ERR invalid expire time in 'expire' command"), "EXPIRE", "k", "9223372036854775807")
	expect(t, c, Err("ERR invalid expire time in 'pexpire' command"), "PEXPIRE", "k", "9223372036854775807")
	expect(t, c, Err("ERR Unsupported option FOO"), "EXPIRE", "k", 10, "FOO")
}

func TestExpireOptions(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "k", "v")
	expect(t, c, 0, "EXPIRE", "k", 100, "XX") // no ttl
	expect(t, c, 0, "EXPIRE", "k", 100, "GT") // no ttl = infinite
	expect(t, c, 1, "EXPIRE", "k", 100, "NX")
	expect(t, c, 0, "EXPIRE", "k", 200, "NX")
	expect(t, c, 1, "EXPIRE", "k", 200, "XX")
	expect(t, c, 1, "EXPIRE", "k", 300, "GT")
	expect(t, c, 0, "EXPIRE", "k", 250, "GT")
	expect(t, c, 1, "EXPIRE", "k", 250, "LT")
	expect(t, c, 0, "EXPIRE", "k", 260, "LT")
	c.Do("PERSIST", "k")
	expect(t, c, 1, "EXPIRE", "k", 500, "LT") // no ttl = infinite, so LT sets
	expect(t, c, Err("ERR NX and XX, GT or LT options at the same time are not compatible"), "EXPIRE", "k", 1, "NX", "XX")
	expect(t, c, Err("ERR GT and LT options at the same time are not compatible"), "EXPIRE", "k", 1, "GT", "LT")
}

func TestLazyAndActiveExpiry(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "lazy", "v", "PX", 60)
	expect(t, c, "v", "GET", "lazy")
	time.Sleep(120 * time.Millisecond)
	expect(t, c, Nil, "GET", "lazy")
	expect(t, c, 0, "EXISTS", "lazy")
	// active expiry: never touched again, must vanish from DBSIZE by itself
	for i := 0; i < 100; i++ {
		c.Do("SET", "act"+time.Duration(i).String(), "v", "PX", 50)
	}
	c.Do("SET", "forever", "v")
	expect(t, c, 101, "DBSIZE")
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if c.Do("DBSIZE").(int64) == 1 {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	expect(t, c, 1, "DBSIZE")
	ks, _ := c.Do("INFO", "stats").(string)
	if ks == "" {
		t.Fatal("no stats")
	}
}

func TestExpiryAllAccessPaths(t *testing.T) {
	_, c := newSrv(t)
	mk := func() {
		c.Do("SET", "e", "1", "PX", 40)
		c.Do("SET", "keep", "1")
	}
	mk()
	time.Sleep(80 * time.Millisecond)
	expect(t, c, arr("keep"), "KEYS", "*")
	mk()
	time.Sleep(80 * time.Millisecond)
	expect(t, c, Err("ERR no such key"), "RENAME", "e", "z")
	mk()
	time.Sleep(80 * time.Millisecond)
	expect(t, c, arr("1", nil), "MGET", "keep", "e")
	mk()
	time.Sleep(80 * time.Millisecond)
	expect(t, c, 0, "COPY", "e", "z")
	mk()
	time.Sleep(80 * time.Millisecond)
	expect(t, c, -2, "TTL", "e")
	mk()
	time.Sleep(80 * time.Millisecond)
	expect(t, c, Simple("none"), "TYPE", "e")
	mk()
	time.Sleep(80 * time.Millisecond)
	r := c.Do("SCAN", 0, "COUNT", 100).([]any)
	if got := strs(t, r[1]); len(got) != 1 || got[0] != "keep" {
		t.Fatalf("scan returned expired keys: %v", got)
	}
}

func TestSetClearsTTLUnlessKeepTTL(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "k", "v", "EX", 100)
	c.Do("SET", "k", "v2")
	expect(t, c, -1, "TTL", "k")
	c.Do("SET", "k", "v", "EX", 100)
	c.Do("SET", "k", "v3", "KEEPTTL")
	if v := c.Do("TTL", "k").(int64); v < 98 {
		t.Fatal(v)
	}
	c.Do("APPEND", "k", "x")
	c.Do("SETRANGE", "k", 0, "z")
	if v := c.Do("TTL", "k").(int64); v < 98 {
		t.Fatalf("APPEND/SETRANGE must keep ttl: %d", v)
	}
	c.Do("GETSET", "k", "n")
	expect(t, c, -1, "TTL", "k")
}

func TestCopy(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "a", "v")
	c.Do("EXPIRE", "a", 100)
	expect(t, c, 1, "COPY", "a", "b")
	expect(t, c, "v", "GET", "b")
	if v := c.Do("TTL", "b").(int64); v < 98 {
		t.Fatalf("COPY keeps TTL: %d", v)
	}
	expect(t, c, 0, "COPY", "a", "b")
	c.Do("SET", "a", "v2")
	expect(t, c, 1, "COPY", "a", "b", "REPLACE")
	expect(t, c, "v2", "GET", "b")
	expect(t, c, -1, "TTL", "b")
	expect(t, c, 0, "COPY", "none", "x")
	expect(t, c, Err("ERR source and destination objects are the same"), "COPY", "a", "a")
	expect(t, c, 1, "COPY", "a", "a2", "DB", 3)
	expect(t, c, 1, "COPY", "a", "a", "DB", 4) // same name, other db is fine
	expect(t, c, Err("ERR DB index is out of range"), "COPY", "a", "q", "DB", 99)
	expect(t, c, Err("ERR syntax error"), "COPY", "a", "q", "BOGUS")
	c.Do("SELECT", 3)
	expect(t, c, "v2", "GET", "a2")
	// deep copy: modifying the copy leaves the source
	c.Do("SELECT", 0)
	c.Do("APPEND", "b", "!")
	expect(t, c, "v2", "GET", "a")
}

func TestObjectEncoding(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "i", 12345)
	c.Do("SET", "s", "hello")
	c.Do("SET", "l", string(make([]byte, 100)))
	c.Do("SET", "neg", "-7")
	c.Do("SET", "lead0", "007")
	expect(t, c, "int", "OBJECT", "ENCODING", "i")
	expect(t, c, "int", "OBJECT", "ENCODING", "neg")
	expect(t, c, "embstr", "OBJECT", "ENCODING", "s")
	expect(t, c, "embstr", "OBJECT", "ENCODING", "lead0")
	expect(t, c, "raw", "OBJECT", "ENCODING", "l")
	expect(t, c, Nil, "OBJECT", "ENCODING", "none")
	expect(t, c, Err("ERR wrong number of arguments for 'object|encoding' command"), "OBJECT", "ENCODING")
	expect(t, c, 2, "TOUCH", "i", "s", "nokey")
}
