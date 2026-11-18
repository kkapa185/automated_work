package server

import "strings"

func registerTx(s *Server) {
	s.register("multi", 1, false, cmdMulti)
	s.register("exec", 1, false, cmdExec)
	s.register("discard", 1, false, cmdDiscard)
	s.register("watch", -2, false, cmdWatch)
	s.register("unwatch", 1, false, cmdUnwatch)
	s.register("reset", 1, false, cmdReset)
}

// fingerprint captures everything WATCH must notice: the entry identity, its
// expiry, and modification counters of the entry / typed object. Any write
// (even one that stores an identical value) changes it.
type fingerprint struct {
	e    *entry
	exp  int64
	ever uint64
	over uint64
}

func objVersion(v any) uint64 {
	switch x := v.(type) {
	case *List:
		return x.ver
	case *Hash:
		return x.ver
	case *Set:
		return x.ver
	case *ZSet:
		return x.ver
	}
	return 0
}

func fingerprintOf(d *DB, key string) fingerprint {
	e := d.data[key]
	if e == nil || (e.exp != 0 && e.exp <= nowMs()) { // logically absent
		return fingerprint{}
	}
	return fingerprint{e: e, exp: e.exp, ever: e.ver, over: objVersion(e.val)}
}

type watchEntry struct {
	db  *DB
	key string
	fp  fingerprint
}

func (w watchEntry) dirty() bool { return fingerprintOf(w.db, w.key) != w.fp }

func cmdMulti(c *Client, a [][]byte) {
	if c.multi {
		c.addErr("ERR MULTI calls can not be nested")
		return
	}
	c.multi = true
	c.addSimple("OK")
}

func cmdDiscard(c *Client, a [][]byte) {
	if !c.multi {
		c.addErr("ERR DISCARD without MULTI")
		return
	}
	c.clearTx()
	c.addSimple("OK")
}

func (c *Client) clearTx() {
	c.multi, c.txDirty, c.txQueue, c.watched = false, false, nil, nil
}

func cmdExec(c *Client, a [][]byte) {
	if !c.multi {
		c.addErr("ERR EXEC without MULTI")
		return
	}
	queue, dirty, watched := c.txQueue, c.txDirty, c.watched
	c.clearTx()
	if dirty {
		c.addErr("EXECABORT Transaction discarded because of previous errors.")
		return
	}
	for _, w := range watched {
		if w.dirty() {
			c.addNilArray()
			return
		}
	}
	c.inTx = true
	c.addArrayLen(len(queue))
	for _, q := range queue {
		cmd := c.srv.cmds[strings.ToLower(string(q[0]))]
		c.srv.stats.commands++
		cmd.fn(c, q)
	}
	c.inTx = false
}

func cmdWatch(c *Client, a [][]byte) {
	if c.multi {
		c.addErr("ERR WATCH inside MULTI is not allowed")
		return
	}
	for _, k := range a[1:] {
		key := string(k)
		c.watched = append(c.watched, watchEntry{c.db, key, fingerprintOf(c.db, key)})
	}
	c.addSimple("OK")
}

func cmdUnwatch(c *Client, a [][]byte) {
	c.watched = nil
	c.addSimple("OK")
}

// cmdReset restores the connection to its initial state.
func cmdReset(c *Client, a [][]byte) {
	c.clearTx()
	c.srv.unsubscribeAll(c)
	c.db = c.srv.dbs[0]
	c.name = ""
	c.addSimple("RESET")
}
