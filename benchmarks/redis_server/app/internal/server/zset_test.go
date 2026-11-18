package server

import (
	"math/rand"
	"sort"
	"testing"
)

type pair struct {
	m string
	s float64
}

func naiveSorted(ref map[string]float64) []pair {
	out := make([]pair, 0, len(ref))
	for m, s := range ref {
		out = append(out, pair{m, s})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].s != out[j].s {
			return out[i].s < out[j].s
		}
		return out[i].m < out[j].m
	})
	return out
}

// Differential test of the skiplist against a naive sorted slice.
func TestSkiplistRandomised(t *testing.T) {
	lim := &limits{zsetEntries: 128, zsetValue: 64}
	z := newZSet()
	ref := map[string]float64{}
	rng := rand.New(rand.NewSource(42))
	names := make([]string, 300)
	for i := range names {
		names[i] = string(rune('a'+i%26)) + string(rune('A'+i/26))
	}
	for step := 0; step < 20000; step++ {
		m := names[rng.Intn(len(names))]
		switch rng.Intn(3) {
		case 0, 1:
			s := float64(rng.Intn(40)) // many ties
			z.put(m, s, lim)
			ref[m] = s
		case 2:
			if z.remove(m) != (func() bool { _, ok := ref[m]; return ok })() {
				t.Fatal("remove result mismatch")
			}
			delete(ref, m)
		}
		if step%250 != 0 {
			continue
		}
		want := naiveSorted(ref)
		if z.sl.length != len(want) || z.Len() != len(want) {
			t.Fatalf("length %d/%d want %d", z.sl.length, z.Len(), len(want))
		}
		i := 0
		for n := z.sl.first(); n != nil; n = n.lvl[0].fwd {
			if n.member != want[i].m || n.score != want[i].s {
				t.Fatalf("order mismatch at %d", i)
			}
			if r := z.sl.rank(n.score, n.member); r != i+1 {
				t.Fatalf("rank(%s)=%d want %d", n.member, r, i+1)
			}
			if b := z.sl.byRank(i + 1); b != n {
				t.Fatalf("byRank(%d) wrong", i+1)
			}
			i++
		}
		// backward links
		for n, j := z.sl.tail, len(want)-1; n != nil; n, j = n.back, j-1 {
			if n.member != want[j].m {
				t.Fatal("back link mismatch")
			}
		}
		// score range counting
		r := scoreRange{min: 10, max: 20, minEx: true}
		cnt := 0
		for _, p := range want {
			if p.s > 10 && p.s <= 20 {
				cnt++
			}
		}
		if f := z.sl.firstInRange(&r); f == nil {
			if cnt != 0 {
				t.Fatal("range missed")
			}
		} else {
			l := z.sl.lastInRange(&r)
			if got := z.sl.rank(l.score, l.member) - z.sl.rank(f.score, f.member) + 1; got != cnt {
				t.Fatalf("range count %d want %d", got, cnt)
			}
		}
	}
}

func TestLexRangeParse(t *testing.T) {
	r, ok := parseLexRange([]byte("[a"), []byte("(c"))
	if !ok || r.min != "a" || r.max != "c" || r.minEx || !r.maxEx {
		t.Fatalf("%+v", r)
	}
	r, ok = parseLexRange([]byte("-"), []byte("+"))
	if !ok || !r.minInf || !r.maxInf || r.empty() {
		t.Fatal("inf")
	}
	if r, _ = parseLexRange([]byte("+"), []byte("[a")); !r.empty() {
		t.Fatal("+ as min matches nothing")
	}
	for _, bad := range [][2]string{{"a", "[b"}, {"[a", ""}, {"--", "+"}} {
		if _, ok := parseLexRange([]byte(bad[0]), []byte(bad[1])); ok {
			t.Errorf("%v should be invalid", bad)
		}
	}
}

func TestScoreRangeParse(t *testing.T) {
	r, ok := parseScoreRange([]byte("(1.5"), []byte("+inf"))
	if !ok || r.min != 1.5 || !r.minEx || r.maxEx || r.max <= 1e300 {
		t.Fatalf("%+v", r)
	}
	if _, ok := parseScoreRange([]byte("abc"), []byte("1")); ok {
		t.Fatal("invalid accepted")
	}
	if _, ok := parseScoreRange([]byte("(("), []byte("1")); ok {
		t.Fatal("invalid accepted")
	}
}
