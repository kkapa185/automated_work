package server

import "strconv"

// limits mirrors the encoding-threshold configuration (OBJECT ENCODING only).
type limits struct {
	hashEntries, hashValue          int
	setIntset, setEntries, setValue int
	zsetEntries, zsetValue          int
	listBytes                       int
}

func (s *Server) refreshLimits() {
	get := func(name string, def int) int {
		if v, err := strconv.Atoi(s.cfg[name]); err == nil {
			return v
		}
		return def
	}
	s.lim = limits{
		hashEntries: get("hash-max-listpack-entries", 128), hashValue: get("hash-max-listpack-value", 64),
		setIntset: get("set-max-intset-entries", 512), setEntries: get("set-max-listpack-entries", 128),
		setValue: get("set-max-listpack-value", 64), zsetEntries: get("zset-max-listpack-entries", 128),
		zsetValue: get("zset-max-listpack-value", 64), listBytes: 8192,
	}
	if sz := get("list-max-listpack-size", -2); sz > 0 {
		s.lim.listBytes = sz * 64
	}
}

// ---------------- List: a deque with O(1) push/pop at both ends ----------------

type List struct {
	buf  [][]byte
	head int
	ver  uint64 // bumped on every mutation (WATCH)
}

func (l *List) Len() int        { return len(l.buf) - l.head }
func (l *List) items() [][]byte { return l.buf[l.head:] }

func (l *List) pushBack(v []byte) { l.ver++; l.buf = append(l.buf, v) }

func (l *List) pushFront(v []byte) {
	l.ver++
	if l.head == 0 {
		n := len(l.buf)
		gap := max(n, 8)
		nb := make([][]byte, gap+n, gap+n+n/2+8)
		copy(nb[gap:], l.buf)
		l.buf, l.head = nb, gap
	}
	l.head--
	l.buf[l.head] = v
}

func (l *List) popFront() []byte {
	l.ver++
	v := l.buf[l.head]
	l.buf[l.head] = nil
	l.head++
	if l.head == len(l.buf) {
		l.buf, l.head = l.buf[:0], 0
	} else if l.head > 1024 && l.head*2 > len(l.buf) {
		n := copy(l.buf, l.buf[l.head:])
		for i := n; i < len(l.buf); i++ {
			l.buf[i] = nil
		}
		l.buf, l.head = l.buf[:n], 0
	}
	return v
}

func (l *List) popBack() []byte {
	l.ver++
	n := len(l.buf) - 1
	v := l.buf[n]
	l.buf[n] = nil
	l.buf = l.buf[:n]
	if l.head == len(l.buf) {
		l.buf, l.head = l.buf[:0], 0
	}
	return v
}

// replace swaps in a brand-new element slice.
func (l *List) replace(items [][]byte) { l.ver++; l.buf, l.head = items, 0 }

func (l *List) encoding(lim *limits) string {
	size := 0
	for _, it := range l.items() {
		size += len(it) + 2
	}
	if size <= lim.listBytes {
		return "listpack"
	}
	return "quicklist"
}

// ---------------- Hash: insertion-ordered map with tombstones ----------------

type hitem struct {
	f    string
	v    []byte
	live bool
}

type Hash struct {
	m     map[string]int
	items []hitem
	dead  int
	big   bool // sticky: once converted to hashtable it stays so
	ver   uint64
}

func newHash() *Hash { return &Hash{m: map[string]int{}} }

func (h *Hash) Len() int { return len(h.m) }

func (h *Hash) get(f string) ([]byte, bool) {
	i, ok := h.m[f]
	if !ok {
		return nil, false
	}
	return h.items[i].v, true
}

// set stores f=v and reports whether f is new.
func (h *Hash) set(f string, v []byte, lim *limits) bool {
	h.ver++
	i, ok := h.m[f]
	if ok {
		h.items[i].v = v
	} else {
		h.m[f] = len(h.items)
		h.items = append(h.items, hitem{f, v, true})
	}
	if !h.big && (len(h.m) > lim.hashEntries || len(f) > lim.hashValue || len(v) > lim.hashValue) {
		h.big = true
	}
	return !ok
}

func (h *Hash) del(f string) bool {
	i, ok := h.m[f]
	if !ok {
		return false
	}
	h.ver++
	delete(h.m, f)
	h.items[i] = hitem{}
	h.dead++
	if h.dead > 32 && h.dead*2 > len(h.items) {
		out := make([]hitem, 0, len(h.m))
		for _, it := range h.items {
			if it.live {
				h.m[it.f] = len(out)
				out = append(out, it)
			}
		}
		h.items, h.dead = out, 0
	}
	return true
}

// each calls fn for live fields in insertion order.
func (h *Hash) each(fn func(f string, v []byte)) {
	for _, it := range h.items {
		if it.live {
			fn(it.f, it.v)
		}
	}
}

func (h *Hash) fields() []hitem {
	out := make([]hitem, 0, len(h.m))
	for _, it := range h.items {
		if it.live {
			out = append(out, it)
		}
	}
	return out
}

func (h *Hash) clone() *Hash {
	n := newHash()
	n.big = h.big
	h.each(func(f string, v []byte) {
		n.m[f] = len(n.items)
		n.items = append(n.items, hitem{f, append([]byte(nil), v...), true})
	})
	return n
}

func (h *Hash) encoding() string {
	if h.big {
		return "hashtable"
	}
	return "listpack"
}

// ---------------- Set: dense slice + index (O(1) add/remove/random) ----------------

const (
	setIntset = iota
	setListpack
	setHashtable
)

type Set struct {
	m     map[string]int
	items []string
	enc   int
	ver   uint64
}

func newSet() *Set { return &Set{m: map[string]int{}, enc: setIntset} }

func (s *Set) Len() int { return len(s.items) }

func (s *Set) has(m string) bool { _, ok := s.m[m]; return ok }

func (s *Set) add(m string, lim *limits) bool {
	if _, ok := s.m[m]; ok {
		return false
	}
	s.ver++
	s.m[m] = len(s.items)
	s.items = append(s.items, m)
	n := len(s.items)
	switch s.enc {
	case setIntset:
		if _, isInt := parseInt64([]byte(m)); isInt && n <= lim.setIntset {
			break
		}
		fallthrough
	case setListpack:
		if n > lim.setEntries || len(m) > lim.setValue {
			s.enc = setHashtable
		} else {
			s.enc = setListpack
		}
	}
	return true
}

func (s *Set) remove(m string) bool {
	i, ok := s.m[m]
	if !ok {
		return false
	}
	s.ver++
	last := s.items[len(s.items)-1]
	s.items[i] = last
	s.m[last] = i
	s.items = s.items[:len(s.items)-1]
	delete(s.m, m)
	return true
}

func (s *Set) clone() *Set {
	n := &Set{m: make(map[string]int, len(s.m)), items: append([]string(nil), s.items...), enc: s.enc}
	for k, v := range s.m {
		n.m[k] = v
	}
	return n
}

func (s *Set) encoding() string {
	return [...]string{"intset", "listpack", "hashtable"}[s.enc]
}
