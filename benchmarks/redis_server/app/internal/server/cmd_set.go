package server

import (
	"math"
	"math/rand"
	"sort"
	"strings"
)

func registerSets(s *Server) {
	s.register("sadd", -3, true, cmdSAdd)
	s.register("srem", -3, true, cmdSRem)
	s.register("smembers", 2, false, cmdSMembers)
	s.register("sismember", 3, false, cmdSIsMember)
	s.register("smismember", -3, false, cmdSMIsMember)
	s.register("scard", 2, false, cmdSCard)
	s.register("spop", -2, true, cmdSPop)
	s.register("srandmember", -2, false, cmdSRandMember)
	s.register("sinter", -2, false, func(c *Client, a [][]byte) { setOp(c, a, opInter, false) })
	s.register("sunion", -2, false, func(c *Client, a [][]byte) { setOp(c, a, opUnion, false) })
	s.register("sdiff", -2, false, func(c *Client, a [][]byte) { setOp(c, a, opDiff, false) })
	s.register("sinterstore", -3, true, func(c *Client, a [][]byte) { setOp(c, a, opInter, true) })
	s.register("sunionstore", -3, true, func(c *Client, a [][]byte) { setOp(c, a, opUnion, true) })
	s.register("sdiffstore", -3, true, func(c *Client, a [][]byte) { setOp(c, a, opDiff, true) })
	s.register("smove", 4, true, cmdSMove)
	s.register("sintercard", -3, false, cmdSInterCard)
}

func (c *Client) getSet(key string) (*entry, *Set, bool) {
	e := c.db.lookup(key)
	if e == nil {
		return nil, nil, true
	}
	s, ok := e.val.(*Set)
	if !ok {
		c.addErr(errWrongType)
		return nil, nil, false
	}
	return e, s, true
}

// replyMembers writes members; sets that would be intsets in Redis come out
// in ascending numeric order, like Redis' intset encoding.
func (c *Client) replyMembers(items []string, intsetOrder bool) {
	if intsetOrder {
		sorted := append([]string(nil), items...)
		sort.Slice(sorted, func(i, j int) bool {
			x, _ := parseInt64([]byte(sorted[i]))
			y, _ := parseInt64([]byte(sorted[j]))
			return x < y
		})
		items = sorted
	}
	c.addArrayLen(len(items))
	for _, m := range items {
		c.addBulkStr(m)
	}
}

func allInts(items []string) bool {
	for _, m := range items {
		if _, ok := parseInt64([]byte(m)); !ok {
			return false
		}
	}
	return true
}

func cmdSAdd(c *Client, a [][]byte) {
	key := string(a[1])
	_, s, ok := c.getSet(key)
	if !ok {
		return
	}
	if s == nil {
		s = newSet()
		c.db.add(key, s)
	}
	n := int64(0)
	for _, m := range a[2:] {
		if s.add(string(m), &c.srv.lim) {
			n++
		}
	}
	c.addInt(n)
}

func cmdSRem(c *Client, a [][]byte) {
	e, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	n := int64(0)
	if s != nil {
		for _, m := range a[2:] {
			if s.remove(string(m)) {
				n++
			}
		}
		if s.Len() == 0 {
			c.db.remove(e)
		}
	}
	c.addInt(n)
}

func cmdSMembers(c *Client, a [][]byte) {
	_, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	if s == nil {
		c.addEmptyArray()
		return
	}
	c.replyMembers(s.items, s.enc == setIntset)
}

func cmdSIsMember(c *Client, a [][]byte) {
	_, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	c.addBool(s != nil && s.has(string(a[2])))
}

func cmdSMIsMember(c *Client, a [][]byte) {
	_, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	c.addArrayLen(len(a) - 2)
	for _, m := range a[2:] {
		c.addBool(s != nil && s.has(string(m)))
	}
}

func cmdSCard(c *Client, a [][]byte) {
	_, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	if s == nil {
		c.addInt(0)
		return
	}
	c.addInt(int64(s.Len()))
}

func cmdSPop(c *Client, a [][]byte) {
	if len(a) > 3 {
		c.addErr(errSyntax)
		return
	}
	hasCount := len(a) == 3
	var count int64
	if hasCount {
		n, ok := parseInt64(a[2])
		if !ok || n < 0 {
			c.addErr("ERR value is out of range, must be positive")
			return
		}
		count = n
	}
	e, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	if s == nil {
		if hasCount {
			c.addEmptyArray()
		} else {
			c.addNil()
		}
		return
	}
	if !hasCount {
		m := s.items[rand.Intn(s.Len())]
		s.remove(m)
		c.addBulkStr(m)
	} else {
		k := int(min(count, int64(s.Len())))
		picked := make([]string, 0, k)
		for _, i := range randomIndexes(s.Len(), k, false) {
			picked = append(picked, s.items[i])
		}
		for _, m := range picked {
			s.remove(m)
		}
		c.addArrayLen(len(picked))
		for _, m := range picked {
			c.addBulkStr(m)
		}
	}
	if s.Len() == 0 {
		c.db.remove(e)
	}
}

func cmdSRandMember(c *Client, a [][]byte) {
	if len(a) > 3 {
		c.addErr(errSyntax)
		return
	}
	hasCount := len(a) == 3
	var count int64
	if hasCount {
		n, ok := parseInt64(a[2])
		if !ok {
			c.addErr(errNotInt)
			return
		}
		count = n
	}
	_, s, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	if !hasCount {
		if s == nil {
			c.addNil()
		} else {
			c.addBulkStr(s.items[rand.Intn(s.Len())])
		}
		return
	}
	if s == nil || count == 0 {
		c.addEmptyArray()
		return
	}
	repeat := count < 0
	k := count
	if repeat {
		if count == math.MinInt64 || -count > 1<<31 {
			c.addErr("ERR value is out of range")
			return
		}
		k = -count
	} else if k > int64(s.Len()) {
		k = int64(s.Len())
	}
	idx := randomIndexes(s.Len(), int(k), repeat)
	c.addArrayLen(len(idx))
	for _, i := range idx {
		c.addBulkStr(s.items[i])
	}
}

const (
	opInter = iota
	opUnion
	opDiff
)

// loadSets fetches all keys as sets (missing -> nil). ok=false: WRONGTYPE sent.
func (c *Client) loadSets(keys [][]byte) ([]*Set, bool) {
	sets := make([]*Set, len(keys))
	for i, k := range keys {
		_, s, ok := c.getSet(string(k))
		if !ok {
			return nil, false
		}
		sets[i] = s
	}
	return sets, true
}

func compute(op int, sets []*Set) []string {
	var out []string
	switch op {
	case opInter:
		smallest := 0
		for i, s := range sets {
			if s == nil {
				return nil
			}
			if s.Len() < sets[smallest].Len() {
				smallest = i
			}
		}
	next:
		for _, m := range sets[smallest].items {
			for i, s := range sets {
				if i != smallest && !s.has(m) {
					continue next
				}
			}
			out = append(out, m)
		}
	case opUnion:
		seen := map[string]struct{}{}
		for _, s := range sets {
			if s == nil {
				continue
			}
			for _, m := range s.items {
				if _, dup := seen[m]; !dup {
					seen[m] = struct{}{}
					out = append(out, m)
				}
			}
		}
	case opDiff:
		if sets[0] == nil {
			return nil
		}
	nextd:
		for _, m := range sets[0].items {
			for _, s := range sets[1:] {
				if s != nil && s.has(m) {
					continue nextd
				}
			}
			out = append(out, m)
		}
	}
	return out
}

func setOp(c *Client, a [][]byte, op int, store bool) {
	keys := a[1:]
	if store {
		keys = a[2:]
	}
	sets, ok := c.loadSets(keys)
	if !ok {
		return
	}
	res := compute(op, sets)
	if !store {
		c.replyMembers(res, allInts(res) && len(res) <= c.srv.lim.setIntset)
		return
	}
	dst := string(a[1])
	c.db.del(dst)
	if len(res) > 0 {
		ns := newSet()
		for _, m := range res {
			ns.add(m, &c.srv.lim)
		}
		c.db.add(dst, ns)
	}
	c.addInt(int64(len(res)))
}

func cmdSMove(c *Client, a [][]byte) {
	se, src, ok := c.getSet(string(a[1]))
	if !ok {
		return
	}
	_, dst, ok := c.getSet(string(a[2]))
	if !ok {
		return
	}
	m := string(a[3])
	if src == nil || !src.has(m) {
		c.addInt(0)
		return
	}
	if string(a[1]) == string(a[2]) {
		c.addInt(1)
		return
	}
	src.remove(m)
	if src.Len() == 0 {
		c.db.remove(se)
	}
	if dst == nil {
		dst = newSet()
		c.db.add(string(a[2]), dst)
	}
	dst.add(m, &c.srv.lim)
	c.addInt(1)
}

func cmdSInterCard(c *Client, a [][]byte) {
	n, ok := parseInt64(a[1])
	if !ok || n <= 0 {
		c.addErr("ERR numkeys should be greater than 0")
		return
	}
	if n > int64(len(a)-2) {
		c.addErr("ERR Number of keys can't be greater than number of args")
		return
	}
	keys := a[2 : 2+n]
	limit := int64(0)
	for i := 2 + int(n); i < len(a); i++ {
		if strings.ToUpper(string(a[i])) != "LIMIT" || i+1 >= len(a) {
			c.addErr(errSyntax)
			return
		}
		l, ok := parseInt64(a[i+1])
		if !ok {
			c.addErr(errNotInt)
			return
		}
		if l < 0 {
			c.addErr("ERR LIMIT can't be negative")
			return
		}
		limit = l
		i++
	}
	sets, ok := c.loadSets(keys)
	if !ok {
		return
	}
	res := int64(len(compute(opInter, sets)))
	if limit > 0 && res > limit {
		res = limit
	}
	c.addInt(res)
}
