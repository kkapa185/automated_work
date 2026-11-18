package server

import (
	"fmt"
	"math"
	"strings"
)

const maxStringLen = 512 * 1024 * 1024

func registerStrings(s *Server) {
	s.register("get", 2, false, cmdGet)
	s.register("set", -3, true, cmdSet)
	s.register("setnx", 3, true, cmdSetNX)
	s.register("setex", 4, true, func(c *Client, a [][]byte) { cmdSetEx(c, a, 1000) })
	s.register("psetex", 4, true, func(c *Client, a [][]byte) { cmdSetEx(c, a, 1) })
	s.register("mget", -2, false, cmdMGet)
	s.register("mset", -3, true, func(c *Client, a [][]byte) { cmdMSet(c, a, false) })
	s.register("msetnx", -3, true, func(c *Client, a [][]byte) { cmdMSet(c, a, true) })
	s.register("getset", 3, true, cmdGetSet)
	s.register("getdel", 2, true, cmdGetDel)
	s.register("getex", -2, true, cmdGetEx)
	s.register("append", 3, true, cmdAppend)
	s.register("strlen", 2, false, cmdStrlen)
	s.register("incr", 2, true, func(c *Client, a [][]byte) { incrBy(c, a[1], 1) })
	s.register("decr", 2, true, func(c *Client, a [][]byte) { incrBy(c, a[1], -1) })
	s.register("incrby", 3, true, func(c *Client, a [][]byte) { cmdIncrBy(c, a, false) })
	s.register("decrby", 3, true, func(c *Client, a [][]byte) { cmdIncrBy(c, a, true) })
	s.register("incrbyfloat", 3, true, cmdIncrByFloat)
	s.register("getrange", 4, false, cmdGetRange)
	s.register("substr", 4, false, cmdGetRange)
	s.register("setrange", 4, true, cmdSetRange)
}

// getStr fetches a string value. ok=false means WRONGTYPE was already sent.
// e is nil when the key does not exist.
func (c *Client) getStr(key string) (e *entry, ok bool) {
	e = c.db.lookup(key)
	if e == nil {
		return nil, true
	}
	if _, isStr := e.val.([]byte); !isStr {
		c.addErr(errWrongType)
		return nil, false
	}
	return e, true
}

func cmdGet(c *Client, a [][]byte) {
	e, ok := c.getStr(string(a[1]))
	if !ok {
		return
	}
	if e == nil {
		c.addNil()
		return
	}
	c.addBulk(e.val.([]byte))
}

func cmdSet(c *Client, a [][]byte) {
	key, val := string(a[1]), a[2]
	var nx, xx, get, keep bool
	var kind string
	var arg []byte
	for i := 3; i < len(a); i++ {
		switch opt := strings.ToUpper(string(a[i])); opt {
		case "NX":
			if xx {
				c.addErr(errSyntax)
				return
			}
			nx = true
		case "XX":
			if nx {
				c.addErr(errSyntax)
				return
			}
			xx = true
		case "GET":
			get = true
		case "KEEPTTL":
			if kind != "" {
				c.addErr(errSyntax)
				return
			}
			keep = true
		case "EX", "PX", "EXAT", "PXAT":
			if kind != "" || keep || i+1 >= len(a) {
				c.addErr(errSyntax)
				return
			}
			kind = opt
			i++
			arg = a[i]
		default:
			c.addErr(errSyntax)
			return
		}
	}
	var when int64
	if kind != "" {
		n, ok := parseInt64(arg)
		if !ok {
			c.addErr(errNotInt)
			return
		}
		unit := int64(1000)
		if kind == "PX" || kind == "PXAT" {
			unit = 1
		}
		var ok2 bool
		when, ok2 = toAbsMs(n, unit, kind == "EXAT" || kind == "PXAT")
		if n <= 0 || !ok2 {
			c.addErr("ERR invalid expire time in 'set' command")
			return
		}
	}
	old := c.db.lookup(key)
	if get && old != nil {
		if _, isStr := old.val.([]byte); !isStr {
			c.addErr(errWrongType)
			return
		}
	}
	exists := old != nil
	var oldVal []byte
	if get && exists {
		oldVal = old.val.([]byte)
	}
	if (nx && exists) || (xx && !exists) {
		if get {
			c.replyOld(oldVal, exists)
		} else {
			c.addNil()
		}
		return
	}
	var e *entry
	if keep {
		e = c.db.setKeepTTL(key, val)
	} else {
		e = c.db.set(key, val)
	}
	if kind != "" {
		if when <= nowMs() {
			c.db.remove(e)
		} else {
			c.db.setExp(e, when)
		}
	}
	if get {
		c.replyOld(oldVal, exists)
	} else {
		c.addSimple("OK")
	}
}

func (c *Client) replyOld(v []byte, exists bool) {
	if exists {
		c.addBulk(v)
	} else {
		c.addNil()
	}
}

func cmdSetNX(c *Client, a [][]byte) {
	key := string(a[1])
	if c.db.lookup(key) != nil {
		c.addInt(0)
		return
	}
	c.db.add(key, a[2])
	c.addInt(1)
}

func cmdSetEx(c *Client, a [][]byte, unit int64) {
	name := strings.ToLower(string(a[0]))
	n, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	when, ok := toAbsMs(n, unit, false)
	if n <= 0 || !ok {
		c.addErr(fmt.Sprintf("ERR invalid expire time in '%s' command", name))
		return
	}
	e := c.db.set(string(a[1]), a[3])
	c.db.setExp(e, when)
	c.addSimple("OK")
}

func cmdMGet(c *Client, a [][]byte) {
	c.addArrayLen(len(a) - 1)
	for _, k := range a[1:] {
		e := c.db.lookup(string(k))
		if e == nil {
			c.addNil()
			continue
		}
		if v, ok := e.val.([]byte); ok {
			c.addBulk(v)
		} else {
			c.addNil()
		}
	}
}

func cmdMSet(c *Client, a [][]byte, nx bool) {
	if len(a)%2 != 1 {
		c.addErr(fmt.Sprintf("ERR wrong number of arguments for '%s' command", strings.ToLower(string(a[0]))))
		return
	}
	if nx {
		for i := 1; i < len(a); i += 2 {
			if c.db.lookup(string(a[i])) != nil {
				c.addInt(0)
				return
			}
		}
	}
	for i := 1; i < len(a); i += 2 {
		c.db.set(string(a[i]), a[i+1])
	}
	if nx {
		c.addInt(1)
	} else {
		c.addSimple("OK")
	}
}

func cmdGetSet(c *Client, a [][]byte) {
	key := string(a[1])
	e, ok := c.getStr(key)
	if !ok {
		return
	}
	if e == nil {
		c.addNil()
	} else {
		c.addBulk(e.val.([]byte))
	}
	c.db.set(key, a[2])
}

func cmdGetDel(c *Client, a [][]byte) {
	e, ok := c.getStr(string(a[1]))
	if !ok {
		return
	}
	if e == nil {
		c.addNil()
		return
	}
	c.addBulk(e.val.([]byte))
	c.db.remove(e)
}

func cmdGetEx(c *Client, a [][]byte) {
	var kind string
	var arg []byte
	for i := 2; i < len(a); i++ {
		opt := strings.ToUpper(string(a[i]))
		switch opt {
		case "PERSIST":
			if kind != "" {
				c.addErr(errSyntax)
				return
			}
			kind = opt
		case "EX", "PX", "EXAT", "PXAT":
			if kind != "" || i+1 >= len(a) {
				c.addErr(errSyntax)
				return
			}
			kind = opt
			i++
			arg = a[i]
		default:
			c.addErr(errSyntax)
			return
		}
	}
	var when int64
	if kind != "" && kind != "PERSIST" {
		n, ok := parseInt64(arg)
		if !ok {
			c.addErr(errNotInt)
			return
		}
		unit := int64(1000)
		if kind == "PX" || kind == "PXAT" {
			unit = 1
		}
		var ok2 bool
		when, ok2 = toAbsMs(n, unit, kind == "EXAT" || kind == "PXAT")
		if n <= 0 || !ok2 {
			c.addErr("ERR invalid expire time in 'getex' command")
			return
		}
	}
	e, ok := c.getStr(string(a[1]))
	if !ok {
		return
	}
	if e == nil {
		c.addNil()
		return
	}
	c.addBulk(e.val.([]byte))
	switch kind {
	case "PERSIST":
		c.db.setExp(e, 0)
	case "":
	default:
		if when <= nowMs() {
			c.db.remove(e)
		} else {
			c.db.setExp(e, when)
		}
	}
}

func cmdAppend(c *Client, a [][]byte) {
	key := string(a[1])
	e, ok := c.getStr(key)
	if !ok {
		return
	}
	if e == nil {
		c.db.add(key, a[2])
		c.addInt(int64(len(a[2])))
		return
	}
	cur := e.val.([]byte)
	if len(cur)+len(a[2]) > maxStringLen {
		c.addErr("ERR string exceeds maximum allowed size (proto-max-bulk-len)")
		return
	}
	e.ver++
	e.val = append(cur, a[2]...)
	c.addInt(int64(len(e.val.([]byte))))
}

func cmdStrlen(c *Client, a [][]byte) {
	e, ok := c.getStr(string(a[1]))
	if !ok {
		return
	}
	if e == nil {
		c.addInt(0)
		return
	}
	c.addInt(int64(len(e.val.([]byte))))
}

// incrBy adds delta to the integer string at key.
func incrBy(c *Client, keyb []byte, delta int64) {
	key := string(keyb)
	e, ok := c.getStr(key)
	if !ok {
		return
	}
	var cur int64
	if e != nil {
		cur, ok = parseInt64(e.val.([]byte))
		if !ok {
			c.addErr(errNotInt)
			return
		}
	}
	if (delta > 0 && cur > math.MaxInt64-delta) || (delta < 0 && cur < math.MinInt64-delta) {
		c.addErr("ERR increment or decrement would overflow")
		return
	}
	cur += delta
	nv := appendInt(nil, 0, cur)
	nv = nv[1 : len(nv)-2]
	if e == nil {
		c.db.add(key, nv)
	} else {
		e.ver++
		e.val = nv
	}
	c.addInt(cur)
}

func cmdIncrBy(c *Client, a [][]byte, dec bool) {
	d, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	if dec {
		if d == math.MinInt64 {
			c.addErr("ERR decrement would overflow")
			return
		}
		d = -d
	}
	incrBy(c, a[1], d)
}

func cmdIncrByFloat(c *Client, a [][]byte) {
	key := string(a[1])
	inc, ok := parseLongDouble(a[2])
	if !ok {
		c.addErr(errNotFloat)
		return
	}
	e, ok := c.getStr(key)
	if !ok {
		return
	}
	cur, _ := parseLongDouble([]byte("0"))
	if e != nil {
		cur, ok = parseLongDouble(e.val.([]byte))
		if !ok {
			c.addErr(errNotFloat)
			return
		}
	}
	sum, ok := addLongDouble(cur, inc)
	if !ok {
		c.addErr("ERR increment would produce NaN or Infinity")
		return
	}
	s := []byte(formatLongDouble(sum))
	if e == nil {
		c.db.add(key, s)
	} else {
		e.ver++
		e.val = s
	}
	c.addBulk(s)
}

func cmdGetRange(c *Client, a [][]byte) {
	start, ok1 := parseInt64(a[2])
	end, ok2 := parseInt64(a[3])
	if !ok1 || !ok2 {
		c.addErr(errNotInt)
		return
	}
	e, ok := c.getStr(string(a[1]))
	if !ok {
		return
	}
	if e == nil {
		c.addBulkStr("")
		return
	}
	s := e.val.([]byte)
	n := int64(len(s))
	if start < 0 && end < 0 && start > end {
		c.addBulkStr("")
		return
	}
	if start < 0 {
		start += n
	}
	if end < 0 {
		end += n
	}
	if start < 0 {
		start = 0
	}
	if end < 0 {
		end = 0
	}
	if end >= n {
		end = n - 1
	}
	if n == 0 || start > end {
		c.addBulkStr("")
		return
	}
	c.addBulk(s[start : end+1])
}

func cmdSetRange(c *Client, a [][]byte) {
	key := string(a[1])
	off, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	if off < 0 {
		c.addErr("ERR offset is out of range")
		return
	}
	e, ok := c.getStr(key)
	if !ok {
		return
	}
	val := a[3]
	if len(val) == 0 {
		if e == nil {
			c.addInt(0)
		} else {
			c.addInt(int64(len(e.val.([]byte))))
		}
		return
	}
	if off+int64(len(val)) > maxStringLen {
		c.addErr("ERR string exceeds maximum allowed size (proto-max-bulk-len)")
		return
	}
	var cur []byte
	if e != nil {
		cur = e.val.([]byte)
	}
	need := int(off) + len(val)
	if len(cur) < need {
		cur = append(cur, make([]byte, need-len(cur))...)
	}
	copy(cur[off:], val)
	if e == nil {
		c.db.add(key, cur)
	} else {
		e.ver++
		e.val = cur
	}
	c.addInt(int64(len(cur)))
}
