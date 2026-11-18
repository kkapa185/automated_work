package server

import "math/rand"

const slMaxLevel = 32

type slLevel struct {
	fwd  *slNode
	span int
}

type slNode struct {
	member string
	score  float64
	back   *slNode
	lvl    []slLevel
}

// skiplist is an indexable skip list ordered by (score, member): O(log n)
// insert, delete, rank and select-by-rank thanks to per-link spans.
type skiplist struct {
	head, tail *slNode
	length     int
	level      int
}

func newSkiplist() *skiplist {
	return &skiplist{head: &slNode{lvl: make([]slLevel, slMaxLevel)}, level: 1}
}

func randomLevel() int {
	l := 1
	for l < slMaxLevel && rand.Uint32()&3 == 0 {
		l++
	}
	return l
}

func before(n *slNode, score float64, member string) bool {
	return n.score < score || (n.score == score && n.member < member)
}

func (sl *skiplist) insert(score float64, member string) *slNode {
	var update [slMaxLevel]*slNode
	var rank [slMaxLevel]int
	x := sl.head
	for i := sl.level - 1; i >= 0; i-- {
		if i != sl.level-1 {
			rank[i] = rank[i+1]
		}
		for x.lvl[i].fwd != nil && before(x.lvl[i].fwd, score, member) {
			rank[i] += x.lvl[i].span
			x = x.lvl[i].fwd
		}
		update[i] = x
	}
	lvl := randomLevel()
	if lvl > sl.level {
		for i := sl.level; i < lvl; i++ {
			rank[i] = 0
			update[i] = sl.head
			sl.head.lvl[i].span = sl.length
		}
		sl.level = lvl
	}
	n := &slNode{member: member, score: score, lvl: make([]slLevel, lvl)}
	for i := 0; i < lvl; i++ {
		n.lvl[i].fwd = update[i].lvl[i].fwd
		update[i].lvl[i].fwd = n
		n.lvl[i].span = update[i].lvl[i].span - (rank[0] - rank[i])
		update[i].lvl[i].span = rank[0] - rank[i] + 1
	}
	for i := lvl; i < sl.level; i++ {
		update[i].lvl[i].span++
	}
	if update[0] != sl.head {
		n.back = update[0]
	}
	if n.lvl[0].fwd != nil {
		n.lvl[0].fwd.back = n
	} else {
		sl.tail = n
	}
	sl.length++
	return n
}

func (sl *skiplist) unlink(x *slNode, update *[slMaxLevel]*slNode) {
	for i := 0; i < sl.level; i++ {
		if update[i].lvl[i].fwd == x {
			update[i].lvl[i].span += x.lvl[i].span - 1
			update[i].lvl[i].fwd = x.lvl[i].fwd
		} else {
			update[i].lvl[i].span--
		}
	}
	if x.lvl[0].fwd != nil {
		x.lvl[0].fwd.back = x.back
	} else {
		sl.tail = x.back
	}
	for sl.level > 1 && sl.head.lvl[sl.level-1].fwd == nil {
		sl.level--
	}
	sl.length--
}

func (sl *skiplist) delete(score float64, member string) bool {
	var update [slMaxLevel]*slNode
	x := sl.head
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil && before(x.lvl[i].fwd, score, member) {
			x = x.lvl[i].fwd
		}
		update[i] = x
	}
	x = x.lvl[0].fwd
	if x != nil && x.score == score && x.member == member {
		sl.unlink(x, &update)
		return true
	}
	return false
}

// rank returns the 1-based rank of the element, or 0.
func (sl *skiplist) rank(score float64, member string) int {
	x := sl.head
	r := 0
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil {
			f := x.lvl[i].fwd
			if f.score < score || (f.score == score && f.member <= member) {
				r += x.lvl[i].span
				x = f
			} else {
				break
			}
		}
		if x != sl.head && x.score == score && x.member == member {
			return r
		}
	}
	return 0
}

// byRank returns the node at 1-based rank, or nil.
func (sl *skiplist) byRank(rank int) *slNode {
	if rank < 1 || rank > sl.length {
		return nil
	}
	x := sl.head
	tr := 0
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil && tr+x.lvl[i].span <= rank {
			tr += x.lvl[i].span
			x = x.lvl[i].fwd
		}
		if tr == rank {
			return x
		}
	}
	return nil
}

func (sl *skiplist) first() *slNode { return sl.head.lvl[0].fwd }

// ---- score ranges ----

type scoreRange struct {
	min, max     float64
	minEx, maxEx bool
}

func (r *scoreRange) gteMin(s float64) bool {
	if r.minEx {
		return s > r.min
	}
	return s >= r.min
}

func (r *scoreRange) lteMax(s float64) bool {
	if r.maxEx {
		return s < r.max
	}
	return s <= r.max
}

func (r *scoreRange) empty() bool {
	return r.min > r.max || (r.min == r.max && (r.minEx || r.maxEx))
}

func (sl *skiplist) firstInRange(r *scoreRange) *slNode {
	if r.empty() {
		return nil
	}
	x := sl.head
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil && !r.gteMin(x.lvl[i].fwd.score) {
			x = x.lvl[i].fwd
		}
	}
	x = x.lvl[0].fwd
	if x == nil || !r.lteMax(x.score) {
		return nil
	}
	return x
}

func (sl *skiplist) lastInRange(r *scoreRange) *slNode {
	if r.empty() {
		return nil
	}
	x := sl.head
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil && r.lteMax(x.lvl[i].fwd.score) {
			x = x.lvl[i].fwd
		}
	}
	if x == sl.head || !r.gteMin(x.score) {
		return nil
	}
	return x
}

// ---- lex ranges (meaningful when all scores are equal) ----

type lexRange struct {
	min, max       string
	minInf, maxInf bool // min is "-", max is "+"
	minEx, maxEx   bool
	never          bool // min is "+" or max is "-": matches nothing
}

func (r *lexRange) gteMin(m string) bool {
	if r.minInf {
		return true
	}
	if r.minEx {
		return m > r.min
	}
	return m >= r.min
}

func (r *lexRange) lteMax(m string) bool {
	if r.maxInf {
		return true
	}
	if r.maxEx {
		return m < r.max
	}
	return m <= r.max
}

func (r *lexRange) empty() bool {
	if r.never {
		return true
	}
	if r.minInf || r.maxInf {
		return false
	}
	return r.min > r.max || (r.min == r.max && (r.minEx || r.maxEx))
}

func (sl *skiplist) firstInLex(r *lexRange) *slNode {
	if r.empty() {
		return nil
	}
	x := sl.head
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil && !r.gteMin(x.lvl[i].fwd.member) {
			x = x.lvl[i].fwd
		}
	}
	x = x.lvl[0].fwd
	if x == nil || !r.lteMax(x.member) {
		return nil
	}
	return x
}

func (sl *skiplist) lastInLex(r *lexRange) *slNode {
	if r.empty() {
		return nil
	}
	x := sl.head
	for i := sl.level - 1; i >= 0; i-- {
		for x.lvl[i].fwd != nil && r.lteMax(x.lvl[i].fwd.member) {
			x = x.lvl[i].fwd
		}
	}
	if x == sl.head || !r.gteMin(x.member) {
		return nil
	}
	return x
}

// ---------------- ZSet ----------------

// ZSet is a sorted set: member -> score map plus the ordered skiplist.
type ZSet struct {
	dict map[string]float64
	sl   *skiplist
	big  bool // sticky skiplist encoding
	ver  uint64
}

func newZSet() *ZSet { return &ZSet{dict: map[string]float64{}, sl: newSkiplist()} }

func (z *ZSet) Len() int { return len(z.dict) }

func (z *ZSet) score(m string) (float64, bool) { s, ok := z.dict[m]; return s, ok }

// put inserts or re-scores a member.
func (z *ZSet) put(m string, score float64, lim *limits) {
	if old, ok := z.dict[m]; ok {
		if old == score {
			return
		}
		z.sl.delete(old, m)
	}
	z.ver++
	z.dict[m] = score
	z.sl.insert(score, m)
	if !z.big && (len(z.dict) > lim.zsetEntries || len(m) > lim.zsetValue) {
		z.big = true
	}
}

func (z *ZSet) remove(m string) bool {
	s, ok := z.dict[m]
	if !ok {
		return false
	}
	z.ver++
	z.sl.delete(s, m)
	delete(z.dict, m)
	return true
}

func (z *ZSet) clone() *ZSet {
	n := newZSet()
	n.big = z.big
	for x := z.sl.first(); x != nil; x = x.lvl[0].fwd {
		n.dict[x.member] = x.score
		n.sl.insert(x.score, x.member)
	}
	return n
}

func (z *ZSet) encoding() string {
	if z.big {
		return "skiplist"
	}
	return "listpack"
}
