package server

import (
	"fmt"
	"math"
	"strings"
)

func registerZSets(s *Server) {
	s.register("zadd", -4, true, cmdZAdd)
	s.register("zrem", -3, true, cmdZRem)
	s.register("zscore", 3, false, cmdZScore)
	s.register("zmscore", -3, false, cmdZMScore)
	s.register("zincrby", 4, true, cmdZIncrBy)
	s.register("zcard", 2, false, cmdZCard)
	s.register("zcount", 4, false, cmdZCount)
	s.register("zlexcount", 4, false, cmdZLexCount)
	s.register("zrank", -3, false, func(c *Client, a [][]byte) { cmdZRank(c, a, false) })
	s.register("zrevrank", -3, false, func(c *Client, a [][]byte) { cmdZRank(c, a, true) })
	s.register("zrange", -4, false, cmdZRange)
	s.register("zrevrange", -4, false, func(c *Client, a [][]byte) { legacyRange(c, a, modeRank, true) })
	s.register("zrangebyscore", -4, false, func(c *Client, a [][]byte) { legacyRange(c, a, modeScore, false) })
	s.register("zrevrangebyscore", -4, false, func(c *Client, a [][]byte) { legacyRange(c, a, modeScore, true) })
	s.register("zrangebylex", -4, false, func(c *Client, a [][]byte) { legacyRange(c, a, modeLex, false) })
	s.register("zrevrangebylex", -4, false, func(c *Client, a [][]byte) { legacyRange(c, a, modeLex, true) })
	s.register("zpopmin", -2, true, func(c *Client, a [][]byte) { cmdZPop(c, a, false) })
	s.register("zpopmax", -2, true, func(c *Client, a [][]byte) { cmdZPop(c, a, true) })
	s.register("zremrangebyrank", 4, true, cmdZRemRangeByRank)
	s.register("zremrangebyscore", 4, true, cmdZRemRangeByScore)
	s.register("zremrangebylex", 4, true, cmdZRemRangeByLex)
	s.register("zunionstore", -4, true, func(c *Client, a [][]byte) { zsetStore(c, a, true) })
	s.register("zinterstore", -4, true, func(c *Client, a [][]byte) { zsetStore(c, a, false) })
}

const errNaN = "ERR resulting score is not a number (NaN)"

func (c *Client) getZSet(key string) (*entry, *ZSet, bool) {
	e := c.db.lookup(key)
	if e == nil {
		return nil, nil, true
	}
	z, ok := e.val.(*ZSet)
	if !ok {
		c.addErr(errWrongType)
		return nil, nil, false
	}
	return e, z, true
}

// ---------------- ZADD & friends ----------------

func cmdZAdd(c *Client, a [][]byte) {
	var nx, xx, gt, lt, ch, incr bool
	i := 2
loop:
	for ; i < len(a); i++ {
		switch strings.ToUpper(string(a[i])) {
		case "NX":
			nx = true
		case "XX":
			xx = true
		case "GT":
			gt = true
		case "LT":
			lt = true
		case "CH":
			ch = true
		case "INCR":
			incr = true
		default:
			break loop
		}
	}
	pairs := a[i:]
	if len(pairs) == 0 || len(pairs)%2 != 0 {
		c.addErr(errSyntax)
		return
	}
	if nx && xx {
		c.addErr("ERR XX and NX options at the same time are not compatible")
		return
	}
	if (gt && nx) || (lt && nx) || (gt && lt) {
		c.addErr("ERR GT, LT, and/or NX options at the same time are not compatible")
		return
	}
	if incr && len(pairs) > 2 {
		c.addErr("ERR INCR option supports a single increment-element pair")
		return
	}
	scores := make([]float64, len(pairs)/2)
	for j := range scores {
		f, ok := parseFloat(pairs[2*j])
		if !ok {
			c.addErr(errNotFloat)
			return
		}
		scores[j] = f
	}
	key := string(a[1])
	e, z, ok := c.getZSet(key)
	if !ok {
		return
	}
	created := false
	if z == nil {
		if xx { // nothing can be added
			if incr {
				c.addNil()
			} else {
				c.addInt(0)
			}
			return
		}
		z = newZSet()
		created = true
	}
	var added, updated int64
	var lastScore float64
	var incrApplied bool
	for j, sc := range scores {
		m := string(pairs[2*j+1])
		cur, exists := z.score(m)
		if !exists {
			if xx {
				continue
			}
			if incr && math.IsNaN(sc) {
				c.addErr(errNaN)
				return
			}
			z.put(m, sc, &c.srv.lim)
			if created && e == nil {
				e = c.db.add(key, z)
			}
			added++
			lastScore, incrApplied = sc, true
			continue
		}
		if nx {
			continue
		}
		ns := sc
		if incr {
			ns = cur + sc
			if math.IsNaN(ns) {
				c.addErr(errNaN)
				return
			}
		}
		if (gt && ns <= cur) || (lt && ns >= cur) {
			continue
		}
		lastScore, incrApplied = ns, true
		if ns != cur {
			z.put(m, ns, &c.srv.lim)
			updated++
		}
	}
	if incr {
		if incrApplied {
			c.addDouble(lastScore)
		} else {
			c.addNil()
		}
		return
	}
	if ch {
		c.addInt(added + updated)
	} else {
		c.addInt(added)
	}
}

func cmdZRem(c *Client, a [][]byte) {
	e, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	n := int64(0)
	if z != nil {
		for _, m := range a[2:] {
			if z.remove(string(m)) {
				n++
			}
		}
		if z.Len() == 0 {
			c.db.remove(e)
		}
	}
	c.addInt(n)
}

func cmdZScore(c *Client, a [][]byte) {
	_, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z != nil {
		if s, found := z.score(string(a[2])); found {
			c.addDouble(s)
			return
		}
	}
	c.addNil()
}

func cmdZMScore(c *Client, a [][]byte) {
	_, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	c.addArrayLen(len(a) - 2)
	for _, m := range a[2:] {
		if z != nil {
			if s, found := z.score(string(m)); found {
				c.addDouble(s)
				continue
			}
		}
		c.addNil()
	}
}

func cmdZIncrBy(c *Client, a [][]byte) {
	inc, ok := parseFloat(a[2])
	if !ok {
		c.addErr(errNotFloat)
		return
	}
	key := string(a[1])
	_, z, ok := c.getZSet(key)
	if !ok {
		return
	}
	m := string(a[3])
	var cur float64
	if z != nil {
		cur, _ = z.score(m)
	}
	ns := cur + inc
	if math.IsNaN(ns) {
		c.addErr(errNaN)
		return
	}
	if z == nil {
		z = newZSet()
		c.db.add(key, z)
	}
	z.put(m, ns, &c.srv.lim)
	c.addDouble(ns)
}

func cmdZCard(c *Client, a [][]byte) {
	_, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil {
		c.addInt(0)
		return
	}
	c.addInt(int64(z.Len()))
}

func cmdZRank(c *Client, a [][]byte, rev bool) {
	withScore := false
	if len(a) == 4 {
		if strings.ToUpper(string(a[3])) != "WITHSCORE" {
			c.addErr(errSyntax)
			return
		}
		withScore = true
	} else if len(a) > 4 {
		c.addErr(errSyntax)
		return
	}
	_, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	var sc float64
	var found bool
	if z != nil {
		sc, found = z.score(string(a[2]))
	}
	if !found {
		if withScore {
			c.addNilArray()
		} else {
			c.addNil()
		}
		return
	}
	r := z.sl.rank(sc, string(a[2])) - 1
	if rev {
		r = z.Len() - 1 - r
	}
	if withScore {
		c.addArrayLen(2)
		c.addInt(int64(r))
		c.addDouble(sc)
		return
	}
	c.addInt(int64(r))
}

// ---------------- range parsing ----------------

func parseScoreRange(minB, maxB []byte) (scoreRange, bool) {
	var r scoreRange
	bound := func(b []byte) (float64, bool, bool) {
		ex := false
		if len(b) > 0 && b[0] == '(' {
			ex = true
			b = b[1:]
		}
		f, ok := parseFloat(b)
		return f, ex, ok
	}
	var ok1, ok2 bool
	r.min, r.minEx, ok1 = bound(minB)
	r.max, r.maxEx, ok2 = bound(maxB)
	return r, ok1 && ok2
}

func parseLexRange(minB, maxB []byte) (lexRange, bool) {
	var r lexRange
	parse := func(b []byte, isMin bool) bool {
		if len(b) == 0 {
			return false
		}
		switch b[0] {
		case '-':
			if len(b) != 1 {
				return false
			}
			if isMin {
				r.minInf = true
			} else {
				r.never = true
			}
		case '+':
			if len(b) != 1 {
				return false
			}
			if isMin {
				r.never = true
			} else {
				r.maxInf = true
			}
		case '[', '(':
			ex := b[0] == '('
			if isMin {
				r.min, r.minEx = string(b[1:]), ex
			} else {
				r.max, r.maxEx = string(b[1:]), ex
			}
		default:
			return false
		}
		return true
	}
	ok := parse(minB, true) && parse(maxB, false)
	return r, ok
}

const (
	modeRank = iota
	modeScore
	modeLex
)

type rangeSpec struct {
	mode       int
	rev        bool
	withScores bool
	offset     int64
	count      int64 // <0: unlimited
}

func cmdZRange(c *Client, a [][]byte) {
	sp := rangeSpec{count: -1}
	byScore, byLex, hasLimit := false, false, false
	for i := 4; i < len(a); i++ {
		switch strings.ToUpper(string(a[i])) {
		case "BYSCORE":
			byScore = true
		case "BYLEX":
			byLex = true
		case "REV":
			sp.rev = true
		case "WITHSCORES":
			sp.withScores = true
		case "LIMIT":
			if i+2 >= len(a) {
				c.addErr(errSyntax)
				return
			}
			off, ok1 := parseInt64(a[i+1])
			cnt, ok2 := parseInt64(a[i+2])
			if !ok1 || !ok2 {
				c.addErr(errNotInt)
				return
			}
			sp.offset, sp.count, hasLimit = off, cnt, true
			i += 2
		default:
			c.addErr(errSyntax)
			return
		}
	}
	if byScore && byLex {
		c.addErr(errSyntax)
		return
	}
	switch {
	case byScore:
		sp.mode = modeScore
	case byLex:
		sp.mode = modeLex
	}
	if hasLimit && sp.mode == modeRank {
		c.addErr("ERR syntax error, LIMIT is only supported in combination with either BYSCORE or BYLEX")
		return
	}
	if sp.withScores && sp.mode == modeLex {
		c.addErr("ERR syntax error, WITHSCORES not supported in combination with BYLEX")
		return
	}
	zrange(c, string(a[1]), a[2], a[3], sp)
}

func legacyRange(c *Client, a [][]byte, mode int, rev bool) {
	sp := rangeSpec{mode: mode, rev: rev, count: -1}
	for i := 4; i < len(a); i++ {
		switch strings.ToUpper(string(a[i])) {
		case "WITHSCORES":
			if mode == modeLex {
				c.addErr(errSyntax)
				return
			}
			sp.withScores = true
		case "LIMIT":
			if mode == modeRank || i+2 >= len(a) {
				c.addErr(errSyntax)
				return
			}
			off, ok1 := parseInt64(a[i+1])
			cnt, ok2 := parseInt64(a[i+2])
			if !ok1 || !ok2 {
				c.addErr(errNotInt)
				return
			}
			sp.offset, sp.count = off, cnt
			i += 2
		default:
			c.addErr(errSyntax)
			return
		}
	}
	zrange(c, string(a[1]), a[2], a[3], sp)
}

func step(n *slNode, rev bool) *slNode {
	if rev {
		return n.back
	}
	return n.lvl[0].fwd
}

// zrange evaluates a range query. For reversed BYSCORE/BYLEX the first bound
// is the maximum, as in Redis.
func zrange(c *Client, key string, b1, b2 []byte, sp rangeSpec) {
	var sr scoreRange
	var lr lexRange
	var rs, re int64
	switch sp.mode {
	case modeRank:
		var ok1, ok2 bool
		rs, ok1 = parseInt64(b1)
		re, ok2 = parseInt64(b2)
		if !ok1 || !ok2 {
			c.addErr(errNotInt)
			return
		}
	case modeScore:
		lo, hi := b1, b2
		if sp.rev {
			lo, hi = b2, b1
		}
		var ok bool
		if sr, ok = parseScoreRange(lo, hi); !ok {
			c.addErr("ERR min or max is not a float")
			return
		}
	case modeLex:
		lo, hi := b1, b2
		if sp.rev {
			lo, hi = b2, b1
		}
		var ok bool
		if lr, ok = parseLexRange(lo, hi); !ok {
			c.addErr("ERR min or max not valid string range item")
			return
		}
	}
	_, z, ok := c.getZSet(key)
	if !ok {
		return
	}
	var out []*slNode
	if z != nil {
		out = collectRange(z, sp, rs, re, &sr, &lr)
	}
	if sp.withScores {
		c.addArrayLen(len(out) * 2)
	} else {
		c.addArrayLen(len(out))
	}
	for _, n := range out {
		c.addBulkStr(n.member)
		if sp.withScores {
			c.addDouble(n.score)
		}
	}
}

func collectRange(z *ZSet, sp rangeSpec, rs, re int64, sr *scoreRange, lr *lexRange) []*slNode {
	sl := z.sl
	var out []*slNode
	if sp.mode == modeRank {
		s, e, ok := clampRange(rs, re, sl.length)
		if !ok {
			return nil
		}
		var n *slNode
		if sp.rev {
			n = sl.byRank(sl.length - s)
		} else {
			n = sl.byRank(s + 1)
		}
		for i := s; i <= e && n != nil; i++ {
			out = append(out, n)
			n = step(n, sp.rev)
		}
		return out
	}
	if sp.offset < 0 {
		return nil
	}
	var n *slNode
	switch {
	case sp.mode == modeScore && !sp.rev:
		n = sl.firstInRange(sr)
	case sp.mode == modeScore:
		n = sl.lastInRange(sr)
	case !sp.rev:
		n = sl.firstInLex(lr)
	default:
		n = sl.lastInLex(lr)
	}
	for off := sp.offset; off > 0 && n != nil; off-- {
		n = step(n, sp.rev)
	}
	for n != nil && (sp.count < 0 || int64(len(out)) < sp.count) {
		var in bool
		switch {
		case sp.mode == modeScore && !sp.rev:
			in = sr.lteMax(n.score)
		case sp.mode == modeScore:
			in = sr.gteMin(n.score)
		case !sp.rev:
			in = lr.lteMax(n.member)
		default:
			in = lr.gteMin(n.member)
		}
		if !in {
			break
		}
		out = append(out, n)
		n = step(n, sp.rev)
	}
	return out
}

func cmdZCount(c *Client, a [][]byte) {
	r, ok := parseScoreRange(a[2], a[3])
	if !ok {
		c.addErr("ERR min or max is not a float")
		return
	}
	_, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil {
		c.addInt(0)
		return
	}
	first := z.sl.firstInRange(&r)
	if first == nil {
		c.addInt(0)
		return
	}
	last := z.sl.lastInRange(&r)
	c.addInt(int64(z.sl.rank(last.score, last.member) - z.sl.rank(first.score, first.member) + 1))
}

func cmdZLexCount(c *Client, a [][]byte) {
	r, ok := parseLexRange(a[2], a[3])
	if !ok {
		c.addErr("ERR min or max not valid string range item")
		return
	}
	_, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil {
		c.addInt(0)
		return
	}
	first := z.sl.firstInLex(&r)
	if first == nil {
		c.addInt(0)
		return
	}
	last := z.sl.lastInLex(&r)
	c.addInt(int64(z.sl.rank(last.score, last.member) - z.sl.rank(first.score, first.member) + 1))
}

func cmdZPop(c *Client, a [][]byte, max bool) {
	if len(a) > 3 {
		c.addErr(errSyntax)
		return
	}
	count := int64(1)
	if len(a) == 3 {
		n, ok := parseInt64(a[2])
		if !ok || n < 0 {
			c.addErr("ERR value is out of range, must be positive")
			return
		}
		count = n
	}
	e, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil || count == 0 {
		c.addEmptyArray()
		return
	}
	n := int(min(count, int64(z.Len())))
	c.addArrayLen(2 * n)
	for i := 0; i < n; i++ {
		node := z.sl.first()
		if max {
			node = z.sl.tail
		}
		c.addBulkStr(node.member)
		c.addDouble(node.score)
		z.remove(node.member)
	}
	if z.Len() == 0 {
		c.db.remove(e)
	}
}

// removeNodes deletes the given members and the key if it becomes empty.
func (c *Client) removeNodes(e *entry, z *ZSet, nodes []*slNode) {
	for _, n := range nodes {
		z.remove(n.member)
	}
	if z.Len() == 0 {
		c.db.remove(e)
	}
	c.addInt(int64(len(nodes)))
}

func cmdZRemRangeByRank(c *Client, a [][]byte) {
	rs, ok1 := parseInt64(a[2])
	re, ok2 := parseInt64(a[3])
	if !ok1 || !ok2 {
		c.addErr(errNotInt)
		return
	}
	e, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil {
		c.addInt(0)
		return
	}
	c.removeNodes(e, z, collectRange(z, rangeSpec{mode: modeRank}, rs, re, nil, nil))
}

func cmdZRemRangeByScore(c *Client, a [][]byte) {
	r, ok := parseScoreRange(a[2], a[3])
	if !ok {
		c.addErr("ERR min or max is not a float")
		return
	}
	e, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil {
		c.addInt(0)
		return
	}
	c.removeNodes(e, z, collectRange(z, rangeSpec{mode: modeScore, count: -1}, 0, 0, &r, nil))
}

func cmdZRemRangeByLex(c *Client, a [][]byte) {
	r, ok := parseLexRange(a[2], a[3])
	if !ok {
		c.addErr("ERR min or max not valid string range item")
		return
	}
	e, z, ok := c.getZSet(string(a[1]))
	if !ok {
		return
	}
	if z == nil {
		c.addInt(0)
		return
	}
	c.removeNodes(e, z, collectRange(z, rangeSpec{mode: modeLex, count: -1}, 0, 0, nil, &r))
}

// ---------------- ZUNIONSTORE / ZINTERSTORE ----------------

type zsource struct {
	z *ZSet
	s *Set
}

func (s zsource) size() int {
	switch {
	case s.z != nil:
		return s.z.Len()
	case s.s != nil:
		return s.s.Len()
	}
	return 0
}

func (s zsource) get(m string) (float64, bool) {
	switch {
	case s.z != nil:
		return s.z.score(m)
	case s.s != nil:
		return 1, s.s.has(m)
	}
	return 0, false
}

func (s zsource) each(fn func(m string, sc float64)) {
	switch {
	case s.z != nil:
		for n := s.z.sl.first(); n != nil; n = n.lvl[0].fwd {
			fn(n.member, n.score)
		}
	case s.s != nil:
		for _, m := range s.s.items {
			fn(m, 1)
		}
	}
}

func aggregate(agg string, old, v float64) float64 {
	switch agg {
	case "MIN":
		return math.Min(old, v)
	case "MAX":
		return math.Max(old, v)
	}
	r := old + v
	if math.IsNaN(r) {
		return 0
	}
	return r
}

func zsetStore(c *Client, a [][]byte, union bool) {
	name := strings.ToLower(string(a[0]))
	n, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	if n < 1 {
		c.addErr(fmt.Sprintf("ERR at least 1 input key is needed for '%s' command", name))
		return
	}
	if n > int64(len(a)-3) {
		c.addErr(errSyntax)
		return
	}
	keys := a[3 : 3+n]
	weights := make([]float64, n)
	for i := range weights {
		weights[i] = 1
	}
	agg := "SUM"
	for i := 3 + int(n); i < len(a); i++ {
		switch strings.ToUpper(string(a[i])) {
		case "WEIGHTS":
			if i+int(n) >= len(a) {
				c.addErr(errSyntax)
				return
			}
			for j := 0; j < int(n); j++ {
				w, ok := parseFloat(a[i+1+j])
				if !ok {
					c.addErr("ERR weight value is not a float")
					return
				}
				weights[j] = w
			}
			i += int(n)
		case "AGGREGATE":
			if i+1 >= len(a) {
				c.addErr(errSyntax)
				return
			}
			agg = strings.ToUpper(string(a[i+1]))
			if agg != "SUM" && agg != "MIN" && agg != "MAX" {
				c.addErr(errSyntax)
				return
			}
			i++
		default:
			c.addErr(errSyntax)
			return
		}
	}
	srcs := make([]zsource, n)
	for i, k := range keys {
		e := c.db.lookup(string(k))
		if e == nil {
			continue
		}
		switch v := e.val.(type) {
		case *ZSet:
			srcs[i].z = v
		case *Set:
			srcs[i].s = v
		default:
			c.addErr(errWrongType)
			return
		}
	}
	weighted := func(sc float64, i int) float64 {
		v := sc * weights[i]
		if math.IsNaN(v) {
			return 0
		}
		return v
	}
	res := map[string]float64{}
	if union {
		for i, s := range srcs {
			s.each(func(m string, sc float64) {
				v := weighted(sc, i)
				if old, exists := res[m]; exists {
					res[m] = aggregate(agg, old, v)
				} else {
					res[m] = v
				}
			})
		}
	} else {
		small, empty := 0, false
		for i, s := range srcs {
			if s.size() == 0 {
				empty = true
			}
			if s.size() < srcs[small].size() {
				small = i
			}
		}
		if !empty {
			srcs[small].each(func(m string, _ float64) {
				var acc float64
				for i, s := range srcs {
					sc, found := s.get(m)
					if !found {
						return
					}
					v := weighted(sc, i)
					if i == 0 {
						acc = v
					} else {
						acc = aggregate(agg, acc, v)
					}
				}
				res[m] = acc
			})
		}
	}
	dst := string(a[1])
	c.db.del(dst)
	if len(res) > 0 {
		z := newZSet()
		for m, sc := range res {
			z.put(m, sc, &c.srv.lim)
		}
		c.db.add(dst, z)
	}
	c.addInt(int64(len(res)))
}
