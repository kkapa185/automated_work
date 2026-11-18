package server

import (
	"errors"
	"math"
	"os"
	"time"
)

const (
	blkPop  = iota // BLPOP / BRPOP
	blkMove        // BLMOVE / BRPOPLPUSH
)

// blockInfo describes a client parked on one or more list keys.
type blockInfo struct {
	db       *DB
	keys     []string
	kind     int
	left     bool   // pop from the head (BLPOP) / source side (BLMOVE)
	dst      string // BLMOVE destination
	dstLeft  bool
	deadline time.Time // zero = forever
	done     chan struct{}
}

type readyKey struct {
	db  *DB
	key string
}

// signalIfList notes that a list may now satisfy blocked clients.
func (d *DB) signalIfList(key string, v any) {
	if _, ok := v.(*List); ok {
		d.signalKey(key)
	}
}

func (d *DB) signalKey(key string) {
	if len(d.waiters[key]) > 0 {
		d.srv.ready = append(d.srv.ready, readyKey{d, key})
	}
}

func (s *Server) blockedCount() int {
	n := 0
	for _, c := range s.clients {
		if c.blk != nil {
			n++
		}
	}
	return n
}

// block parks c until one of keys has data or the timeout passes.
func (c *Client) block(b *blockInfo) {
	c.flush() // keep reply ordering: earlier pipelined replies go out first
	b.done = make(chan struct{})
	c.blk = b
	for _, k := range b.keys {
		b.db.waiters[k] = append(b.db.waiters[k], c)
	}
}

// unblock removes c from every wait queue. Caller holds s.mu.
func (s *Server) unblock(c *Client) {
	b := c.blk
	if b == nil {
		return
	}
	for _, k := range b.keys {
		q := b.db.waiters[k]
		for i, w := range q {
			if w == c {
				q = append(q[:i:i], q[i+1:]...)
				break
			}
		}
		if len(q) == 0 {
			delete(b.db.waiters, k)
		} else {
			b.db.waiters[k] = q
		}
	}
	c.blk = nil
	close(b.done)
}

// handleBlocked serves waiters (FIFO per key) for keys that received data.
// Caller holds s.mu.
func (s *Server) handleBlocked() {
	for len(s.ready) > 0 {
		r := s.ready[0]
		s.ready = s.ready[1:]
		for len(r.db.waiters[r.key]) > 0 {
			e := r.db.lookup(r.key)
			if e == nil {
				break
			}
			l, ok := e.val.(*List)
			if !ok || l.Len() == 0 {
				break
			}
			c := r.db.waiters[r.key][0]
			s.serveWaiter(c, r.db, e, l)
		}
	}
}

func (s *Server) serveWaiter(c *Client, d *DB, e *entry, l *List) {
	b := c.blk
	var tmp Client
	switch b.kind {
	case blkPop:
		var v []byte
		if b.left {
			v = l.popFront()
		} else {
			v = l.popBack()
		}
		tmp.addArrayLen(2)
		tmp.addBulkStr(e.key)
		tmp.addBulk(v)
		if l.Len() == 0 {
			d.remove(e)
		}
	case blkMove:
		de := d.lookup(b.dst)
		var dl *List
		if de != nil {
			var ok bool
			if dl, ok = de.val.(*List); !ok {
				tmp.addErr(errWrongType)
				s.unblock(c)
				c.push(tmp.buf)
				return
			}
		}
		v := popSide(l, b.left)
		if l.Len() == 0 {
			d.remove(e)
		}
		if dl == nil {
			dl = &List{}
			d.add(b.dst, dl)
		}
		pushSide(dl, v, b.dstLeft)
		d.signalKey(b.dst)
		tmp.addBulk(v)
	}
	s.unblock(c)
	c.push(tmp.buf)
}

func popSide(l *List, left bool) []byte {
	if left {
		return l.popFront()
	}
	return l.popBack()
}

func pushSide(l *List, v []byte, left bool) {
	if left {
		l.pushFront(v)
	} else {
		l.pushBack(v)
	}
}

// waitBlocked runs on the blocked client's own goroutine (without s.mu). It
// returns once the client was served, timed out, or its connection dropped.
func (c *Client) waitBlocked(b *blockInfo) {
	s := c.srv
	// Watch the socket without consuming data: Peek blocks until bytes arrive
	// or the peer closes.
	c.noFlush.Store(true)
	gone := make(chan struct{})
	stopped := make(chan struct{})
	go func() {
		defer close(stopped)
		if _, err := c.r.Peek(1); err != nil && !errors.Is(err, os.ErrDeadlineExceeded) {
			close(gone)
		}
	}()
	var timer <-chan time.Time
	if !b.deadline.IsZero() {
		t := time.NewTimer(time.Until(b.deadline))
		defer t.Stop()
		timer = t.C
	}
	select {
	case <-b.done:
	case <-timer:
		s.mu.Lock()
		if c.blk == b {
			s.unblock(c)
			if b.kind == blkMove {
				c.addNil()
			} else {
				c.addNilArray()
			}
		}
		s.mu.Unlock()
	case <-gone:
		s.mu.Lock()
		s.unblock(c)
		s.mu.Unlock()
	}
	c.conn.SetReadDeadline(time.Now())
	<-stopped
	c.conn.SetReadDeadline(time.Time{})
	c.noFlush.Store(false)
}

// parseTimeout parses a BLPOP-style timeout (seconds, may be fractional).
func parseTimeout(c *Client, arg []byte) (time.Time, bool) {
	f, ok := parseFloat(arg)
	if !ok || math.IsInf(f, 0) {
		c.addErr("ERR timeout is not a float or out of range")
		return time.Time{}, false
	}
	if f < 0 {
		c.addErr("ERR timeout is negative")
		return time.Time{}, false
	}
	if f == 0 {
		return time.Time{}, true
	}
	if f > 1e9*365*24 {
		c.addErr("ERR timeout is out of range")
		return time.Time{}, false
	}
	return time.Now().Add(time.Duration(f * float64(time.Second))), true
}
