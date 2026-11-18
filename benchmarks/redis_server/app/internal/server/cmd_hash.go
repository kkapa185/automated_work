package server

import (
	"fmt"
	"math"
	"math/rand"
	"strings"
)

func registerHashes(s *Server) {
	s.register("hset", -4, true, func(c *Client, a [][]byte) { cmdHSet(c, a, false) })
	s.register("hmset", -4, true, func(c *Client, a [][]byte) { cmdHSet(c, a, true) })
	s.register("hget", 3, false, cmdHGet)
	s.register("hmget", -3, false, cmdHMGet)
	s.register("hgetall", 2, false, func(c *Client, a [][]byte) { hashDump(c, a, true, true) })
	s.register("hkeys", 2, false, func(c *Client, a [][]byte) { hashDump(c, a, true, false) })
	s.register("hvals", 2, false, func(c *Client, a [][]byte) { hashDump(c, a, false, true) })
	s.register("hdel", -3, true, cmdHDel)
	s.register("hexists", 3, false, cmdHExists)
	s.register("hlen", 2, false, cmdHLen)
	s.register("hincrby", 4, true, cmdHIncrBy)
	s.register("hincrbyfloat", 4, true, cmdHIncrByFloat)
	s.register("hsetnx", 4, true, cmdHSetNX)
	s.register("hstrlen", 3, false, cmdHStrlen)
	s.register("hrandfield", -2, false, cmdHRandField)
}

func (c *Client) getHash(key string) (*entry, *Hash, bool) {
	e := c.db.lookup(key)
	if e == nil {
		return nil, nil, true
	}
	h, ok := e.val.(*Hash)
	if !ok {
		c.addErr(errWrongType)
		return nil, nil, false
	}
	return e, h, true
}

// getOrCreateHash returns the hash at key, creating it when absent.
func (c *Client) getOrCreateHash(key string) (*Hash, bool) {
	_, h, ok := c.getHash(key)
	if !ok {
		return nil, false
	}
	if h == nil {
		h = newHash()
		c.db.add(key, h)
	}
	return h, true
}

func cmdHSet(c *Client, a [][]byte, legacy bool) {
	if len(a)%2 != 0 {
		c.addErr(fmt.Sprintf("ERR wrong number of arguments for '%s' command", strings.ToLower(string(a[0]))))
		return
	}
	h, ok := c.getOrCreateHash(string(a[1]))
	if !ok {
		return
	}
	added := int64(0)
	for i := 2; i < len(a); i += 2 {
		if h.set(string(a[i]), a[i+1], &c.srv.lim) {
			added++
		}
	}
	if legacy {
		c.addSimple("OK")
	} else {
		c.addInt(added)
	}
}

func cmdHGet(c *Client, a [][]byte) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if h != nil {
		if v, found := h.get(string(a[2])); found {
			c.addBulk(v)
			return
		}
	}
	c.addNil()
}

func cmdHMGet(c *Client, a [][]byte) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	c.addArrayLen(len(a) - 2)
	for _, f := range a[2:] {
		if h != nil {
			if v, found := h.get(string(f)); found {
				c.addBulk(v)
				continue
			}
		}
		c.addNil()
	}
}

func hashDump(c *Client, a [][]byte, keys, vals bool) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if h == nil {
		c.addEmptyArray()
		return
	}
	n := h.Len()
	if keys && vals {
		n *= 2
	}
	c.addArrayLen(n)
	h.each(func(f string, v []byte) {
		if keys {
			c.addBulkStr(f)
		}
		if vals {
			c.addBulk(v)
		}
	})
}

func cmdHDel(c *Client, a [][]byte) {
	e, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	n := int64(0)
	if h != nil {
		for _, f := range a[2:] {
			if h.del(string(f)) {
				n++
			}
		}
		if h.Len() == 0 {
			c.db.remove(e)
		}
	}
	c.addInt(n)
}

func cmdHExists(c *Client, a [][]byte) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if h != nil {
		if _, found := h.get(string(a[2])); found {
			c.addInt(1)
			return
		}
	}
	c.addInt(0)
}

func cmdHLen(c *Client, a [][]byte) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if h == nil {
		c.addInt(0)
		return
	}
	c.addInt(int64(h.Len()))
}

func cmdHIncrBy(c *Client, a [][]byte) {
	d, ok := parseInt64(a[3])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	var cur int64
	if h != nil {
		if v, found := h.get(string(a[2])); found {
			if cur, ok = parseInt64(v); !ok {
				c.addErr("ERR hash value is not an integer")
				return
			}
		}
	}
	if (d > 0 && cur > math.MaxInt64-d) || (d < 0 && cur < math.MinInt64-d) {
		c.addErr("ERR increment or decrement would overflow")
		return
	}
	cur += d
	if h == nil {
		h, _ = c.getOrCreateHash(string(a[1]))
	}
	h.set(string(a[2]), []byte(fmt.Sprint(cur)), &c.srv.lim)
	c.addInt(cur)
}

func cmdHIncrByFloat(c *Client, a [][]byte) {
	inc, ok := parseLongDouble(a[3])
	if !ok {
		c.addErr(errNotFloat)
		return
	}
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	cur, _ := parseLongDouble([]byte("0"))
	if h != nil {
		if v, found := h.get(string(a[2])); found {
			if cur, ok = parseLongDouble(v); !ok {
				c.addErr("ERR hash value is not a float")
				return
			}
		}
	}
	sum, ok := addLongDouble(cur, inc)
	if !ok {
		c.addErr("ERR increment would produce NaN or Infinity")
		return
	}
	s := []byte(formatLongDouble(sum))
	if h == nil {
		h, _ = c.getOrCreateHash(string(a[1]))
	}
	h.set(string(a[2]), s, &c.srv.lim)
	c.addBulk(s)
}

func cmdHSetNX(c *Client, a [][]byte) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if h != nil {
		if _, found := h.get(string(a[2])); found {
			c.addInt(0)
			return
		}
	}
	if h == nil {
		h, _ = c.getOrCreateHash(string(a[1]))
	}
	h.set(string(a[2]), a[3], &c.srv.lim)
	c.addInt(1)
}

func cmdHStrlen(c *Client, a [][]byte) {
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if h != nil {
		if v, found := h.get(string(a[2])); found {
			c.addInt(int64(len(v)))
			return
		}
	}
	c.addInt(0)
}

// randomIndexes picks k indexes in [0,n): distinct when !repeat.
func randomIndexes(n, k int, repeat bool) []int {
	out := make([]int, 0, k)
	if repeat {
		for i := 0; i < k; i++ {
			out = append(out, rand.Intn(n))
		}
		return out
	}
	if k >= n {
		for i := 0; i < n; i++ {
			out = append(out, i)
		}
		rand.Shuffle(n, func(i, j int) { out[i], out[j] = out[j], out[i] })
		return out
	}
	if k*3 > n {
		p := rand.Perm(n)
		return p[:k]
	}
	seen := make(map[int]struct{}, k)
	for len(out) < k {
		i := rand.Intn(n)
		if _, dup := seen[i]; !dup {
			seen[i] = struct{}{}
			out = append(out, i)
		}
	}
	return out
}

func cmdHRandField(c *Client, a [][]byte) {
	if len(a) > 4 {
		c.addErr(errSyntax)
		return
	}
	withValues := false
	hasCount := len(a) >= 3
	var count int64
	if hasCount {
		n, ok := parseInt64(a[2])
		if !ok {
			c.addErr(errNotInt)
			return
		}
		count = n
		if len(a) == 4 {
			if strings.ToUpper(string(a[3])) != "WITHVALUES" {
				c.addErr(errSyntax)
				return
			}
			withValues = true
			if count < -math.MaxInt64/2 || count > math.MaxInt64/2 {
				c.addErr("ERR value is out of range")
				return
			}
		}
	}
	_, h, ok := c.getHash(string(a[1]))
	if !ok {
		return
	}
	if !hasCount {
		if h == nil {
			c.addNil()
			return
		}
		for { // tombstones are at most ~half of the slots, so this is O(1) expected
			if it := h.items[rand.Intn(len(h.items))]; it.live {
				c.addBulkStr(it.f)
				return
			}
		}
	}
	if h == nil || count == 0 {
		c.addEmptyArray()
		return
	}
	items := h.fields()
	repeat := count < 0
	k := count
	if repeat {
		k = -count
	}
	if !repeat && k > int64(len(items)) {
		k = int64(len(items))
	}
	if k > 1<<31 {
		c.addErr("ERR value is out of range")
		return
	}
	idx := randomIndexes(len(items), int(k), repeat)
	if withValues {
		c.addArrayLen(len(idx) * 2)
	} else {
		c.addArrayLen(len(idx))
	}
	for _, i := range idx {
		c.addBulkStr(items[i].f)
		if withValues {
			c.addBulk(items[i].v)
		}
	}
}
