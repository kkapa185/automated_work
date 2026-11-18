package tests

import (
	"sort"
	"testing"
)

func TestHashBasics(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 2, "HSET", "h", "a", 1, "b", 2)
	expect(t, c, 1, "HSET", "h", "a", 10, "c", 3) // a updated (not counted), c new
	expect(t, c, "10", "HGET", "h", "a")
	expect(t, c, Nil, "HGET", "h", "zz")
	expect(t, c, Nil, "HGET", "nokey", "a")
	expect(t, c, 3, "HLEN", "h")
	expect(t, c, 0, "HLEN", "nokey")
	expect(t, c, 1, "HEXISTS", "h", "b")
	expect(t, c, 0, "HEXISTS", "h", "zz")
	expect(t, c, arr("10", nil, "3"), "HMGET", "h", "a", "zz", "c")
	expect(t, c, arr(nil, nil), "HMGET", "nokey", "a", "b")
	expect(t, c, arr("a", "10", "b", "2", "c", "3"), "HGETALL", "h") // insertion order
	expect(t, c, arr("a", "b", "c"), "HKEYS", "h")
	expect(t, c, arr("10", "2", "3"), "HVALS", "h")
	expect(t, c, arr(), "HGETALL", "nokey")
	expect(t, c, OK, "HMSET", "h", "d", 4, "e", 5)
	expect(t, c, 5, "HLEN", "h")
	expect(t, c, 2, "HDEL", "h", "a", "zz", "b")
	expect(t, c, arr("c", "d", "e"), "HKEYS", "h")
	expect(t, c, 3, "HDEL", "h", "c", "d", "e")
	expect(t, c, 0, "EXISTS", "h")
	expect(t, c, 0, "HDEL", "nokey", "a")
	expect(t, c, Err("ERR wrong number of arguments for 'hset' command"), "HSET", "h", "a")
	expect(t, c, Err("ERR wrong number of arguments for 'hset' command"), "HSET", "h", "a", 1, "b")
	expect(t, c, Err("ERR wrong number of arguments for 'hmset' command"), "HMSET", "h", "a")
	expect(t, c, Err("ERR wrong number of arguments for 'hget' command"), "HGET", "h")
}

func TestHashSetNXStrlen(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 1, "HSETNX", "h", "f", "hello")
	expect(t, c, 0, "HSETNX", "h", "f", "other")
	expect(t, c, "hello", "HGET", "h", "f")
	expect(t, c, 5, "HSTRLEN", "h", "f")
	expect(t, c, 0, "HSTRLEN", "h", "zz")
	expect(t, c, 0, "HSTRLEN", "nokey", "f")
}

func TestHashIncr(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 5, "HINCRBY", "h", "n", 5)
	expect(t, c, 3, "HINCRBY", "h", "n", -2)
	expect(t, c, "3", "HGET", "h", "n")
	c.Do("HSET", "h", "s", "abc")
	expect(t, c, Err("ERR hash value is not an integer"), "HINCRBY", "h", "s", 1)
	expect(t, c, Err("ERR value is not an integer or out of range"), "HINCRBY", "h", "n", "x")
	c.Do("HSET", "h", "max", "9223372036854775807")
	expect(t, c, Err("ERR increment or decrement would overflow"), "HINCRBY", "h", "max", 1)
	expect(t, c, "10.5", "HINCRBYFLOAT", "h", "f", "10.5")
	expect(t, c, "10.6", "HINCRBYFLOAT", "h", "f", "0.1")
	expect(t, c, "5200", "HINCRBYFLOAT", "h", "g", "5.2e3")
	expect(t, c, Err("ERR hash value is not a float"), "HINCRBYFLOAT", "h", "s", 1)
	expect(t, c, Err("ERR value is not a valid float"), "HINCRBYFLOAT", "h", "f", "abc")
	expect(t, c, Err("ERR increment would produce NaN or Infinity"), "HINCRBYFLOAT", "h", "f", "inf")
}

func TestHRandField(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Nil, "HRANDFIELD", "nokey")
	expect(t, c, arr(), "HRANDFIELD", "nokey", 3)
	c.Do("HSET", "h", "a", 1, "b", 2, "c", 3)
	seen := map[string]bool{}
	for i := 0; i < 100; i++ {
		seen[c.Do("HRANDFIELD", "h").(string)] = true
	}
	if len(seen) != 3 {
		t.Fatalf("not random: %v", seen)
	}
	got := strs(t, c.Do("HRANDFIELD", "h", 10)) // distinct, capped at size
	sort.Strings(got)
	if len(got) != 3 || got[0] != "a" || got[2] != "c" {
		t.Fatal(got)
	}
	got = strs(t, c.Do("HRANDFIELD", "h", 2))
	if len(got) != 2 || got[0] == got[1] {
		t.Fatalf("distinct: %v", got)
	}
	got = strs(t, c.Do("HRANDFIELD", "h", -10)) // repetition allowed, exact count
	if len(got) != 10 {
		t.Fatal(got)
	}
	expect(t, c, arr(), "HRANDFIELD", "h", 0)
	wv := strs(t, c.Do("HRANDFIELD", "h", 3, "WITHVALUES"))
	if len(wv) != 6 {
		t.Fatal(wv)
	}
	want := map[string]string{"a": "1", "b": "2", "c": "3"}
	for i := 0; i < 6; i += 2 {
		if want[wv[i]] != wv[i+1] {
			t.Fatalf("pair mismatch %v", wv)
		}
	}
	if n := len(c.Do("HRANDFIELD", "h", -5, "WITHVALUES").([]any)); n != 10 {
		t.Fatal(n)
	}
	expect(t, c, Err("ERR syntax error"), "HRANDFIELD", "h", 2, "WITHVALS")
	expect(t, c, Err("ERR value is not an integer or out of range"), "HRANDFIELD", "h", "x")
}

func TestHashManyFieldsWithDeletes(t *testing.T) {
	_, c := newSrv(t)
	for i := 0; i < 500; i++ {
		c.Send("HSET", "h", i, i*2)
	}
	for i := 0; i < 500; i++ {
		c.Read()
	}
	for i := 0; i < 500; i += 2 {
		c.Send("HDEL", "h", i)
	}
	for i := 0; i < 250; i++ {
		c.Read()
	}
	expect(t, c, 250, "HLEN", "h")
	expect(t, c, "6", "HGET", "h", 3)
	expect(t, c, Nil, "HGET", "h", 4)
	all := c.Do("HGETALL", "h").([]any)
	if len(all) != 500 || all[0] != "1" || all[1] != "2" || all[498] != "499" {
		t.Fatalf("order after deletions broken: %v ...", all[:4])
	}
}
