package server

import (
	"bytes"
	"fmt"
	"math"
	"strings"
)

func registerLists(s *Server) {
	s.register("lpush", -3, true, func(c *Client, a [][]byte) { cmdPush(c, a, true, false) })
	s.register("rpush", -3, true, func(c *Client, a [][]byte) { cmdPush(c, a, false, false) })
	s.register("lpushx", -3, true, func(c *Client, a [][]byte) { cmdPush(c, a, true, true) })
	s.register("rpushx", -3, true, func(c *Client, a [][]byte) { cmdPush(c, a, false, true) })
	s.register("lpop", -2, true, func(c *Client, a [][]byte) { cmdPop(c, a, true) })
	s.register("rpop", -2, true, func(c *Client, a [][]byte) { cmdPop(c, a, false) })
	s.register("llen", 2, false, cmdLLen)
	s.register("lrange", 4, false, cmdLRange)
	s.register("lindex", 3, false, cmdLIndex)
	s.register("lset", 4, true, cmdLSet)
	s.register("linsert", 5, true, cmdLInsert)
	s.register("lrem", 4, true, cmdLRem)
	s.register("ltrim", 4, true, cmdLTrim)
	s.register("lpos", -3, false, cmdLPos)
	s.register("rpoplpush", 3, true, cmdRPopLPush)
	s.register("lmove", 5, true, cmdLMove)
	s.register("blpop", -3, true, func(c *Client, a [][]byte) { cmdBPop(c, a, true) })
	s.register("brpop", -3, true, func(c *Client, a [][]byte) { cmdBPop(c, a, false) })
	s.register("blmove", 6, true, cmdBLMove)
	s.register("brpoplpush", 4, true, cmdBRPopLPush)
}

// getList fetches a list; ok=false means WRONGTYPE was already sent.
func (c *Client) getList(key string) (*entry, *List, bool) {
	e := c.db.lookup(key)
	if e == nil {
		return nil, nil, true
	}
	l, ok := e.val.(*List)
	if !ok {
		c.addErr(errWrongType)
		return nil, nil, false
	}
	return e, l, true
}

func cmdPush(c *Client, a [][]byte, left, onlyExisting bool) {
	key := string(a[1])
	_, l, ok := c.getList(key)
	if !ok {
		return
	}
	if l == nil {
		if onlyExisting {
			c.addInt(0)
			return
		}
		l = &List{}
		c.db.add(key, l)
	}
	for _, v := range a[2:] {
		pushSide(l, v, left)
	}
	c.db.signalKey(key)
	c.addInt(int64(l.Len()))
}

func cmdPop(c *Client, a [][]byte, left bool) {
	if len(a) > 3 {
		c.addErr(fmt.Sprintf("ERR wrong number of arguments for '%s' command", strings.ToLower(string(a[0]))))
		return
	}
	count := int64(-1)
	if len(a) == 3 {
		n, ok := parseInt64(a[2])
		if !ok || n < 0 {
			c.addErr("ERR value is out of range, must be positive")
			return
		}
		count = n
	}
	e, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		if count < 0 {
			c.addNil()
		} else {
			c.addNilArray()
		}
		return
	}
	if count < 0 {
		c.addBulk(popSide(l, left))
	} else {
		n := min(count, int64(l.Len()))
		c.addArrayLen(int(n))
		for i := int64(0); i < n; i++ {
			c.addBulk(popSide(l, left))
		}
	}
	if l.Len() == 0 {
		c.db.remove(e)
	}
}

func cmdLLen(c *Client, a [][]byte) {
	_, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addInt(0)
		return
	}
	c.addInt(int64(l.Len()))
}

// clampRange normalises Redis start/stop indexes; ok=false means empty.
func clampRange(start, end int64, n int) (int, int, bool) {
	ln := int64(n)
	if start < 0 {
		start += ln
		if start < 0 {
			start = 0
		}
	}
	if end < 0 {
		end += ln
	}
	if start > end || start >= ln {
		return 0, 0, false
	}
	if end >= ln {
		end = ln - 1
	}
	return int(start), int(end), true
}

func cmdLRange(c *Client, a [][]byte) {
	start, ok1 := parseInt64(a[2])
	end, ok2 := parseInt64(a[3])
	if !ok1 || !ok2 {
		c.addErr(errNotInt)
		return
	}
	_, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addEmptyArray()
		return
	}
	s, e, ok := clampRange(start, end, l.Len())
	if !ok {
		c.addEmptyArray()
		return
	}
	c.addBulkArray(l.items()[s : e+1])
}

func cmdLIndex(c *Client, a [][]byte) {
	idx, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	_, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addNil()
		return
	}
	n := int64(l.Len())
	if idx < 0 {
		idx += n
	}
	if idx < 0 || idx >= n {
		c.addNil()
		return
	}
	c.addBulk(l.items()[idx])
}

func cmdLSet(c *Client, a [][]byte) {
	idx, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	_, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addErr(errNoKey)
		return
	}
	n := int64(l.Len())
	if idx < 0 {
		idx += n
	}
	if idx < 0 || idx >= n {
		c.addErr("ERR index out of range")
		return
	}
	l.ver++
	l.items()[idx] = a[3]
	c.addSimple("OK")
}

func cmdLInsert(c *Client, a [][]byte) {
	var before bool
	switch strings.ToUpper(string(a[2])) {
	case "BEFORE":
		before = true
	case "AFTER":
	default:
		c.addErr(errSyntax)
		return
	}
	_, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addInt(0)
		return
	}
	items := l.items()
	pos := -1
	for i, it := range items {
		if bytes.Equal(it, a[3]) {
			pos = i
			break
		}
	}
	if pos < 0 {
		c.addInt(-1)
		return
	}
	if !before {
		pos++
	}
	out := make([][]byte, 0, len(items)+1)
	out = append(out, items[:pos]...)
	out = append(out, a[4])
	out = append(out, items[pos:]...)
	l.replace(out)
	c.addInt(int64(len(out)))
}

func cmdLRem(c *Client, a [][]byte) {
	count, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	e, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addInt(0)
		return
	}
	items := l.items()
	limit := count
	if limit < 0 {
		limit = -limit
	}
	if count == 0 {
		limit = math.MaxInt64
	}
	remove := make([]bool, len(items))
	removed := int64(0)
	if count >= 0 {
		for i := 0; i < len(items) && removed < limit; i++ {
			if bytes.Equal(items[i], a[3]) {
				remove[i] = true
				removed++
			}
		}
	} else {
		for i := len(items) - 1; i >= 0 && removed < limit; i-- {
			if bytes.Equal(items[i], a[3]) {
				remove[i] = true
				removed++
			}
		}
	}
	if removed > 0 {
		out := make([][]byte, 0, len(items)-int(removed))
		for i, it := range items {
			if !remove[i] {
				out = append(out, it)
			}
		}
		l.replace(out)
		if l.Len() == 0 {
			c.db.remove(e)
		}
	}
	c.addInt(removed)
}

func cmdLTrim(c *Client, a [][]byte) {
	start, ok1 := parseInt64(a[2])
	end, ok2 := parseInt64(a[3])
	if !ok1 || !ok2 {
		c.addErr(errNotInt)
		return
	}
	e, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	if l == nil {
		c.addSimple("OK")
		return
	}
	s, en, ok := clampRange(start, end, l.Len())
	if !ok {
		c.db.remove(e)
	} else {
		l.replace(append([][]byte(nil), l.items()[s:en+1]...))
	}
	c.addSimple("OK")
}

func cmdLPos(c *Client, a [][]byte) {
	rank := int64(1)
	count := int64(-1)
	maxlen := int64(0)
	for i := 3; i < len(a); i += 2 {
		if i+1 >= len(a) {
			c.addErr(errSyntax)
			return
		}
		opt := strings.ToUpper(string(a[i]))
		n, ok := parseInt64(a[i+1])
		switch opt {
		case "RANK":
			if !ok {
				c.addErr(errNotInt)
				return
			}
			if n == 0 {
				c.addErr("ERR RANK can't be zero: use 1 to start from the first match, 2 from the second ... or use negative to start from the end of the list")
				return
			}
			if n == math.MinInt64 {
				c.addErr("ERR value is out of range")
				return
			}
			rank = n
		case "COUNT":
			if !ok {
				c.addErr(errNotInt)
				return
			}
			if n < 0 {
				c.addErr("ERR COUNT can't be negative")
				return
			}
			count = n
		case "MAXLEN":
			if !ok {
				c.addErr(errNotInt)
				return
			}
			if n < 0 {
				c.addErr("ERR MAXLEN can't be negative")
				return
			}
			maxlen = n
		default:
			c.addErr(errSyntax)
			return
		}
	}
	_, l, ok := c.getList(string(a[1]))
	if !ok {
		return
	}
	var matches []int
	if l != nil {
		items := l.items()
		n := len(items)
		skip := rank - 1
		step, i := 1, 0
		if rank < 0 {
			skip = -rank - 1
			step, i = -1, n-1
		}
		for cmps := int64(0); i >= 0 && i < n; i, cmps = i+step, cmps+1 {
			if maxlen > 0 && cmps >= maxlen {
				break
			}
			if bytes.Equal(items[i], a[2]) {
				if skip > 0 {
					skip--
					continue
				}
				matches = append(matches, i)
				if count < 0 || (count > 0 && int64(len(matches)) == count) {
					break
				}
			}
		}
	}
	if count >= 0 {
		c.addArrayLen(len(matches))
		for _, m := range matches {
			c.addInt(int64(m))
		}
		return
	}
	if len(matches) == 0 {
		c.addNil()
	} else {
		c.addInt(int64(matches[0]))
	}
}

// moveElem implements LMOVE semantics. ok=false means an error was written;
// moved=false means the source was empty.
func moveElem(c *Client, src, dst string, srcLeft, dstLeft bool) ([]byte, bool, bool) {
	se, sl, ok := c.getList(src)
	if !ok {
		return nil, false, false
	}
	de, dl, ok := c.getList(dst)
	if !ok {
		return nil, false, false
	}
	if sl == nil {
		return nil, false, true
	}
	v := popSide(sl, srcLeft)
	if sl.Len() == 0 {
		c.db.remove(se)
	}
	if dl == nil || de == nil {
		dl = &List{}
		c.db.add(dst, dl)
	}
	pushSide(dl, v, dstLeft)
	c.db.signalKey(dst)
	return v, true, true
}

func cmdRPopLPush(c *Client, a [][]byte) {
	v, moved, ok := moveElem(c, string(a[1]), string(a[2]), false, true)
	if !ok {
		return
	}
	if !moved {
		c.addNil()
		return
	}
	c.addBulk(v)
}

func parseSide(b []byte) (left, ok bool) {
	switch strings.ToUpper(string(b)) {
	case "LEFT":
		return true, true
	case "RIGHT":
		return false, true
	}
	return false, false
}

func cmdLMove(c *Client, a [][]byte) {
	sl, ok1 := parseSide(a[3])
	dl, ok2 := parseSide(a[4])
	if !ok1 || !ok2 {
		c.addErr(errSyntax)
		return
	}
	v, moved, ok := moveElem(c, string(a[1]), string(a[2]), sl, dl)
	if !ok {
		return
	}
	if !moved {
		c.addNil()
		return
	}
	c.addBulk(v)
}

func cmdBLMove(c *Client, a [][]byte) {
	sl, ok1 := parseSide(a[3])
	dl, ok2 := parseSide(a[4])
	if !ok1 || !ok2 {
		c.addErr(errSyntax)
		return
	}
	blockMove(c, a[1], a[2], sl, dl, a[5])
}

func cmdBRPopLPush(c *Client, a [][]byte) {
	blockMove(c, a[1], a[2], false, true, a[3])
}

func blockMove(c *Client, src, dst []byte, sl, dl bool, timeout []byte) {
	deadline, ok := parseTimeout(c, timeout)
	if !ok {
		return
	}
	v, moved, ok := moveElem(c, string(src), string(dst), sl, dl)
	if !ok {
		return
	}
	if moved {
		c.addBulk(v)
		return
	}
	if c.inTx {
		c.addNil()
		return
	}
	c.block(&blockInfo{db: c.db, keys: []string{string(src)}, kind: blkMove, left: sl,
		dst: string(dst), dstLeft: dl, deadline: deadline})
}

func cmdBPop(c *Client, a [][]byte, left bool) {
	deadline, ok := parseTimeout(c, a[len(a)-1])
	if !ok {
		return
	}
	keys := a[1 : len(a)-1]
	for _, k := range keys {
		e, l, ok := c.getList(string(k))
		if !ok {
			return
		}
		if l == nil || l.Len() == 0 {
			continue
		}
		v := popSide(l, left)
		if l.Len() == 0 {
			c.db.remove(e)
		}
		c.addArrayLen(2)
		c.addBulk(k)
		c.addBulk(v)
		return
	}
	if c.inTx {
		c.addNilArray()
		return
	}
	names := make([]string, len(keys))
	for i, k := range keys {
		names[i] = string(k)
	}
	c.block(&blockInfo{db: c.db, keys: names, kind: blkPop, left: left, deadline: deadline})
}
