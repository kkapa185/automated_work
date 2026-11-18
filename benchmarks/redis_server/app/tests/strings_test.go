package tests

import (
	"testing"
	"time"
)

func TestGetSetBasics(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Nil, "GET", "k")
	expect(t, c, OK, "SET", "k", "v")
	expect(t, c, "v", "GET", "k")
	expect(t, c, OK, "SET", "k", "v2")
	expect(t, c, "v2", "GET", "k")
	expect(t, c, Err("ERR wrong number of arguments for 'set' command"), "SET", "k")
	expect(t, c, Err("ERR syntax error"), "SET", "k", "v", "BOGUS")
}

func TestSetOptions(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Nil, "SET", "k", "v", "XX")
	expect(t, c, OK, "SET", "k", "v", "NX")
	expect(t, c, Nil, "SET", "k", "w", "NX")
	expect(t, c, OK, "SET", "k", "w", "XX")
	expect(t, c, "w", "GET", "k")
	// GET option
	expect(t, c, "w", "SET", "k", "x", "GET")
	expect(t, c, Nil, "SET", "fresh", "x", "GET")
	expect(t, c, "x", "SET", "k", "y", "NX", "GET") // NX fails; returns old value
	expect(t, c, "x", "GET", "k")
	expect(t, c, Nil, "SET", "nokey", "y", "XX", "GET")
	// expire options
	expect(t, c, OK, "SET", "e", "v", "EX", 100)
	if v := c.Do("TTL", "e").(int64); v < 99 || v > 100 {
		t.Fatal(v)
	}
	expect(t, c, OK, "SET", "e", "v", "PX", 100000)
	if v := c.Do("PTTL", "e").(int64); v < 99000 || v > 100000 {
		t.Fatal(v)
	}
	at := time.Now().Unix() + 500
	expect(t, c, OK, "SET", "e", "v", "EXAT", at)
	expect(t, c, at, "EXPIRETIME", "e")
	expect(t, c, OK, "SET", "e", "v", "PXAT", at*1000+250)
	expect(t, c, at*1000+250, "PEXPIRETIME", "e")
	// errors
	expect(t, c, Err("ERR syntax error"), "SET", "k", "v", "NX", "XX")
	expect(t, c, Err("ERR syntax error"), "SET", "k", "v", "EX", 10, "PX", 100)
	expect(t, c, Err("ERR syntax error"), "SET", "k", "v", "EX", 10, "KEEPTTL")
	expect(t, c, Err("ERR syntax error"), "SET", "k", "v", "KEEPTTL", "EX", 10)
	expect(t, c, Err("ERR syntax error"), "SET", "k", "v", "EX")
	expect(t, c, Err("ERR value is not an integer or out of range"), "SET", "k", "v", "EX", "abc")
	expect(t, c, Err("ERR invalid expire time in 'set' command"), "SET", "k", "v", "EX", 0)
	expect(t, c, Err("ERR invalid expire time in 'set' command"), "SET", "k", "v", "PX", -5)
	expect(t, c, Err("ERR invalid expire time in 'set' command"), "SET", "k", "v", "EX", "9223372036854775807")
	// past absolute time: key is gone right away
	expect(t, c, OK, "SET", "gone", "v", "PXAT", 1)
	expect(t, c, 0, "EXISTS", "gone")
	// expiry actually happens
	c.Do("SET", "t", "v", "PX", 50)
	time.Sleep(100 * time.Millisecond)
	expect(t, c, Nil, "GET", "t")
}

func TestSetNXSetExPSetEx(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 1, "SETNX", "k", "a")
	expect(t, c, 0, "SETNX", "k", "b")
	expect(t, c, "a", "GET", "k")
	expect(t, c, OK, "SETEX", "e", 100, "v")
	if v := c.Do("TTL", "e").(int64); v < 99 {
		t.Fatal(v)
	}
	expect(t, c, OK, "PSETEX", "p", 5000, "v")
	if v := c.Do("PTTL", "p").(int64); v < 4000 || v > 5000 {
		t.Fatal(v)
	}
	expect(t, c, Err("ERR invalid expire time in 'setex' command"), "SETEX", "e", 0, "v")
	expect(t, c, Err("ERR invalid expire time in 'psetex' command"), "PSETEX", "e", -1, "v")
	expect(t, c, Err("ERR value is not an integer or out of range"), "SETEX", "e", "x", "v")
}

func TestMGetMSet(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, OK, "MSET", "a", 1, "b", 2)
	expect(t, c, arr("1", "2", nil), "MGET", "a", "b", "c")
	expect(t, c, Err("ERR wrong number of arguments for 'mset' command"), "MSET", "a", 1, "b")
	expect(t, c, Err("ERR wrong number of arguments for 'mget' command"), "MGET")
	expect(t, c, 0, "MSETNX", "a", 9, "z", 9)
	expect(t, c, Nil, "GET", "z") // atomic: nothing set
	expect(t, c, 1, "MSETNX", "x", 1, "y", 2)
	expect(t, c, arr("1", "2"), "MGET", "x", "y")
	expect(t, c, Err("ERR wrong number of arguments for 'msetnx' command"), "MSETNX", "x", 1, "y")
}

func TestGetSetGetDelGetEx(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Nil, "GETSET", "k", "a")
	expect(t, c, "a", "GETSET", "k", "b")
	expect(t, c, "b", "GETDEL", "k")
	expect(t, c, Nil, "GETDEL", "k")
	expect(t, c, 0, "EXISTS", "k")
	c.Do("SET", "k", "v")
	expect(t, c, "v", "GETEX", "k")
	expect(t, c, -1, "TTL", "k")
	expect(t, c, "v", "GETEX", "k", "EX", 100)
	if v := c.Do("TTL", "k").(int64); v < 99 {
		t.Fatal(v)
	}
	expect(t, c, "v", "GETEX", "k", "PERSIST")
	expect(t, c, -1, "TTL", "k")
	expect(t, c, "v", "GETEX", "k", "PX", 100000)
	if v := c.Do("PTTL", "k").(int64); v < 99000 {
		t.Fatal(v)
	}
	expect(t, c, "v", "GETEX", "k", "PXAT", 1) // past: returns value, then deleted
	expect(t, c, 0, "EXISTS", "k")
	expect(t, c, Nil, "GETEX", "missing", "EX", 10)
	c.Do("SET", "k", "v")
	expect(t, c, Err("ERR syntax error"), "GETEX", "k", "EX", 10, "PERSIST")
	expect(t, c, Err("ERR syntax error"), "GETEX", "k", "FOO")
	expect(t, c, Err("ERR invalid expire time in 'getex' command"), "GETEX", "k", "EX", 0)
}

func TestAppendStrlen(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 0, "STRLEN", "k")
	expect(t, c, 5, "APPEND", "k", "hello")
	expect(t, c, 11, "APPEND", "k", " world")
	expect(t, c, "hello world", "GET", "k")
	expect(t, c, 11, "STRLEN", "k")
	expect(t, c, 0, "APPEND", "e", "")
	expect(t, c, "", "GET", "e")
}

func TestIncrDecr(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 1, "INCR", "n")
	expect(t, c, 2, "INCR", "n")
	expect(t, c, 1, "DECR", "n")
	expect(t, c, 11, "INCRBY", "n", 10)
	expect(t, c, 1, "DECRBY", "n", 10)
	expect(t, c, -9, "DECRBY", "n", 10)
	expect(t, c, "-9", "GET", "n")
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCRBY", "n", "abc")
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCRBY", "n", "1.5")
	c.Do("SET", "s", "abc")
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCR", "s")
	c.Do("SET", "sp", " 1")
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCR", "sp")
	c.Do("SET", "plus", "+1")
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCR", "plus")
	// overflow
	c.Do("SET", "max", "9223372036854775807")
	expect(t, c, Err("ERR increment or decrement would overflow"), "INCR", "max")
	expect(t, c, Err("ERR increment or decrement would overflow"), "INCRBY", "max", 1)
	expect(t, c, "9223372036854775807", "GET", "max")
	expect(t, c, 9223372036854775806, "DECR", "max")
	c.Do("SET", "min", "-9223372036854775808")
	expect(t, c, Err("ERR increment or decrement would overflow"), "DECR", "min")
	expect(t, c, Err("ERR decrement would overflow"), "DECRBY", "min", "-9223372036854775808")
	expect(t, c, Err("ERR increment or decrement would overflow"), "DECRBY", "min", 1)
	c.Do("SET", "big", "9223372036854775808")
	expect(t, c, Err("ERR value is not an integer or out of range"), "INCR", "big")
	// TTL survives INCR
	c.Do("SET", "t", 1, "EX", 100)
	c.Do("INCR", "t")
	if v := c.Do("TTL", "t").(int64); v < 98 {
		t.Fatal(v)
	}
}

func TestIncrByFloat(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, "10.5", "INCRBYFLOAT", "f", "10.5")
	expect(t, c, "10.6", "INCRBYFLOAT", "f", "0.1")
	expect(t, c, "-4.4", "INCRBYFLOAT", "f", "-15")
	expect(t, c, "-4.4", "GET", "f")
	c.Do("SET", "e", "5.0e3")
	expect(t, c, "5200", "INCRBYFLOAT", "e", "200")
	// long-double arithmetic: 0.1+0.2 prints as 0.3 (not 0.30000000000000004)
	expect(t, c, "0.1", "INCRBYFLOAT", "z", "0.1")
	expect(t, c, "0.3", "INCRBYFLOAT", "z", "0.2")
	expect(t, c, "3", "INCRBYFLOAT", "int", "3")
	expect(t, c, "-0.5", "INCRBYFLOAT", "neg", "-0.5")
}

func TestIncrByFloatErrors(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "s", "abc")
	expect(t, c, Err("ERR value is not a valid float"), "INCRBYFLOAT", "s", 1)
	expect(t, c, Err("ERR value is not a valid float"), "INCRBYFLOAT", "k", "abc")
	expect(t, c, Err("ERR value is not a valid float"), "INCRBYFLOAT", "k", "nan")
	expect(t, c, Err("ERR increment would produce NaN or Infinity"), "INCRBYFLOAT", "k", "inf")
	expect(t, c, Err("ERR increment would produce NaN or Infinity"), "INCRBYFLOAT", "k", "-inf")
	expect(t, c, Err("ERR value is not a valid float"), "INCRBYFLOAT", "k", "1e5000")
}

func TestGetRange(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "k", "This is a string")
	expect(t, c, "This", "GETRANGE", "k", 0, 3)
	expect(t, c, "ing", "GETRANGE", "k", -3, -1)
	expect(t, c, "This is a string", "GETRANGE", "k", 0, -1)
	expect(t, c, "string", "GETRANGE", "k", 10, 100)
	expect(t, c, "", "GETRANGE", "k", 5, 2)
	expect(t, c, "", "GETRANGE", "k", -1, -3)
	expect(t, c, "T", "GETRANGE", "k", -100, 0)
	expect(t, c, "", "GETRANGE", "k", 100, 200)
	expect(t, c, "", "GETRANGE", "nokey", 0, -1)
	expect(t, c, "This", "SUBSTR", "k", 0, 3)
	expect(t, c, Err("ERR value is not an integer or out of range"), "GETRANGE", "k", "a", 1)
}

func TestSetRange(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "k", "Hello World")
	expect(t, c, 11, "SETRANGE", "k", 6, "Redis")
	expect(t, c, "Hello Redis", "GET", "k")
	expect(t, c, 8, "SETRANGE", "pad", 5, "abc")
	expect(t, c, "\x00\x00\x00\x00\x00abc", "GET", "pad")
	expect(t, c, 0, "SETRANGE", "none", 0, "")
	expect(t, c, 0, "EXISTS", "none")
	expect(t, c, 11, "SETRANGE", "k", 0, "")
	expect(t, c, 13, "SETRANGE", "k", 11, "!!")
	expect(t, c, Err("ERR offset is out of range"), "SETRANGE", "k", -1, "x")
	expect(t, c, Err("ERR string exceeds maximum allowed size (proto-max-bulk-len)"), "SETRANGE", "k", 536870912, "x")
	expect(t, c, Err("ERR value is not an integer or out of range"), "SETRANGE", "k", "x", "x")
}
