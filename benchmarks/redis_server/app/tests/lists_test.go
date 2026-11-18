package tests

import (
	"testing"
)

const wrongType = Err("WRONGTYPE Operation against a key holding the wrong kind of value")

func TestWrongTypeFromTicket(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a")
	expect(t, c, wrongType, "GET", "l")
	expect(t, c, wrongType, "INCR", "l")
	c.Do("SET", "s", "x")
	expect(t, c, wrongType, "LPUSH", "s", "a")
	expect(t, c, wrongType, "LLEN", "s")
	expect(t, c, wrongType, "HGET", "s", "f")
	expect(t, c, wrongType, "SADD", "s", "a")
	c.Do("HSET", "h", "f", "v")
	expect(t, c, wrongType, "LPOP", "h")
	expect(t, c, wrongType, "SMEMBERS", "h")
	expect(t, c, wrongType, "APPEND", "h", "x")
	c.Do("SADD", "st", "m")
	expect(t, c, wrongType, "HGETALL", "st")
	expect(t, c, wrongType, "RPUSH", "st", "x")
	expect(t, c, Simple("list"), "TYPE", "l")
	expect(t, c, Simple("hash"), "TYPE", "h")
	expect(t, c, Simple("set"), "TYPE", "st")
	// SET overwrites any type
	expect(t, c, OK, "SET", "l", "now-string")
	expect(t, c, Simple("string"), "TYPE", "l")
	expect(t, c, wrongType, "SET", "h", "x", "GET")
}

func TestPushPopRange(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 3, "RPUSH", "l", "a", "b", "c")
	expect(t, c, 5, "LPUSH", "l", "x", "y") // list: y x a b c
	expect(t, c, arr("y", "x", "a", "b", "c"), "LRANGE", "l", 0, -1)
	expect(t, c, arr("x", "a"), "LRANGE", "l", 1, 2)
	expect(t, c, arr("b", "c"), "LRANGE", "l", -2, -1)
	expect(t, c, arr(), "LRANGE", "l", 3, 1)
	expect(t, c, arr(), "LRANGE", "l", 10, 20)
	expect(t, c, arr("y", "x", "a", "b", "c"), "LRANGE", "l", -100, 100)
	expect(t, c, arr(), "LRANGE", "nokey", 0, -1)
	expect(t, c, 5, "LLEN", "l")
	expect(t, c, 0, "LLEN", "nokey")
	expect(t, c, "y", "LPOP", "l")
	expect(t, c, "c", "RPOP", "l")
	expect(t, c, arr("x", "a"), "LPOP", "l", 2)
	expect(t, c, arr("b"), "RPOP", "l", 10)
	expect(t, c, 0, "EXISTS", "l") // emptied list is removed
	expect(t, c, Nil, "LPOP", "l")
	expect(t, c, Nil, "RPOP", "l", 2)
	c.Do("RPUSH", "l", "a")
	expect(t, c, arr(), "LPOP", "l", 0)
	expect(t, c, Err("ERR value is out of range, must be positive"), "LPOP", "l", -1)
	expect(t, c, Err("ERR value is out of range, must be positive"), "LPOP", "l", "x")
	expect(t, c, Err("ERR wrong number of arguments for 'lpop' command"), "LPOP", "l", 1, 2)
	// push order: LPUSH a b c => c b a
	c.Do("LPUSH", "o", "a", "b", "c")
	expect(t, c, arr("c", "b", "a"), "LRANGE", "o", 0, -1)
}

func TestPushX(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 0, "LPUSHX", "l", "a")
	expect(t, c, 0, "RPUSHX", "l", "a")
	expect(t, c, 0, "EXISTS", "l")
	c.Do("RPUSH", "l", "m")
	expect(t, c, 2, "LPUSHX", "l", "a")
	expect(t, c, 4, "RPUSHX", "l", "b", "c")
	expect(t, c, arr("a", "m", "b", "c"), "LRANGE", "l", 0, -1)
}

func TestLIndexLSet(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a", "b", "c")
	expect(t, c, "a", "LINDEX", "l", 0)
	expect(t, c, "c", "LINDEX", "l", -1)
	expect(t, c, Nil, "LINDEX", "l", 3)
	expect(t, c, Nil, "LINDEX", "l", -4)
	expect(t, c, Nil, "LINDEX", "nokey", 0)
	expect(t, c, Err("ERR value is not an integer or out of range"), "LINDEX", "l", "x")
	expect(t, c, OK, "LSET", "l", 1, "B")
	expect(t, c, OK, "LSET", "l", -1, "C")
	expect(t, c, arr("a", "B", "C"), "LRANGE", "l", 0, -1)
	expect(t, c, Err("ERR index out of range"), "LSET", "l", 3, "x")
	expect(t, c, Err("ERR index out of range"), "LSET", "l", -4, "x")
	expect(t, c, Err("ERR no such key"), "LSET", "nokey", 0, "x")
}

func TestLInsertLRemLTrim(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a", "c")
	expect(t, c, 3, "LINSERT", "l", "BEFORE", "c", "b")
	expect(t, c, 4, "LINSERT", "l", "after", "c", "d")
	expect(t, c, arr("a", "b", "c", "d"), "LRANGE", "l", 0, -1)
	expect(t, c, -1, "LINSERT", "l", "BEFORE", "zz", "x")
	expect(t, c, 0, "LINSERT", "nokey", "BEFORE", "a", "x")
	expect(t, c, Err("ERR syntax error"), "LINSERT", "l", "MIDDLE", "a", "x")

	c.Do("DEL", "l")
	c.Do("RPUSH", "l", "a", "b", "a", "c", "a")
	expect(t, c, 2, "LREM", "l", 2, "a")
	expect(t, c, arr("b", "c", "a"), "LRANGE", "l", 0, -1)
	c.Do("RPUSH", "l", "a", "a")
	expect(t, c, 1, "LREM", "l", -1, "a")
	expect(t, c, arr("b", "c", "a", "a"), "LRANGE", "l", 0, -1)
	expect(t, c, 2, "LREM", "l", 0, "a")
	expect(t, c, 0, "LREM", "l", 0, "zzz")
	expect(t, c, 0, "LREM", "nokey", 0, "a")
	expect(t, c, 1, "LREM", "l", 0, "b")
	expect(t, c, 1, "LREM", "l", 5, "c")
	expect(t, c, 0, "EXISTS", "l")

	c.Do("RPUSH", "t", 1, 2, 3, 4, 5)
	expect(t, c, OK, "LTRIM", "t", 1, -2)
	expect(t, c, arr("2", "3", "4"), "LRANGE", "t", 0, -1)
	expect(t, c, OK, "LTRIM", "t", 0, 0)
	expect(t, c, arr("2"), "LRANGE", "t", 0, -1)
	expect(t, c, OK, "LTRIM", "t", 5, 10) // empty -> key removed
	expect(t, c, 0, "EXISTS", "t")
	expect(t, c, OK, "LTRIM", "nokey", 0, 1)
	c.Do("RPUSH", "t", 1, 2, 3)
	expect(t, c, OK, "LTRIM", "t", 2, 1)
	expect(t, c, 0, "EXISTS", "t")
}

func TestLPos(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a", "b", "c", "1", "2", "3", "c", "c")
	expect(t, c, 2, "LPOS", "l", "c")
	expect(t, c, 6, "LPOS", "l", "c", "RANK", 2)
	expect(t, c, 7, "LPOS", "l", "c", "RANK", -1)
	expect(t, c, 6, "LPOS", "l", "c", "RANK", -2)
	expect(t, c, Nil, "LPOS", "l", "c", "RANK", 4)
	expect(t, c, arr(2, 6, 7), "LPOS", "l", "c", "COUNT", 0)
	expect(t, c, arr(2, 6), "LPOS", "l", "c", "COUNT", 2)
	expect(t, c, arr(7, 6, 2), "LPOS", "l", "c", "COUNT", 0, "RANK", -1)
	expect(t, c, arr(2), "LPOS", "l", "c", "COUNT", 0, "MAXLEN", 5)
	expect(t, c, Nil, "LPOS", "l", "c", "MAXLEN", 2)
	expect(t, c, Nil, "LPOS", "l", "zzz")
	expect(t, c, arr(), "LPOS", "l", "zzz", "COUNT", 0)
	expect(t, c, Nil, "LPOS", "nokey", "a")
	expect(t, c, Err("ERR RANK can't be zero: use 1 to start from the first match, 2 from the second ... or use negative to start from the end of the list"), "LPOS", "l", "a", "RANK", 0)
	expect(t, c, Err("ERR COUNT can't be negative"), "LPOS", "l", "a", "COUNT", -1)
	expect(t, c, Err("ERR MAXLEN can't be negative"), "LPOS", "l", "a", "MAXLEN", -1)
	expect(t, c, Err("ERR syntax error"), "LPOS", "l", "a", "BOGUS", 1)
}

func TestRPopLPushLMove(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "src", "a", "b", "c")
	expect(t, c, "c", "RPOPLPUSH", "src", "dst")
	expect(t, c, arr("c"), "LRANGE", "dst", 0, -1)
	expect(t, c, "b", "RPOPLPUSH", "src", "dst")
	expect(t, c, arr("b", "c"), "LRANGE", "dst", 0, -1)
	// rotation on the same list
	expect(t, c, "c", "RPOPLPUSH", "dst", "dst")
	expect(t, c, arr("c", "b"), "LRANGE", "dst", 0, -1)
	expect(t, c, Nil, "RPOPLPUSH", "nokey", "dst")

	c.Do("DEL", "src", "dst")
	c.Do("RPUSH", "src", 1, 2, 3)
	expect(t, c, "1", "LMOVE", "src", "dst", "LEFT", "RIGHT")
	expect(t, c, "3", "LMOVE", "src", "dst", "right", "left")
	expect(t, c, "2", "LMOVE", "src", "dst", "LEFT", "LEFT")
	expect(t, c, arr("2", "3", "1"), "LRANGE", "dst", 0, -1)
	expect(t, c, 0, "EXISTS", "src")
	expect(t, c, Nil, "LMOVE", "src", "dst", "LEFT", "LEFT")
	expect(t, c, Err("ERR syntax error"), "LMOVE", "dst", "x", "UP", "LEFT")
	// WRONGTYPE destination must not lose the element
	c.Do("SET", "str", "x")
	expect(t, c, wrongType, "LMOVE", "dst", "str", "LEFT", "LEFT")
	expect(t, c, 3, "LLEN", "dst")
	expect(t, c, wrongType, "RPOPLPUSH", "dst", "str")
	expect(t, c, 3, "LLEN", "dst")
}

func TestEncodings(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a")
	expect(t, c, "listpack", "OBJECT", "ENCODING", "l")
	big := string(make([]byte, 10000))
	c.Do("RPUSH", "l2", big)
	expect(t, c, "quicklist", "OBJECT", "ENCODING", "l2")
	c.Do("HSET", "h", "f", "v")
	expect(t, c, "listpack", "OBJECT", "ENCODING", "h")
	c.Do("HSET", "h", "f", big[:100])
	expect(t, c, "hashtable", "OBJECT", "ENCODING", "h")
	c.Do("SADD", "i", 1, 2, 3)
	expect(t, c, "intset", "OBJECT", "ENCODING", "i")
	c.Do("SADD", "i", "a")
	expect(t, c, "listpack", "OBJECT", "ENCODING", "i")
	for n := 0; n < 200; n++ {
		c.Do("SADD", "i", "member"+string(rune('A'+n%26))+string(rune('a'+n/26)))
	}
	expect(t, c, "hashtable", "OBJECT", "ENCODING", "i")
	for n := 0; n < 129; n++ {
		c.Do("HSET", "h2", "f"+string(rune('A'+n%26))+string(rune('a'+n/26)), n)
	}
	expect(t, c, "hashtable", "OBJECT", "ENCODING", "h2")
	c.Do("SADD", "i2", 1)
	for n := 0; n < 600; n++ {
		c.Do("SADD", "i2", 1000+n)
	}
	expect(t, c, "hashtable", "OBJECT", "ENCODING", "i2")
}

func TestCopyCollections(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a", "b")
	c.Do("HSET", "h", "f", "v")
	c.Do("SADD", "s", "x", "y")
	for _, k := range []string{"l", "h", "s"} {
		expect(t, c, 1, "COPY", k, k+"2")
	}
	c.Do("RPUSH", "l2", "c")
	c.Do("HSET", "h2", "g", "w")
	c.Do("SADD", "s2", "z")
	expect(t, c, arr("a", "b"), "LRANGE", "l", 0, -1)
	expect(t, c, 1, "HLEN", "h")
	expect(t, c, 2, "SCARD", "s")
	expect(t, c, 3, "LLEN", "l2")
	expect(t, c, 2, "HLEN", "h2")
	expect(t, c, 3, "SCARD", "s2")
}

func TestRenameCollections(t *testing.T) {
	_, c := newSrv(t)
	c.Do("RPUSH", "l", "a")
	expect(t, c, OK, "RENAME", "l", "m")
	expect(t, c, arr("a"), "LRANGE", "m", 0, -1)
	expect(t, c, Simple("list"), "TYPE", "m")
}
