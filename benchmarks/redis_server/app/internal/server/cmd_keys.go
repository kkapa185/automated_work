package server

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

func registerKeys(s *Server) {
	s.register("del", -2, true, cmdDel)
	s.register("unlink", -2, true, cmdDel)
	s.register("exists", -2, false, cmdExists)
	s.register("touch", -2, false, cmdExists)
	s.register("type", 2, false, cmdType)
	s.register("keys", 2, false, cmdKeys)
	s.register("scan", -2, false, cmdScan)
	s.register("rename", 3, true, func(c *Client, a [][]byte) { cmdRename(c, a, false) })
	s.register("renamenx", 3, true, func(c *Client, a [][]byte) { cmdRename(c, a, true) })
	s.register("move", 3, true, cmdMove)
	s.register("randomkey", 1, false, cmdRandomKey)
	s.register("expire", -3, true, func(c *Client, a [][]byte) { cmdExpire(c, a, 1000, false) })
	s.register("pexpire", -3, true, func(c *Client, a [][]byte) { cmdExpire(c, a, 1, false) })
	s.register("expireat", -3, true, func(c *Client, a [][]byte) { cmdExpire(c, a, 1000, true) })
	s.register("pexpireat", -3, true, func(c *Client, a [][]byte) { cmdExpire(c, a, 1, true) })
	s.register("ttl", 2, false, func(c *Client, a [][]byte) { cmdTTL(c, a, false, false) })
	s.register("pttl", 2, false, func(c *Client, a [][]byte) { cmdTTL(c, a, true, false) })
	s.register("expiretime", 2, false, func(c *Client, a [][]byte) { cmdTTL(c, a, false, true) })
	s.register("pexpiretime", 2, false, func(c *Client, a [][]byte) { cmdTTL(c, a, true, true) })
	s.register("persist", 2, true, cmdPersist)
	s.register("copy", -3, true, cmdCopy)
	s.register("object", -2, false, cmdObject)
}

func cmdDel(c *Client, a [][]byte) {
	n := int64(0)
	for _, k := range a[1:] {
		if c.db.del(string(k)) {
			n++
		}
	}
	c.addInt(n)
}

func cmdExists(c *Client, a [][]byte) {
	n := int64(0)
	for _, k := range a[1:] {
		if c.db.lookup(string(k)) != nil {
			n++
		}
	}
	c.addInt(n)
}

func cmdType(c *Client, a [][]byte) {
	if e := c.db.lookup(string(a[1])); e != nil {
		c.addSimple(typeName(e.val))
	} else {
		c.addSimple("none")
	}
}

func cmdKeys(c *Client, a [][]byte) {
	pat := a[1]
	all := len(pat) == 1 && pat[0] == '*'
	now := nowMs()
	var out []string
	var dead []*entry
	for k, e := range c.db.data {
		if e.exp != 0 && e.exp <= now {
			dead = append(dead, e)
			continue
		}
		if all || globMatch(pat, []byte(k)) {
			out = append(out, k)
		}
	}
	for _, e := range dead {
		c.db.remove(e)
		c.srv.stats.expired++
	}
	c.addArrayLen(len(out))
	for _, k := range out {
		c.addBulkStr(k)
	}
}

func cmdScan(c *Client, a [][]byte) {
	cur, err := strconv.ParseUint(string(a[1]), 10, 64)
	if err != nil {
		c.addErr("ERR invalid cursor")
		return
	}
	count := 10
	var pat []byte
	var typ string
	for i := 2; i < len(a); i++ {
		opt := strings.ToUpper(string(a[i]))
		if i+1 >= len(a) {
			c.addErr(errSyntax)
			return
		}
		switch opt {
		case "COUNT":
			n, ok := parseInt64(a[i+1])
			if !ok {
				c.addErr(errNotInt)
				return
			}
			if n < 1 {
				c.addErr(errSyntax)
				return
			}
			count = int(min(n, math.MaxInt32))
		case "MATCH":
			pat = a[i+1]
		case "TYPE":
			typ = strings.ToLower(string(a[i+1]))
		default:
			c.addErr(errSyntax)
			return
		}
		i++
	}
	var match func(*entry) bool
	if (pat != nil && !(len(pat) == 1 && pat[0] == '*')) || typ != "" {
		match = func(e *entry) bool {
			if typ != "" && typeName(e.val) != typ {
				return false
			}
			return pat == nil || globMatch(pat, []byte(e.key))
		}
	}
	var keys []string
	next := c.db.scan(cur, count, match, &keys)
	c.addArrayLen(2)
	c.addBulkStr(strconv.FormatUint(next, 10))
	c.addArrayLen(len(keys))
	for _, k := range keys {
		c.addBulkStr(k)
	}
}

func cmdRename(c *Client, a [][]byte, nx bool) {
	src, dst := string(a[1]), string(a[2])
	e := c.db.lookup(src)
	if e == nil {
		c.addErr(errNoKey)
		return
	}
	if src == dst {
		if nx {
			c.addInt(0)
		} else {
			c.addSimple("OK")
		}
		return
	}
	if nx && c.db.lookup(dst) != nil {
		c.addInt(0)
		return
	}
	val, exp := e.val, e.exp
	c.db.del(dst)
	c.db.remove(e)
	ne := c.db.add(dst, val)
	c.db.setExp(ne, exp)
	if nx {
		c.addInt(1)
	} else {
		c.addSimple("OK")
	}
}

func parseDBIndex(c *Client, b []byte) (*DB, bool) {
	n, ok := parseInt64(b)
	if !ok {
		c.addErr(errNotInt)
		return nil, false
	}
	if n < 0 || n >= numDBs {
		c.addErr("ERR DB index is out of range")
		return nil, false
	}
	return c.srv.dbs[n], true
}

func cmdMove(c *Client, a [][]byte) {
	dst, ok := parseDBIndex(c, a[2])
	if !ok {
		return
	}
	if dst == c.db {
		c.addErr("ERR source and destination objects are the same")
		return
	}
	key := string(a[1])
	e := c.db.lookup(key)
	if e == nil || dst.lookup(key) != nil {
		c.addInt(0)
		return
	}
	val, exp := e.val, e.exp
	c.db.remove(e)
	ne := dst.add(key, val)
	dst.setExp(ne, exp)
	c.addInt(1)
}

func cmdRandomKey(c *Client, a [][]byte) {
	if k, ok := c.db.randomKey(); ok {
		c.addBulkStr(k)
	} else {
		c.addNil()
	}
}

// toAbsMs converts v (seconds or ms, relative or absolute) into an absolute
// unix-ms deadline, reporting overflow.
func toAbsMs(v, unit int64, absolute bool) (int64, bool) {
	if v > math.MaxInt64/unit || v < math.MinInt64/unit {
		return 0, false
	}
	ms := v * unit
	if !absolute {
		now := nowMs()
		if ms > math.MaxInt64-now {
			return 0, false
		}
		ms += now
	}
	return ms, true
}

func cmdExpire(c *Client, a [][]byte, unit int64, absolute bool) {
	name := strings.ToLower(string(a[0]))
	v, ok := parseInt64(a[2])
	if !ok {
		c.addErr(errNotInt)
		return
	}
	var nx, xx, gt, lt bool
	for _, o := range a[3:] {
		switch strings.ToUpper(string(o)) {
		case "NX":
			nx = true
		case "XX":
			xx = true
		case "GT":
			gt = true
		case "LT":
			lt = true
		default:
			c.addErr("ERR Unsupported option " + string(o))
			return
		}
	}
	if nx && (xx || gt || lt) {
		c.addErr("ERR NX and XX, GT or LT options at the same time are not compatible")
		return
	}
	if gt && lt {
		c.addErr("ERR GT and LT options at the same time are not compatible")
		return
	}
	when, ok := toAbsMs(v, unit, absolute)
	if !ok {
		c.addErr(fmt.Sprintf("ERR invalid expire time in '%s' command", name))
		return
	}
	e := c.db.lookup(string(a[1]))
	if e == nil {
		c.addInt(0)
		return
	}
	if (nx && e.exp != 0) || (xx && e.exp == 0) ||
		(gt && (e.exp == 0 || when <= e.exp)) || (lt && e.exp != 0 && when >= e.exp) {
		c.addInt(0)
		return
	}
	if when <= nowMs() {
		c.db.remove(e)
	} else {
		c.db.setExp(e, when)
	}
	c.addInt(1)
}

func cmdTTL(c *Client, a [][]byte, ms, absolute bool) {
	e := c.db.lookup(string(a[1]))
	switch {
	case e == nil:
		c.addInt(-2)
	case e.exp == 0:
		c.addInt(-1)
	default:
		v := e.exp
		if !absolute {
			v -= nowMs()
			if v < 0 {
				v = 0
			}
		}
		if !ms {
			v = (v + 500) / 1000
		}
		c.addInt(v)
	}
}

func cmdPersist(c *Client, a [][]byte) {
	e := c.db.lookup(string(a[1]))
	if e == nil || e.exp == 0 {
		c.addInt(0)
		return
	}
	c.db.setExp(e, 0)
	c.addInt(1)
}

func cmdCopy(c *Client, a [][]byte) {
	dstDB := c.db
	replace := false
	for i := 3; i < len(a); i++ {
		switch strings.ToUpper(string(a[i])) {
		case "REPLACE":
			replace = true
		case "DB":
			if i+1 >= len(a) {
				c.addErr(errSyntax)
				return
			}
			d, ok := parseDBIndex(c, a[i+1])
			if !ok {
				return
			}
			dstDB = d
			i++
		default:
			c.addErr(errSyntax)
			return
		}
	}
	src, dst := string(a[1]), string(a[2])
	if dstDB == c.db && src == dst {
		c.addErr("ERR source and destination objects are the same")
		return
	}
	e := c.db.lookup(src)
	if e == nil {
		c.addInt(0)
		return
	}
	if dstDB.lookup(dst) != nil {
		if !replace {
			c.addInt(0)
			return
		}
		dstDB.del(dst)
	}
	ne := dstDB.add(dst, cloneValue(e.val))
	dstDB.setExp(ne, e.exp)
	c.addInt(1)
}

func cmdObject(c *Client, a [][]byte) {
	sub := strings.ToUpper(string(a[1]))
	switch sub {
	case "ENCODING", "REFCOUNT", "IDLETIME", "FREQ":
		if len(a) != 3 {
			c.addErr(fmt.Sprintf("ERR wrong number of arguments for 'object|%s' command", strings.ToLower(sub)))
			return
		}
		e := c.db.lookup(string(a[2]))
		if e == nil {
			c.addNil()
			return
		}
		switch sub {
		case "ENCODING":
			c.addBulkStr(encodingOf(e.val, &c.srv.lim))
		case "REFCOUNT":
			c.addInt(1)
		default:
			c.addInt(0)
		}
	case "HELP":
		c.addArrayLen(1)
		c.addSimple("OBJECT <subcommand> [<arg> ...]. Subcommands: ENCODING, FREQ, IDLETIME, REFCOUNT.")
	default:
		c.addErr(fmt.Sprintf("ERR unknown subcommand '%s'. Try OBJECT HELP.", a[1]))
	}
}
