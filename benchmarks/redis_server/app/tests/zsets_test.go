package tests

import (
	"testing"
	"time"
)

func zfill(c *C) {
	c.Do("ZADD", "z", 1, "one", 2, "two", 3, "three")
}

func TestZAddBasics(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 1, "ZADD", "z", 1, "one")
	expect(t, c, 2, "ZADD", "z", 1, "uno", 2, "two")
	expect(t, c, 0, "ZADD", "z", 5, "one") // update, not added
	expect(t, c, 3, "ZCARD", "z")
	expect(t, c, "5", "ZSCORE", "z", "one")
	expect(t, c, Nil, "ZSCORE", "z", "none")
	expect(t, c, Nil, "ZSCORE", "nokey", "m")
	expect(t, c, arr("uno", "1", "two", "2", "one", "5"), "ZRANGE", "z", 0, -1, "WITHSCORES")
	expect(t, c, 0, "ZCARD", "nokey")
	expect(t, c, Err("ERR value is not a valid float"), "ZADD", "z", "abc", "m")
	expect(t, c, Err("ERR value is not a valid float"), "ZADD", "z", "nan", "m")
	expect(t, c, Err("ERR syntax error"), "ZADD", "z", 1, "a", 2)
	expect(t, c, Err("ERR wrong number of arguments for 'zadd' command"), "ZADD", "z", 1)
	expect(t, c, 1, "ZADD", "zi", "inf", "a")
	expect(t, c, "inf", "ZSCORE", "zi", "a")
	c.Do("ZADD", "zi", "-inf", "b")
	expect(t, c, "-inf", "ZSCORE", "zi", "b")
	c.Do("SET", "str", "x")
	expect(t, c, wrongType, "ZADD", "str", 1, "a")
}

func TestScoreFormatting(t *testing.T) {
	_, c := newSrv(t)
	c.Do("ZADD", "z", 1.5, "a", 3, "b", "inf", "c", "-inf", "d", 0, "e", -2.25, "f", 100, "g", 0.1, "h")
	for m, want := range map[string]string{"a": "1.5", "b": "3", "c": "inf", "d": "-inf", "e": "0", "f": "-2.25", "g": "100", "h": "0.1"} {
		expect(t, c, want, "ZSCORE", "z", m)
	}
	expect(t, c, "1.5", "ZINCRBY", "fm", 1.5, "x")
	expect(t, c, "3", "ZINCRBY", "fm", 1.5, "x")
	expect(t, c, "4.5", "ZINCRBY", "fm", 1.5, "x")
}

func TestZAddFlags(t *testing.T) {
	_, c := newSrv(t)
	c.Do("ZADD", "z", 10, "a", 20, "b")
	expect(t, c, 0, "ZADD", "z", "NX", 99, "a")
	expect(t, c, "10", "ZSCORE", "z", "a")
	expect(t, c, 1, "ZADD", "z", "NX", 30, "c")
	expect(t, c, 0, "ZADD", "z", "XX", 99, "zz")
	expect(t, c, Nil, "ZSCORE", "z", "zz")
	expect(t, c, 0, "ZADD", "z", "XX", 11, "a")
	expect(t, c, 1, "ZADD", "z", "XX", "CH", 12, "a")
	expect(t, c, 0, "ZADD", "z", "GT", 5, "a") // lower: no update
	expect(t, c, "12", "ZSCORE", "z", "a")
	expect(t, c, 1, "ZADD", "z", "GT", "CH", 50, "a")
	expect(t, c, 0, "ZADD", "z", "LT", 60, "a")
	expect(t, c, 1, "ZADD", "z", "LT", "CH", 1, "a")
	expect(t, c, 2, "ZADD", "z", "GT", "CH", 100, "b", 5, "new") // update + add counted
	expect(t, c, 3, "ZADD", "z", "CH", 7, "a", 8, "b", 9, "c")
	expect(t, c, 0, "ZADD", "z", 7, "a") // same score: unchanged
	expect(t, c, 0, "ZADD", "z", "CH", 7, "a")
	// INCR
	expect(t, c, "10", "ZADD", "i", "INCR", 10, "m")
	expect(t, c, "15", "ZADD", "i", "INCR", 5, "m")
	expect(t, c, Nil, "ZADD", "i", "INCR", "NX", 5, "m")
	expect(t, c, Nil, "ZADD", "i", "INCR", "XX", 5, "other")
	expect(t, c, Nil, "ZADD", "i", "INCR", "GT", -5, "m")
	expect(t, c, "20", "ZADD", "i", "INCR", "GT", 5, "m")
	expect(t, c, Err("ERR INCR option supports a single increment-element pair"), "ZADD", "i", "INCR", 1, "a", 2, "b")
	// option conflicts
	expect(t, c, Err("ERR XX and NX options at the same time are not compatible"), "ZADD", "z", "NX", "XX", 1, "a")
	expect(t, c, Err("ERR GT, LT, and/or NX options at the same time are not compatible"), "ZADD", "z", "GT", "LT", 1, "a")
	expect(t, c, Err("ERR GT, LT, and/or NX options at the same time are not compatible"), "ZADD", "z", "NX", "GT", 1, "a")
	// XX on a missing key does not create it
	expect(t, c, 0, "ZADD", "nokey", "XX", 1, "a")
	expect(t, c, 0, "EXISTS", "nokey")
	// NaN from inf + -inf
	c.Do("ZADD", "n", "inf", "a")
	expect(t, c, Err("ERR resulting score is not a number (NaN)"), "ZINCRBY", "n", "-inf", "a")
}

func TestZRemZIncrBy(t *testing.T) {
	_, c := newSrv(t)
	zfill(c)
	expect(t, c, 2, "ZREM", "z", "one", "zz", "two")
	expect(t, c, 1, "ZCARD", "z")
	expect(t, c, 1, "ZREM", "z", "three")
	expect(t, c, 0, "EXISTS", "z")
	expect(t, c, 0, "ZREM", "nokey", "a")
	expect(t, c, "2", "ZINCRBY", "z", 2, "m")
	expect(t, c, "-1", "ZINCRBY", "z", -3, "m")
	expect(t, c, Err("ERR value is not a valid float"), "ZINCRBY", "z", "x", "m")
	expect(t, c, arr("-1", nil), "ZMSCORE", "z", "m", "nope")
}

func TestZRankZCountZMScore(t *testing.T) {
	_, c := newSrv(t)
	zfill(c)
	expect(t, c, 0, "ZRANK", "z", "one")
	expect(t, c, 2, "ZRANK", "z", "three")
	expect(t, c, Nil, "ZRANK", "z", "none")
	expect(t, c, 2, "ZREVRANK", "z", "one")
	expect(t, c, 0, "ZREVRANK", "z", "three")
	expect(t, c, Nil, "ZREVRANK", "nokey", "a")
	expect(t, c, arr(1, "2"), "ZRANK", "z", "two", "WITHSCORE")
	expect(t, c, arr(1, "2"), "ZREVRANK", "z", "two", "WITHSCORE")
	expect(t, c, Nil, "ZRANK", "z", "none", "WITHSCORE")
	expect(t, c, Err("ERR syntax error"), "ZRANK", "z", "one", "BOGUS")
	expect(t, c, 3, "ZCOUNT", "z", "-inf", "+inf")
	expect(t, c, 2, "ZCOUNT", "z", 1, 2)
	expect(t, c, 1, "ZCOUNT", "z", "(1", 2)
	expect(t, c, 0, "ZCOUNT", "z", "(1", "(2")
	expect(t, c, 0, "ZCOUNT", "z", 3, 1)
	expect(t, c, 0, "ZCOUNT", "nokey", 0, 10)
	expect(t, c, Err("ERR min or max is not a float"), "ZCOUNT", "z", "a", 2)
	expect(t, c, arr("1", nil, "3"), "ZMSCORE", "z", "one", "none", "three")
	expect(t, c, arr(nil, nil), "ZMSCORE", "nokey", "a", "b")
}

func TestZRangeVariants(t *testing.T) {
	_, c := newSrv(t)
	c.Do("ZADD", "z", 1, "a", 2, "b", 3, "c", 4, "d", 5, "e")
	expect(t, c, arr("a", "b", "c", "d", "e"), "ZRANGE", "z", 0, -1)
	expect(t, c, arr("b", "c"), "ZRANGE", "z", 1, 2)
	expect(t, c, arr("d", "e"), "ZRANGE", "z", -2, -1)
	expect(t, c, arr("a", "b", "c", "d", "e"), "ZRANGE", "z", -100, 100)
	expect(t, c, arr(), "ZRANGE", "z", 3, 1)
	expect(t, c, arr(), "ZRANGE", "z", 10, 20)
	expect(t, c, arr(), "ZRANGE", "nokey", 0, -1)
	expect(t, c, arr("e", "d"), "ZRANGE", "z", 0, 1, "REV")
	expect(t, c, arr("e", "5", "d", "4"), "ZREVRANGE", "z", 0, 1, "WITHSCORES")
	expect(t, c, arr("e", "d", "c", "b", "a"), "ZREVRANGE", "z", 0, -1)
	expect(t, c, arr("c", "b"), "ZREVRANGE", "z", 2, 3)
	expect(t, c, Err("ERR value is not an integer or out of range"), "ZRANGE", "z", "a", 1)
	// BYSCORE
	expect(t, c, arr("b", "c", "d"), "ZRANGE", "z", 2, 4, "BYSCORE")
	expect(t, c, arr("c", "d"), "ZRANGE", "z", "(2", 4, "BYSCORE")
	expect(t, c, arr("c"), "ZRANGE", "z", "(2", "(4", "BYSCORE")
	expect(t, c, arr("a", "b"), "ZRANGE", "z", "-inf", 2, "BYSCORE")
	expect(t, c, arr("d", "e"), "ZRANGE", "z", 4, "+inf", "BYSCORE")
	expect(t, c, arr("d", "e"), "ZRANGE", "z", 4, "inf", "BYSCORE")
	expect(t, c, arr("d", "c", "b"), "ZRANGE", "z", 4, 2, "BYSCORE", "REV")
	expect(t, c, arr("b", "2", "c", "3"), "ZRANGE", "z", 2, 3, "BYSCORE", "WITHSCORES")
	expect(t, c, arr("c", "d"), "ZRANGE", "z", "-inf", "+inf", "BYSCORE", "LIMIT", 2, 2)
	expect(t, c, arr("c", "b"), "ZRANGE", "z", "+inf", "-inf", "BYSCORE", "REV", "LIMIT", 2, 2)
	expect(t, c, arr("c", "d", "e"), "ZRANGE", "z", "-inf", "+inf", "BYSCORE", "LIMIT", 2, -1)
	expect(t, c, arr(), "ZRANGE", "z", "-inf", "+inf", "BYSCORE", "LIMIT", 10, 5)
	expect(t, c, arr(), "ZRANGE", "z", "-inf", "+inf", "BYSCORE", "LIMIT", -1, 5)
	expect(t, c, arr(), "ZRANGE", "z", 4, 2, "BYSCORE")
	expect(t, c, arr(), "ZRANGE", "z", "(3", "(3", "BYSCORE")
	expect(t, c, Err("ERR min or max is not a float"), "ZRANGE", "z", "x", 2, "BYSCORE")
	// legacy
	expect(t, c, arr("b", "c"), "ZRANGEBYSCORE", "z", 2, 3)
	expect(t, c, arr("b", "2"), "ZRANGEBYSCORE", "z", "(1", "(3", "WITHSCORES")
	expect(t, c, arr("c", "d"), "ZRANGEBYSCORE", "z", "-inf", "+inf", "LIMIT", 2, 2)
	expect(t, c, arr("d", "c", "b"), "ZREVRANGEBYSCORE", "z", 4, 2)
	expect(t, c, arr("e", "5"), "ZREVRANGEBYSCORE", "z", "+inf", "(4", "WITHSCORES")
	expect(t, c, arr("d", "c"), "ZREVRANGEBYSCORE", "z", "+inf", "-inf", "LIMIT", 1, 2)
	expect(t, c, Err("ERR syntax error"), "ZRANGEBYSCORE", "z", 1, 2, "BOGUS")
	// option errors
	expect(t, c, Err("ERR syntax error, LIMIT is only supported in combination with either BYSCORE or BYLEX"), "ZRANGE", "z", 0, -1, "LIMIT", 0, 1)
	expect(t, c, Err("ERR syntax error, WITHSCORES not supported in combination with BYLEX"), "ZRANGE", "z", "-", "+", "BYLEX", "WITHSCORES")
	expect(t, c, Err("ERR syntax error"), "ZRANGE", "z", 0, 1, "BYSCORE", "BYLEX")
}

func TestZRangeLex(t *testing.T) {
	_, c := newSrv(t)
	c.Do("ZADD", "z", 0, "a", 0, "b", 0, "c", 0, "d", 0, "e", 0, "f", 0, "g")
	expect(t, c, arr("a", "b", "c", "d", "e", "f", "g"), "ZRANGEBYLEX", "z", "-", "+")
	expect(t, c, arr("a", "b", "c"), "ZRANGEBYLEX", "z", "-", "[c")
	expect(t, c, arr("a", "b"), "ZRANGEBYLEX", "z", "-", "(c")
	expect(t, c, arr("b", "c", "d", "e"), "ZRANGEBYLEX", "z", "[aaa", "(f")
	expect(t, c, arr("c", "d"), "ZRANGEBYLEX", "z", "[b", "(e", "LIMIT", 1, 2)
	expect(t, c, arr("g", "f", "e"), "ZREVRANGEBYLEX", "z", "+", "(d")
	expect(t, c, arr("e", "d"), "ZRANGE", "z", "[e", "(c", "BYLEX", "REV")
	expect(t, c, arr("b", "c"), "ZRANGE", "z", "[b", "[c", "BYLEX")
	expect(t, c, arr(), "ZRANGEBYLEX", "z", "+", "-")
	expect(t, c, arr(), "ZRANGEBYLEX", "z", "(c", "(c")
	expect(t, c, arr(), "ZRANGEBYLEX", "nokey", "-", "+")
	expect(t, c, 7, "ZLEXCOUNT", "z", "-", "+")
	expect(t, c, 3, "ZLEXCOUNT", "z", "[b", "[d")
	expect(t, c, 1, "ZLEXCOUNT", "z", "(b", "(d")
	expect(t, c, 0, "ZLEXCOUNT", "z", "[x", "[z")
	expect(t, c, Err("ERR min or max not valid string range item"), "ZRANGEBYLEX", "z", "a", "[b")
	expect(t, c, Err("ERR min or max not valid string range item"), "ZLEXCOUNT", "z", "[a", "b")
	expect(t, c, Err("ERR syntax error"), "ZRANGEBYLEX", "z", "-", "+", "WITHSCORES")
}

func TestZPop(t *testing.T) {
	_, c := newSrv(t)
	zfill(c)
	expect(t, c, arr("one", "1"), "ZPOPMIN", "z")
	expect(t, c, arr("three", "3"), "ZPOPMAX", "z")
	expect(t, c, arr("two", "2"), "ZPOPMIN", "z", 5)
	expect(t, c, 0, "EXISTS", "z")
	expect(t, c, arr(), "ZPOPMIN", "z")
	expect(t, c, arr(), "ZPOPMAX", "nokey", 3)
	zfill(c)
	expect(t, c, arr("three", "3", "two", "2"), "ZPOPMAX", "z", 2)
	expect(t, c, arr(), "ZPOPMIN", "z", 0)
	expect(t, c, Err("ERR value is out of range, must be positive"), "ZPOPMIN", "z", -1)
	expect(t, c, Err("ERR syntax error"), "ZPOPMIN", "z", 1, 2)
}

func TestZRemRange(t *testing.T) {
	_, c := newSrv(t)
	c.Do("ZADD", "z", 1, "a", 2, "b", 3, "c", 4, "d", 5, "e")
	expect(t, c, 2, "ZREMRANGEBYSCORE", "z", "(1", 3)
	expect(t, c, arr("a", "d", "e"), "ZRANGE", "z", 0, -1)
	expect(t, c, 1, "ZREMRANGEBYRANK", "z", 0, 0)
	expect(t, c, 1, "ZREMRANGEBYRANK", "z", -1, -1)
	expect(t, c, arr("d"), "ZRANGE", "z", 0, -1)
	expect(t, c, 0, "ZREMRANGEBYRANK", "z", 5, 9)
	expect(t, c, 1, "ZREMRANGEBYSCORE", "z", "-inf", "+inf")
	expect(t, c, 0, "EXISTS", "z")
	c.Do("ZADD", "l", 0, "a", 0, "b", 0, "c", 0, "d")
	expect(t, c, 2, "ZREMRANGEBYLEX", "l", "[b", "(d")
	expect(t, c, arr("a", "d"), "ZRANGE", "l", 0, -1)
	expect(t, c, 0, "ZREMRANGEBYSCORE", "nokey", 0, 1)
	expect(t, c, Err("ERR min or max is not a float"), "ZREMRANGEBYSCORE", "l", "x", 1)
	expect(t, c, Err("ERR value is not an integer or out of range"), "ZREMRANGEBYRANK", "l", "x", 1)
}

func TestZUnionInterStore(t *testing.T) {
	_, c := newSrv(t)
	c.Do("ZADD", "z1", 1, "one", 2, "two")
	c.Do("ZADD", "z2", 1, "one", 2, "two", 3, "three")
	expect(t, c, 3, "ZUNIONSTORE", "out", 2, "z1", "z2")
	expect(t, c, arr("one", "2", "three", "3", "two", "4"), "ZRANGE", "out", 0, -1, "WITHSCORES")
	expect(t, c, 2, "ZINTERSTORE", "out", 2, "z1", "z2", "WEIGHTS", 2, 3)
	expect(t, c, arr("one", "5", "two", "10"), "ZRANGE", "out", 0, -1, "WITHSCORES")
	expect(t, c, 2, "ZINTERSTORE", "out", 2, "z1", "z2", "AGGREGATE", "MAX")
	expect(t, c, arr("one", "1", "two", "2"), "ZRANGE", "out", 0, -1, "WITHSCORES")
	c.Do("ZADD", "z3", 10, "one", 0.5, "two")
	expect(t, c, 2, "ZINTERSTORE", "out", 2, "z1", "z3", "AGGREGATE", "MIN")
	expect(t, c, arr("two", "0.5", "one", "1"), "ZRANGE", "out", 0, -1, "WITHSCORES")
	expect(t, c, 3, "ZUNIONSTORE", "out", 3, "z1", "z2", "z3", "WEIGHTS", 1, 0, 2, "AGGREGATE", "SUM")
	expect(t, c, arr("three", "0", "two", "3", "one", "21"), "ZRANGE", "out", 0, -1, "WITHSCORES")
	// plain sets count as score 1; missing keys are empty
	c.Do("SADD", "s", "one", "x")
	expect(t, c, 3, "ZUNIONSTORE", "out", 2, "z1", "s")
	expect(t, c, arr("x", "1", "one", "2", "two", "2"), "ZRANGE", "out", 0, -1, "WITHSCORES")
	expect(t, c, 1, "ZINTERSTORE", "out", 2, "z1", "s")
	expect(t, c, "2", "ZSCORE", "out", "one")
	expect(t, c, 0, "ZINTERSTORE", "out", 2, "z1", "nokey")
	expect(t, c, 0, "EXISTS", "out")
	expect(t, c, 2, "ZUNIONSTORE", "out", 2, "z1", "nokey")
	// dst may be one of the sources
	expect(t, c, 3, "ZUNIONSTORE", "z1", 2, "z1", "z2")
	expect(t, c, "2", "ZSCORE", "z1", "one")
	// inf handling
	c.Do("ZADD", "pi", "inf", "a")
	c.Do("ZADD", "ni", "-inf", "a")
	expect(t, c, 1, "ZUNIONSTORE", "out", 2, "pi", "ni")
	expect(t, c, "0", "ZSCORE", "out", "a") // inf + -inf = NaN -> 0
	// errors
	expect(t, c, Err("ERR at least 1 input key is needed for 'zunionstore' command"), "ZUNIONSTORE", "out", 0, "z1")
	expect(t, c, Err("ERR at least 1 input key is needed for 'zinterstore' command"), "ZINTERSTORE", "out", 0, "z1")
	expect(t, c, Err("ERR syntax error"), "ZUNIONSTORE", "out", 3, "z1", "z2")
	expect(t, c, Err("ERR syntax error"), "ZUNIONSTORE", "out", 1, "z1", "AGGREGATE", "AVG")
	expect(t, c, Err("ERR syntax error"), "ZUNIONSTORE", "out", 2, "z1", "z2", "WEIGHTS", 1)
	expect(t, c, Err("ERR weight value is not a float"), "ZUNIONSTORE", "out", 1, "z1", "WEIGHTS", "x")
	expect(t, c, Err("ERR value is not an integer or out of range"), "ZUNIONSTORE", "out", "x", "z1")
	c.Do("SET", "str", "v")
	expect(t, c, wrongType, "ZUNIONSTORE", "out", 2, "z1", "str")
}

func TestZSetWrongTypeAndMisc(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SET", "s", "v")
	c.Do("ZADD", "z", 1, "a")
	for _, cmd := range [][]any{{"ZADD", "s", 1, "a"}, {"ZRANGE", "s", 0, -1}, {"ZSCORE", "s", "a"}, {"ZCARD", "s"}, {"ZPOPMIN", "s"}, {"ZRANK", "s", "a"}, {"ZREM", "s", "a"}, {"ZCOUNT", "s", 0, 1}} {
		expect(t, c, wrongType, cmd...)
	}
	expect(t, c, wrongType, "GET", "z")
	expect(t, c, wrongType, "SADD", "z", "x")
	expect(t, c, Simple("zset"), "TYPE", "z")
	expect(t, c, "listpack", "OBJECT", "ENCODING", "z")
	for i := 0; i < 130; i++ {
		c.Send("ZADD", "big", i, i)
	}
	for i := 0; i < 130; i++ {
		c.Read()
	}
	expect(t, c, "skiplist", "OBJECT", "ENCODING", "big")
	expect(t, c, 1, "COPY", "big", "big2")
	expect(t, c, 130, "ZCARD", "big2")
	expect(t, c, OK, "RENAME", "big2", "big3")
	expect(t, c, "129", "ZSCORE", "big3", "129")
}

func TestZSetPersistence(t *testing.T) {
	dir := t.TempDir()
	s := startServer(t, dir)
	c := s.Client(t)
	c.Do("ZADD", "z", 1.5, "a", "-inf", "b", 3, "c", "inf", "d")
	expect(t, c, OK, "SAVE")
	s.Kill()
	c2 := startServer(t, dir).Client(t)
	expect(t, c2, arr("b", "-inf", "a", "1.5", "c", "3", "d", "inf"), "ZRANGE", "z", 0, -1, "WITHSCORES")
}

// Large sorted sets must stay O(log n) per operation, even with all-equal
// scores (long runs of ties) and ranges at both ends.
func TestZSetScalability(t *testing.T) {
	_, c := newSrv(t)
	const n = 100000
	st := time.Now()
	pipe := func(count int, f func(i int) []any) {
		for i := 0; i < count; i += 1000 {
			end := min(i+1000, count)
			for j := i; j < end; j++ {
				c.Send(f(j)...)
			}
			for j := i; j < end; j++ {
				c.Read()
			}
		}
	}
	pipe(n, func(i int) []any { return []any{"ZADD", "same", 0, i} }) // all ties: ordered by member
	pipe(n, func(i int) []any { return []any{"ZADD", "inc", i, i} })
	pipe(n, func(i int) []any { return []any{"ZADD", "rev", n - i, i} })
	pipe(n, func(i int) []any { return []any{"ZINCRBY", "inc", 1, i} }) // re-score every element
	pipe(n, func(i int) []any { return []any{"ZRANK", "inc", i} })
	pipe(n, func(i int) []any { return []any{"ZRANGEBYSCORE", "inc", i, i + 2, "LIMIT", 0, 3} })
	pipe(n, func(i int) []any { return []any{"ZCOUNT", "inc", i, i + 100} })
	pipe(n/2, func(i int) []any { return []any{"ZPOPMIN", "same"} })
	pipe(n/2, func(i int) []any { return []any{"ZREM", "rev", i} })
	d := time.Since(st)
	t.Logf("%d-element zset workload: %v", n, d)
	if d > 40*time.Second {
		t.Fatalf("too slow: %v", d)
	}
	expect(t, c, n/2, "ZCARD", "same")
	expect(t, c, n/2, "ZCARD", "rev")
	expect(t, c, "1", "ZSCORE", "inc", 0)
	expect(t, c, 50000, "ZRANK", "inc", 50000)
	// range with a huge offset must stay cheap relative to the set
	st = time.Now()
	c.Do("ZINTERSTORE", "i", 2, "inc", "same")
	c.Do("ZUNIONSTORE", "u", 2, "inc", "rev")
	t.Logf("store ops: %v", time.Since(st))
}
