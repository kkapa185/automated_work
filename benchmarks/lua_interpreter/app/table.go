package main

import "math"

// Table has an array part (keys 1..len(arr)) and an insertion-ordered hash
// part. Removed hash entries become tombstones (val == nil) so that
// traversal with next() survives assignments of nil.
type Table struct {
	arr  []Value
	keys []Value
	vals []Value
	sidx map[string]int32
	oidx map[Value]int32
	dead int
	meta *Table
}

func newTable(narr, nhash int) *Table {
	t := &Table{}
	if narr > 0 {
		t.arr = make([]Value, 0, narr)
	}
	if nhash > 0 {
		t.keys = make([]Value, 0, nhash)
		t.vals = make([]Value, 0, nhash)
	}
	return t
}

func (t *Table) getInt(i int64) Value {
	if uint64(i-1) < uint64(len(t.arr)) {
		return t.arr[i-1]
	}
	if t.oidx == nil {
		return nil
	}
	if e, ok := t.oidx[i]; ok {
		return t.vals[e]
	}
	return nil
}

func (t *Table) getStr(k string) Value {
	if t.sidx == nil {
		return nil
	}
	if e, ok := t.sidx[k]; ok {
		return t.vals[e]
	}
	return nil
}

func (t *Table) get(k Value) Value {
	switch kk := k.(type) {
	case int64:
		return t.getInt(kk)
	case string:
		return t.getStr(kk)
	case nil:
		return nil
	case float64:
		if i, ok := floatToInt(kk); ok {
			return t.getInt(i)
		}
	}
	if t.oidx == nil {
		return nil
	}
	if e, ok := t.oidx[k]; ok {
		return t.vals[e]
	}
	return nil
}

func (t *Table) setStr(k string, v Value) {
	if t.sidx != nil {
		if e, ok := t.sidx[k]; ok {
			if v == nil && t.vals[e] != nil {
				t.dead++
			} else if v != nil && t.vals[e] == nil {
				t.dead--
			}
			t.vals[e] = v
			return
		}
	}
	if v == nil {
		return
	}
	t.maybeCompact()
	if t.sidx == nil {
		t.sidx = make(map[string]int32)
	}
	t.sidx[k] = int32(len(t.keys))
	t.keys = append(t.keys, k)
	t.vals = append(t.vals, v)
}

func (t *Table) setOther(k Value, v Value) {
	if t.oidx != nil {
		if e, ok := t.oidx[k]; ok {
			if v == nil && t.vals[e] != nil {
				t.dead++
			} else if v != nil && t.vals[e] == nil {
				t.dead--
			}
			t.vals[e] = v
			return
		}
	}
	if v == nil {
		return
	}
	t.maybeCompact()
	if t.oidx == nil {
		t.oidx = make(map[Value]int32)
	}
	t.oidx[k] = int32(len(t.keys))
	t.keys = append(t.keys, k)
	t.vals = append(t.vals, v)
}

func (t *Table) maybeCompact() {
	if t.dead < 16 || t.dead*2 < len(t.keys) {
		return
	}
	nk := make([]Value, 0, len(t.keys)-t.dead+4)
	nv := make([]Value, 0, cap(nk))
	if t.sidx != nil {
		t.sidx = make(map[string]int32, len(t.sidx))
	}
	if t.oidx != nil {
		t.oidx = make(map[Value]int32, len(t.oidx))
	}
	for i, k := range t.keys {
		if t.vals[i] == nil {
			continue
		}
		if s, ok := k.(string); ok {
			t.sidx[s] = int32(len(nk))
		} else {
			t.oidx[k] = int32(len(nk))
		}
		nk = append(nk, k)
		nv = append(nv, t.vals[i])
	}
	t.keys, t.vals, t.dead = nk, nv, 0
}

func (t *Table) setInt(i int64, v Value) {
	n := len(t.arr)
	if uint64(i-1) < uint64(n) {
		t.arr[i-1] = v
		return
	}
	if i == int64(n)+1 {
		if v == nil {
			return
		}
		t.arr = append(t.arr, v)
		if len(t.oidx) > 0 {
			t.migrate()
		}
		return
	}
	t.setOther(i, v)
}

// set assumes k is not nil and not NaN.
func (t *Table) set(k Value, v Value) {
	switch kk := k.(type) {
	case int64:
		t.setInt(kk, v)
	case string:
		t.setStr(kk, v)
	case float64:
		if i, ok := floatToInt(kk); ok {
			t.setInt(i, v)
		} else {
			t.setOther(k, v)
		}
	default:
		t.setOther(k, v)
	}
}

func (t *Table) length() int64 {
	n := len(t.arr)
	if n > 0 && t.arr[n-1] == nil {
		lo, hi := 0, n
		for hi-lo > 1 {
			m := (lo + hi) / 2
			if t.arr[m-1] == nil {
				hi = m
			} else {
				lo = m
			}
		}
		return int64(lo)
	}
	return int64(n)
}

// nextAt scans from cursor position pos; returns key (nil at end), value, new cursor.
func (t *Table) nextAt(pos int) (Value, Value, int) {
	n := len(t.arr)
	for pos < n {
		if v := t.arr[pos]; v != nil {
			return int64(pos + 1), v, pos + 1
		}
		pos++
	}
	for e := pos - n; e < len(t.keys); e++ {
		if v := t.vals[e]; v != nil {
			return t.keys[e], v, n + e + 1
		}
	}
	return nil, nil, 0
}

// posOf finds the cursor position following key k; ok=false if k is invalid.
func (t *Table) posOf(k Value) (int, bool) {
	if k == nil {
		return 0, true
	}
	if f, ok := k.(float64); ok {
		if i, ok := floatToInt(f); ok {
			k = i
		}
	}
	if i, ok := k.(int64); ok && uint64(i-1) < uint64(len(t.arr)) {
		return int(i), true
	}
	var e int32
	var ok bool
	if s, isS := k.(string); isS {
		if t.sidx != nil {
			e, ok = t.sidx[s]
		}
	} else if t.oidx != nil {
		e, ok = t.oidx[k]
	}
	if !ok {
		return 0, false
	}
	return len(t.arr) + int(e) + 1, true
}

func isNaN(v Value) bool {
	f, ok := v.(float64)
	return ok && math.IsNaN(f)
}

// migrate moves keys len(arr)+1, +2... from the hash part to the array part.
func (t *Table) migrate() {
	for {
		nk := int64(len(t.arr)) + 1
		e, ok := t.oidx[nk]
		if !ok {
			return
		}
		val := t.vals[e]
		delete(t.oidx, nk)
		t.keys[e] = nil
		if val == nil {
			return
		}
		t.vals[e] = nil
		t.dead++
		t.arr = append(t.arr, val)
	}
}

// adoptArray installs pos as the array part (used by table constructors).
func (t *Table) adoptArray(pos []Value) {
	t.arr = pos
	if len(t.oidx) > 0 {
		for i := range pos {
			key := int64(i + 1)
			if e, ok := t.oidx[key]; ok {
				delete(t.oidx, key)
				if t.vals[e] != nil {
					t.dead++
				}
				t.keys[e] = nil
				t.vals[e] = nil
			}
		}
		t.migrate()
	}
}
