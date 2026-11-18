// Package server implements a Redis-compatible (RESP2) server.
package server

import (
	"bufio"
	"fmt"
	"net"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	errSyntax    = "ERR syntax error"
	errWrongType = "WRONGTYPE Operation against a key holding the wrong kind of value"
	errNotInt    = "ERR value is not an integer or out of range"
	errNotFloat  = "ERR value is not a valid float"
	errNoKey     = "ERR no such key"

	maxPendingOut = 256 << 20 // a client whose unread output exceeds this is dropped
)

// Options configures a Server.
type Options struct {
	Port int
	Dir  string
}

type cmdFn func(c *Client, a [][]byte)

// Cmd is a registered command.
type Cmd struct {
	name  string
	arity int // >0 exact, <0 minimum (-n)
	write bool
	fn    cmdFn
}

type stats struct {
	commands, connections, expired, hits, misses int64
}

// Server holds all state. mu serialises command execution, giving every
// command (and MULTI/EXEC block) atomicity.
type Server struct {
	mu      sync.Mutex
	opts    Options
	dbs     [numDBs]*DB
	cmds    map[string]*Cmd
	cfg     map[string]string
	stats   stats
	started time.Time

	clients map[int64]*Client
	nextID  int64

	channels map[string]map[*Client]struct{} // pub/sub: channel -> subscribers
	patterns map[string]map[*Client]struct{} // pub/sub: pattern -> subscribers

	lim   limits
	ready []readyKey // keys that received list data while clients wait on them

	lastSave   int64 // unix seconds
	bgSaving   bool
	saveMu     sync.Mutex // serialises file writes
	snapshotOK bool
}

// New creates a server (not yet listening).
func New(o Options) *Server {
	s := &Server{opts: o, cmds: map[string]*Cmd{}, clients: map[int64]*Client{}, channels: map[string]map[*Client]struct{}{}, patterns: map[string]map[*Client]struct{}{}, started: time.Now()}
	for i := range s.dbs {
		s.dbs[i] = newDB(i, s)
	}
	s.cfg = defaultConfig(o)
	s.lastSave = time.Now().Unix()
	s.refreshLimits()
	registerAll(s)
	return s
}

func (s *Server) register(name string, arity int, write bool, fn cmdFn) {
	s.cmds[name] = &Cmd{name: name, arity: arity, write: write, fn: fn}
}

// Serve accepts connections until the listener is closed.
func (s *Server) Serve(ln net.Listener) error {
	go s.cron()
	for {
		conn, err := ln.Accept()
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				continue
			}
			return err
		}
		if tc, ok := conn.(*net.TCPConn); ok {
			tc.SetNoDelay(true)
		}
		go s.handle(conn)
	}
}

func (s *Server) cron() {
	t := time.NewTicker(100 * time.Millisecond)
	defer t.Stop()
	for range t.C {
		s.mu.Lock()
		s.activeExpire()
		s.mu.Unlock()
	}
}

// Client is one connection.
type Client struct {
	srv  *Server
	id   int64
	conn net.Conn
	r    *bufio.Reader
	db   *DB
	name string
	quit bool
	inTx bool // executing a transaction: blocking commands must not block

	multi   bool // between MULTI and EXEC: commands are queued
	txDirty bool // a queued command was rejected: EXEC must abort
	txQueue [][][]byte
	watched []watchEntry

	subs, psubs map[string]struct{} // pub/sub subscriptions

	blk     *blockInfo // non-nil while blocked in BLPOP & co (guarded by Server.mu)
	noFlush atomic.Bool

	buf []byte // replies produced by the executing goroutine

	omu  sync.Mutex // guards out/done/dead
	out  []byte
	done bool
	dead bool
	wake chan struct{}
}

// flushReader flushes pending replies right before the reader would block.
type flushReader struct{ c *Client }

func (f flushReader) Read(p []byte) (int, error) {
	if !f.c.noFlush.Load() {
		f.c.flush()
	}
	return f.c.conn.Read(p)
}

func (s *Server) handle(conn net.Conn) {
	c := &Client{srv: s, conn: conn, wake: make(chan struct{}, 1)}
	c.r = bufio.NewReaderSize(flushReader{c}, 64*1024)
	s.mu.Lock()
	s.nextID++
	c.id = s.nextID
	c.db = s.dbs[0]
	s.clients[c.id] = c
	s.stats.connections++
	s.mu.Unlock()
	go c.writeLoop()
	c.serve()
}

func (c *Client) serve() {
	defer c.finish()
	for {
		args, err := readCommand(c.r)
		if err != nil {
			if pe, ok := err.(*protoErr); ok {
				c.addErr("ERR Protocol error: " + pe.msg)
			}
			return
		}
		if args != nil {
			c.srv.execute(c, args)
			if c.quit {
				return
			}
		}
		if len(c.buf) > 64*1024 {
			c.flush()
		}
	}
}

func (c *Client) finish() {
	c.flush()
	c.omu.Lock()
	c.done = true
	c.omu.Unlock()
	c.notify()
	c.srv.mu.Lock()
	c.srv.dropClient(c)
	c.srv.mu.Unlock()
}

func (s *Server) dropClient(c *Client) {
	if c.blk != nil {
		s.unblock(c)
	}
	s.unsubscribeAll(c)
	delete(s.clients, c.id)
}

func (c *Client) notify() {
	select {
	case c.wake <- struct{}{}:
	default:
	}
}

// flush hands pending replies to the writer goroutine.
func (c *Client) flush() {
	if len(c.buf) == 0 {
		return
	}
	c.push(c.buf)
	if cap(c.buf) > 1<<20 {
		c.buf = nil
	} else {
		c.buf = c.buf[:0]
	}
}

// push appends raw bytes to the output queue; safe from any goroutine.
func (c *Client) push(b []byte) {
	c.omu.Lock()
	if !c.dead {
		c.out = append(c.out, b...)
		if len(c.out) > maxPendingOut {
			c.dead = true
			c.out = nil
			go c.conn.Close()
		}
	}
	c.omu.Unlock()
	c.notify()
}

func (c *Client) writeLoop() {
	var spare []byte
	for range c.wake {
		c.omu.Lock()
		data := c.out
		c.out = spare[:0]
		fin := c.done
		c.omu.Unlock()
		if len(data) > 0 {
			if _, err := c.conn.Write(data); err != nil {
				c.omu.Lock()
				c.dead = true
				c.out = nil
				c.omu.Unlock()
				c.conn.Close()
				return
			}
		}
		if cap(data) <= 1<<20 {
			spare = data
		} else {
			spare = nil
		}
		if fin {
			c.omu.Lock()
			pending := len(c.out)
			c.omu.Unlock()
			if pending == 0 {
				c.conn.Close()
				return
			}
			c.notify()
		}
	}
}

// execute runs one command for client c.
func (s *Server) execute(c *Client, args [][]byte) {
	name := strings.ToLower(string(args[0]))
	cmd := s.cmds[name]
	if cmd == nil {
		c.addErr(unknownCommandMsg(args))
		c.txDirty = c.txDirty || c.multi
		return
	}
	if (cmd.arity > 0 && len(args) != cmd.arity) || (cmd.arity < 0 && len(args) < -cmd.arity) {
		c.addErr(fmt.Sprintf("ERR wrong number of arguments for '%s' command", cmd.name))
		c.txDirty = c.txDirty || c.multi
		return
	}
	if c.subCount() > 0 && !subscribedOK[name] {
		c.addErr(fmt.Sprintf("ERR Can't execute '%s': only (P|S)SUBSCRIBE / (P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context", name))
		return
	}
	if c.multi && !txControl[name] {
		c.txQueue = append(c.txQueue, args)
		c.addSimple("QUEUED")
		return
	}
	s.mu.Lock()
	s.stats.commands++
	cmd.fn(c, args)
	if len(s.ready) > 0 {
		s.handleBlocked()
	}
	blk := c.blk
	s.mu.Unlock()
	if blk != nil {
		c.waitBlocked(blk)
	}
}

// commands executed immediately even between MULTI and EXEC
var txControl = map[string]bool{"multi": true, "exec": true, "discard": true, "watch": true, "quit": true, "reset": true}

func unknownCommandMsg(args [][]byte) string {
	var sb strings.Builder
	for _, a := range args[1:] {
		if sb.Len() > 128 {
			break
		}
		sb.WriteString("'" + string(a) + "' ")
	}
	name := string(args[0])
	if len(name) > 128 {
		name = name[:128]
	}
	return fmt.Sprintf("ERR unknown command '%s', with args beginning with: %s", name, sb.String())
}

func (s *Server) commandNames() []string {
	names := make([]string, 0, len(s.cmds))
	for n := range s.cmds {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}

func defaultConfig(o Options) map[string]string {
	return map[string]string{
		"port": fmt.Sprint(o.Port), "bind": "127.0.0.1", "dir": o.Dir, "dbfilename": "dump.kvdb",
		"save": "3600 1 300 100 60 10000", "appendonly": "no", "maxmemory": "0",
		"maxmemory-policy": "noeviction", "maxclients": "10000", "databases": "16",
		"timeout": "0", "hz": "10", "tcp-keepalive": "300", "loglevel": "notice",
		"list-max-listpack-size": "-2", "hash-max-listpack-entries": "128",
		"hash-max-listpack-value": "64", "set-max-intset-entries": "512",
		"set-max-listpack-entries": "128", "set-max-listpack-value": "64",
		"zset-max-listpack-entries": "128", "zset-max-listpack-value": "64",
		"proto-max-bulk-len": "536870912", "notify-keyspace-events": "",
	}
}
