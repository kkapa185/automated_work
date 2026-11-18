package server

import (
	"math/rand"
	"time"
)

const numDBs = 16

func nowMs() int64 { return time.Now().UnixMilli() }

// entry is one key in a database. exp is an absolute unix time in ms (0 = none).
type entry struct {
	key string
	val any // []byte (string) or one of the collection types
	exp int64
	idx int    // position in DB.keys
	ver uint64 // bumped when a string value changes (WATCH)
}

// DB is one logical database. All access happens under Server.mu.
type DB struct {
	id   int
	srv  *Server
	data map[string]*entry
	keys []*entry          // dense array used for SCAN / RANDOMKEY
	ttl  map[string]*entry // keys having an expiry (active expiry sampling)

	waiters map[string][]*Client // clients blocked on a list key, FIFO
}

func newDB(id int, s *Server) *DB {
	return &DB{id: id, srv: s, data: map[string]*entry{}, ttl: map[string]*entry{}, waiters: map[string][]*Client{}}
}

// lookup returns the live entry for key, lazily expiring it.
func (d *DB) lookup(key string) *entry {
	e := d.data[key]
	if e == nil {
		d.srv.stats.misses++
		return nil
	}
	if e.exp != 0 && e.exp <= nowMs() {
		d.remove(e)
		d.srv.stats.expired++
		d.srv.stats.misses++
		return nil
	}
	d.srv.stats.hits++
	return e
}

func (d *DB) add(key string, v any) *entry {
	e := &entry{key: key, val: v, idx: len(d.keys)}
	d.keys = append(d.keys, e)
	d.data[key] = e
	d.signalIfList(key, v)
	return e
}

// set stores v under key, replacing any value and clearing its TTL.
func (d *DB) set(key string, v any) *entry {
	e := d.lookup(key)
	if e == nil {
		return d.add(key, v)
	}
	e.val = v
	e.ver++
	d.setExp(e, 0)
	d.signalIfList(key, v)
	return e
}

// setKeepTTL stores v under key and keeps an existing TTL.
func (d *DB) setKeepTTL(key string, v any) *entry {
	e := d.lookup(key)
	if e == nil {
		return d.add(key, v)
	}
	e.val = v
	e.ver++
	d.signalIfList(key, v)
	return e
}

func (d *DB) remove(e *entry) {
	delete(d.data, e.key)
	if e.exp != 0 {
		delete(d.ttl, e.key)
	}
	last := d.keys[len(d.keys)-1]
	d.keys[e.idx] = last
	last.idx = e.idx
	d.keys[len(d.keys)-1] = nil
	d.keys = d.keys[:len(d.keys)-1]
}

// del removes key if present and live.
func (d *DB) del(key string) bool {
	e := d.lookup(key)
	if e == nil {
		return false
	}
	d.remove(e)
	return true
}

func (d *DB) setExp(e *entry, ms int64) {
	if ms == 0 {
		if e.exp != 0 {
			delete(d.ttl, e.key)
		}
	} else if e.exp == 0 {
		d.ttl[e.key] = e
	}
	e.exp = ms
}

func (d *DB) flush() {
	d.data = map[string]*entry{}
	d.ttl = map[string]*entry{}
	d.keys = nil
}

func (d *DB) randomKey() (string, bool) {
	for tries := 0; len(d.keys) > 0 && tries < 100; tries++ {
		e := d.keys[rand.Intn(len(d.keys))]
		if e.exp != 0 && e.exp <= nowMs() {
			d.remove(e)
			d.srv.stats.expired++
			continue
		}
		return e.key, true
	}
	return "", false
}

// scan examines up to count entries starting at cursor and appends matching
// keys to out. It walks the dense key array from the top down so removals
// (swap-with-last) never cause a key that existed for the whole iteration to
// be skipped. Returns the next cursor (0 = finished).
func (d *DB) scan(cursor uint64, count int, match func(*entry) bool, out *[]string) uint64 {
	n := len(d.keys)
	if n == 0 {
		return 0
	}
	i := n - 1
	if cursor != 0 && int(cursor)-1 < n {
		i = int(cursor) - 1
	}
	now := nowMs()
	for visited := 0; i >= 0 && visited < count; visited, i = visited+1, i-1 {
		if i >= len(d.keys) {
			continue
		}
		e := d.keys[i]
		if e.exp != 0 && e.exp <= now {
			d.remove(e)
			d.srv.stats.expired++
			continue
		}
		if match == nil || match(e) {
			*out = append(*out, e.key)
		}
	}
	if i < 0 {
		return 0
	}
	return uint64(i + 1)
}

// activeExpire samples keys with a TTL and removes expired ones, repeating
// while a large share of the sample was expired.
func (s *Server) activeExpire() {
	now := nowMs()
	for _, d := range s.dbs {
		for round := 0; round < 16 && len(d.ttl) > 0; round++ {
			sampled, expired := 0, 0
			for _, e := range d.ttl {
				if sampled >= 20 {
					break
				}
				sampled++
				if e.exp <= now {
					d.remove(e)
					s.stats.expired++
					expired++
				}
			}
			if expired*4 <= sampled {
				break
			}
		}
	}
}

// typeName reports the Redis type name of a stored value.
func typeName(v any) string {
	switch v.(type) {
	case []byte:
		return "string"
	case *List:
		return "list"
	case *Hash:
		return "hash"
	case *Set:
		return "set"
	case *ZSet:
		return "zset"
	}
	return "none"
}

// cloneValue deep-copies a stored value (for COPY).
func cloneValue(v any) any {
	switch x := v.(type) {
	case []byte:
		return append([]byte(nil), x...)
	case *List:
		n := &List{}
		for _, it := range x.items() {
			n.pushBack(append([]byte(nil), it...))
		}
		return n
	case *Hash:
		return x.clone()
	case *Set:
		return x.clone()
	case *ZSet:
		return x.clone()
	}
	return v
}

// encodingOf reports the OBJECT ENCODING of a value.
func encodingOf(v any, lim *limits) string {
	switch x := v.(type) {
	case *List:
		return x.encoding(lim)
	case *Hash:
		return x.encoding()
	case *Set:
		return x.encoding()
	case *ZSet:
		return x.encoding()
	case []byte:
		if len(x) <= 20 {
			if _, ok := parseInt64(x); ok {
				return "int"
			}
		}
		if len(x) <= 44 {
			return "embstr"
		}
		return "raw"
	}
	return "raw"
}
