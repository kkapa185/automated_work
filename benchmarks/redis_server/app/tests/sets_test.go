package tests

import (
	"sort"
	"testing"
)

func sortedStrs(t testing.TB, v any) []string {
	s := strs(t, v)
	sort.Strings(s)
	return s
}

func sameSet(t testing.TB, got any, want ...string) {
	t.Helper()
	g := sortedStrs(t, got)
	sort.Strings(want)
	if len(g) != len(want) {
		t.Fatalf("got %v want %v", g, want)
	}
	for i := range g {
		if g[i] != want[i] {
			t.Fatalf("got %v want %v", g, want)
		}
	}
}

func TestSetBasics(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, 3, "SADD", "s", "a", "b", "c")
	expect(t, c, 1, "SADD", "s", "a", "d")
	expect(t, c, 4, "SCARD", "s")
	expect(t, c, 0, "SCARD", "nokey")
	expect(t, c, 1, "SISMEMBER", "s", "a")
	expect(t, c, 0, "SISMEMBER", "s", "zz")
	expect(t, c, 0, "SISMEMBER", "nokey", "a")
	expect(t, c, arr(1, 0, 1), "SMISMEMBER", "s", "a", "zz", "d")
	expect(t, c, arr(0, 0), "SMISMEMBER", "nokey", "a", "b")
	sameSet(t, c.Do("SMEMBERS", "s"), "a", "b", "c", "d")
	expect(t, c, arr(), "SMEMBERS", "nokey")
	expect(t, c, 2, "SREM", "s", "a", "zz", "b")
	expect(t, c, 2, "SCARD", "s")
	expect(t, c, 2, "SREM", "s", "c", "d")
	expect(t, c, 0, "EXISTS", "s")
	expect(t, c, 0, "SREM", "nokey", "a")
	expect(t, c, Err("ERR wrong number of arguments for 'sadd' command"), "SADD", "s")
}

func TestIntsetOrder(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SADD", "s", 30, 5, 100, -2)
	expect(t, c, arr("-2", "5", "30", "100"), "SMEMBERS", "s")
}

func TestSPopSRandMember(t *testing.T) {
	_, c := newSrv(t)
	expect(t, c, Nil, "SPOP", "nokey")
	expect(t, c, arr(), "SPOP", "nokey", 3)
	expect(t, c, Nil, "SRANDMEMBER", "nokey")
	expect(t, c, arr(), "SRANDMEMBER", "nokey", 3)
	c.Do("SADD", "s", "a", "b", "c", "d", "e")
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		seen[c.Do("SRANDMEMBER", "s").(string)] = true
	}
	if len(seen) != 5 {
		t.Fatalf("SRANDMEMBER not random: %v", seen)
	}
	expect(t, c, 5, "SCARD", "s")
	got := strs(t, c.Do("SRANDMEMBER", "s", 3))
	if len(got) != 3 || got[0] == got[1] || got[1] == got[2] || got[0] == got[2] {
		t.Fatalf("distinct: %v", got)
	}
	if len(strs(t, c.Do("SRANDMEMBER", "s", 10))) != 5 {
		t.Fatal("count > size returns whole set")
	}
	if len(strs(t, c.Do("SRANDMEMBER", "s", -12))) != 12 {
		t.Fatal("negative count repeats")
	}
	expect(t, c, arr(), "SRANDMEMBER", "s", 0)
	m := c.Do("SPOP", "s").(string)
	expect(t, c, 4, "SCARD", "s")
	expect(t, c, 0, "SISMEMBER", "s", m)
	pp := strs(t, c.Do("SPOP", "s", 2))
	if len(pp) != 2 || pp[0] == pp[1] {
		t.Fatal(pp)
	}
	expect(t, c, 2, "SCARD", "s")
	if len(strs(t, c.Do("SPOP", "s", 100))) != 2 {
		t.Fatal("pop more than size")
	}
	expect(t, c, 0, "EXISTS", "s")
	expect(t, c, Err("ERR value is out of range, must be positive"), "SPOP", "s", -1)
	expect(t, c, Err("ERR value is not an integer or out of range"), "SRANDMEMBER", "s", "x")
}

func TestSetAlgebra(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SADD", "a", 1, 2, 3, 4)
	c.Do("SADD", "b", 3, 4, 5)
	c.Do("SADD", "c", 4, 6)
	expect(t, c, arr("4"), "SINTER", "a", "b", "c")
	expect(t, c, arr("3", "4"), "SINTER", "a", "b")
	expect(t, c, arr("1", "2", "3", "4", "5", "6"), "SUNION", "a", "b", "c")
	expect(t, c, arr("1", "2"), "SDIFF", "a", "b")
	expect(t, c, arr("1", "2"), "SDIFF", "a", "b", "c")
	expect(t, c, arr("1", "2", "3", "4"), "SDIFF", "a", "nokey")
	expect(t, c, arr(), "SDIFF", "nokey", "a")
	expect(t, c, arr(), "SINTER", "a", "nokey")
	expect(t, c, arr("1", "2", "3", "4"), "SUNION", "a", "nokey")
	expect(t, c, arr("1", "2", "3", "4"), "SINTER", "a")
	expect(t, c, 2, "SINTERSTORE", "d", "a", "b")
	expect(t, c, arr("3", "4"), "SMEMBERS", "d")
	expect(t, c, 6, "SUNIONSTORE", "d", "a", "b", "c") // overwrites dest
	expect(t, c, 2, "SDIFFSTORE", "d", "a", "b")
	expect(t, c, arr("1", "2"), "SMEMBERS", "d")
	expect(t, c, 0, "SINTERSTORE", "d", "a", "nokey") // empty result deletes dest
	expect(t, c, 0, "EXISTS", "d")
	c.Do("SET", "str", "x")
	expect(t, c, 4, "SUNIONSTORE", "str", "a") // dest of any type is replaced
	expect(t, c, Simple("set"), "TYPE", "str")
}

func TestSetAlgebraWrongType(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SADD", "a", 1)
	c.Do("RPUSH", "lst", 1)
	expect(t, c, wrongType, "SINTER", "a", "lst")
	expect(t, c, wrongType, "SUNION", "lst", "a")
	expect(t, c, wrongType, "SDIFF", "a", "lst")
	expect(t, c, wrongType, "SINTERSTORE", "d", "a", "lst")
	expect(t, c, wrongType, "SINTERCARD", 2, "a", "lst")
	expect(t, c, 0, "EXISTS", "d")
}

func TestSMove(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SADD", "src", "a", "b")
	expect(t, c, 1, "SMOVE", "src", "dst", "a")
	expect(t, c, arr("b"), "SMEMBERS", "src")
	expect(t, c, arr("a"), "SMEMBERS", "dst")
	expect(t, c, 0, "SMOVE", "src", "dst", "zz")
	expect(t, c, 0, "SMOVE", "nokey", "dst", "a")
	expect(t, c, 1, "SMOVE", "src", "dst", "b")
	expect(t, c, 0, "EXISTS", "src")
	expect(t, c, 1, "SMOVE", "dst", "dst", "a") // same key: 1 if member exists
	c.Do("SET", "str", "x")
	expect(t, c, wrongType, "SMOVE", "dst", "str", "a")
	expect(t, c, 1, "SISMEMBER", "dst", "a")
}

func TestSInterCard(t *testing.T) {
	_, c := newSrv(t)
	c.Do("SADD", "a", 1, 2, 3, 4)
	c.Do("SADD", "b", 3, 4, 5)
	expect(t, c, 2, "SINTERCARD", 2, "a", "b")
	expect(t, c, 1, "SINTERCARD", 2, "a", "b", "LIMIT", 1)
	expect(t, c, 2, "SINTERCARD", 2, "a", "b", "LIMIT", 0)
	expect(t, c, 2, "SINTERCARD", 2, "a", "b", "LIMIT", 10)
	expect(t, c, 0, "SINTERCARD", 2, "a", "nokey")
	expect(t, c, 4, "SINTERCARD", 1, "a")
	expect(t, c, Err("ERR numkeys should be greater than 0"), "SINTERCARD", 0, "a")
	expect(t, c, Err("ERR numkeys should be greater than 0"), "SINTERCARD", "x", "a")
	expect(t, c, Err("ERR Number of keys can't be greater than number of args"), "SINTERCARD", 3, "a", "b")
	expect(t, c, Err("ERR LIMIT can't be negative"), "SINTERCARD", 1, "a", "LIMIT", -1)
	expect(t, c, Err("ERR syntax error"), "SINTERCARD", 1, "a", "BOGUS", 1)
}
