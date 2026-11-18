package main

import (
	"math"
	"sort"
	"strings"
	"time"
)

// ---------- table ----------

func tlen(th *Thread, t *Table) int64 {
	if t.meta == nil {
		return t.length()
	}
	v := th.length(t, "")
	n, ok := v.(int64)
	if !ok {
		if f, ok2 := v.(float64); ok2 {
			if i, ok3 := floatToInt(f); ok3 {
				return i
			}
		}
		th.rtError("object length is not an integer")
	}
	return n
}

func tget(th *Thread, t *Table, i int64) Value {
	if t.meta == nil {
		return t.getInt(i)
	}
	return th.index(t, i, "")
}

func tset(th *Thread, t *Table, i int64, v Value) {
	if t.meta == nil {
		t.setInt(i, v)
		return
	}
	th.setIndex(t, i, v, "")
}

// checkTab accepts tables (and values with suitable metamethods are not needed).
func checkTab(th *Thread, args []Value, i int, fname string) *Table {
	return checkTable(th, args, i, fname)
}

func openTable(th *Thread) {
	t := newTable(0, 8)
	G.setStr("table", t)
	loadedTable.setStr("table", t)

	reg(t, "insert", func(th *Thread, args []Value) []Value {
		tb := checkTab(th, args, 0, "insert")
		e := tlen(th, tb) + 1
		switch len(args) {
		case 2:
			tset(th, tb, e, args[1])
		case 3:
			pos := checkInt(th, args, 1, "insert")
			if uint64(pos)-1 >= uint64(e) {
				argErr(th, 2, "insert", "position out of bounds")
			}
			for i := e; i > pos; i-- {
				tset(th, tb, i, tget(th, tb, i-1))
			}
			tset(th, tb, pos, args[2])
		default:
			th.rtError("wrong number of arguments to 'insert'")
		}
		return nil
	})
	reg(t, "remove", func(th *Thread, args []Value) []Value {
		tb := checkTab(th, args, 0, "remove")
		size := tlen(th, tb)
		pos := optInt(th, args, 1, "remove", size)
		if pos != size && uint64(pos)-1 > uint64(size) {
			argErr(th, 2, "remove", "position out of bounds")
		}
		v := tget(th, tb, pos)
		for ; pos < size; pos++ {
			tset(th, tb, pos, tget(th, tb, pos+1))
		}
		tset(th, tb, pos, nil)
		return []Value{v}
	})
	reg(t, "concat", func(th *Thread, args []Value) []Value {
		tb := checkTab(th, args, 0, "concat")
		sep := optStr(th, args, 1, "concat", "")
		i := optInt(th, args, 2, "concat", 1)
		var j int64
		if len(args) > 3 && args[3] != nil {
			j = checkInt(th, args, 3, "concat")
		} else {
			j = tlen(th, tb)
		}
		var b strings.Builder
		for k := i; k <= j; k++ {
			v := tget(th, tb, k)
			switch x := v.(type) {
			case string:
				b.WriteString(x)
			case int64, float64:
				b.WriteString(numToString(x))
			default:
				th.rtError("invalid value (at index %d) in table for 'concat'", k)
			}
			if k < j {
				b.WriteString(sep)
			}
			if k == math.MaxInt64 {
				break
			}
		}
		return []Value{b.String()}
	})
	unpack := func(th *Thread, args []Value) []Value {
		i := optInt(th, args, 1, "unpack", 1)
		var j int64
		if len(args) > 2 && args[2] != nil {
			j = checkInt(th, args, 2, "unpack")
		} else if tb, ok := argOr(args, 0).(*Table); ok {
			j = tlen(th, tb)
		} else {
			j = th.length(argOr(args, 0), "").(int64)
		}
		if i > j {
			return nil
		}
		if uint64(j)-uint64(i) >= 1<<24 {
			th.rtError("too many results to unpack")
		}
		out := make([]Value, 0, j-i+1)
		src := argOr(args, 0)
		tb, isT := src.(*Table)
		for k := i; ; k++ {
			if isT {
				out = append(out, tget(th, tb, k))
			} else {
				out = append(out, th.index(src, k, ""))
			}
			if k == j {
				break
			}
		}
		return out
	}
	reg(t, "unpack", unpack)
	reg(t, "pack", func(th *Thread, args []Value) []Value {
		tb := newTable(len(args), 1)
		tb.adoptArray(append([]Value(nil), args...))
		tb.setStr("n", int64(len(args)))
		return []Value{tb}
	})
	reg(t, "move", func(th *Thread, args []Value) []Value {
		a1 := checkTab(th, args, 0, "move")
		f := checkInt(th, args, 1, "move")
		e := checkInt(th, args, 2, "move")
		tpos := checkInt(th, args, 3, "move")
		a2 := a1
		if len(args) > 4 && args[4] != nil {
			a2 = checkTab(th, args, 4, "move")
		}
		if e >= f {
			if !(f > 0 || e < math.MaxInt64+f) {
				argErr(th, 3, "move", "too many elements to move")
			}
			n := e - f + 1
			if tpos > math.MaxInt64-n+1 {
				argErr(th, 4, "move", "destination wrap around")
			}
			if tpos > e || tpos <= f || a1 != a2 {
				for i := int64(0); i < n; i++ {
					tset(th, a2, tpos+i, tget(th, a1, f+i))
				}
			} else {
				for i := n - 1; i >= 0; i-- {
					tset(th, a2, tpos+i, tget(th, a1, f+i))
				}
			}
		}
		return []Value{a2}
	})
	reg(t, "sort", func(th *Thread, args []Value) []Value {
		tb := checkTab(th, args, 0, "sort")
		n := tlen(th, tb)
		if n > 1<<30 {
			argErr(th, 1, "sort", "array too big")
		}
		comp := argOr(args, 1)
		if comp != nil {
			switch comp.(type) {
			case *Closure, *GoFunction:
			default:
				typeErr(th, args, 1, "sort", "function")
			}
		}
		vals := make([]Value, n)
		for i := int64(0); i < n; i++ {
			vals[i] = tget(th, tb, i+1)
		}
		var less func(a, b Value) bool
		if comp == nil {
			less = func(a, b Value) bool {
				if x, ok := a.(int64); ok {
					if y, ok := b.(int64); ok {
						return x < y
					}
				}
				return th.lessThan(a, b)
			}
		} else {
			less = func(a, b Value) bool {
				return truthy(first(th.call(comp, []Value{a, b})))
			}
		}
		sort.Sort(&luaSorter{vals, less})
		for i := int64(0); i < n; i++ {
			tset(th, tb, i+1, vals[i])
		}
		return nil
	})
}

type luaSorter struct {
	v    []Value
	less func(a, b Value) bool
}

func (s *luaSorter) Len() int           { return len(s.v) }
func (s *luaSorter) Less(i, j int) bool { return s.less(s.v[i], s.v[j]) }
func (s *luaSorter) Swap(i, j int)      { s.v[i], s.v[j] = s.v[j], s.v[i] }

// ---------- math ----------

type xoshiro struct{ s [4]uint64 }

func rotl(x uint64, n uint) uint64 { return (x << n) | (x >> (64 - n)) }

var rng xoshiro

func (r *xoshiro) nextRand() uint64 {
	s := &r.s
	res := rotl(s[1]*5, 7) * 9
	t := s[1] << 17
	s[2] ^= s[0]
	s[3] ^= s[1]
	s[1] ^= s[2]
	s[0] ^= s[3]
	s[2] ^= t
	s[3] = rotl(s[3], 45)
	return res
}

func (r *xoshiro) seed(n1, n2 uint64) {
	r.s = [4]uint64{n1, 0xff, n2, 0}
	for i := 0; i < 16; i++ {
		r.nextRand()
	}
}

func projectRand(ran, n uint64) uint64 {
	if n&(n+1) == 0 {
		return ran & n
	}
	lim := n
	lim |= lim >> 1
	lim |= lim >> 2
	lim |= lim >> 4
	lim |= lim >> 8
	lim |= lim >> 16
	lim |= lim >> 32
	for {
		ran &= lim
		if ran <= n {
			return ran
		}
		ran = rng.nextRand()
	}
}

func mathFloor(f float64) Value {
	fl := math.Floor(f)
	if i, ok := floatToInt(fl); ok {
		return i
	}
	return fl
}

func openMath(th *Thread) {
	m := newTable(0, 32)
	G.setStr("math", m)
	loadedTable.setStr("math", m)
	m.setStr("pi", math.Pi)
	m.setStr("huge", math.Inf(1))
	m.setStr("maxinteger", int64(math.MaxInt64))
	m.setStr("mininteger", int64(math.MinInt64))
	now := time.Now().UnixNano()
	rng.seed(uint64(now), uint64(0x5deece66d))

	f1 := func(name string, fn func(float64) float64) {
		reg(m, name, func(th *Thread, args []Value) []Value {
			return []Value{fn(checkNum(th, args, 0, name))}
		})
	}
	f1("sin", math.Sin)
	f1("cos", math.Cos)
	f1("tan", math.Tan)
	f1("asin", math.Asin)
	f1("acos", math.Acos)
	f1("exp", math.Exp)
	f1("sqrt", math.Sqrt)
	reg(m, "atan", func(th *Thread, args []Value) []Value {
		y := checkNum(th, args, 0, "atan")
		x := 1.0
		if len(args) > 1 && args[1] != nil {
			x = checkNum(th, args, 1, "atan")
		}
		return []Value{math.Atan2(y, x)}
	})
	reg(m, "log", func(th *Thread, args []Value) []Value {
		x := checkNum(th, args, 0, "log")
		if len(args) < 2 || args[1] == nil {
			return []Value{math.Log(x)}
		}
		b := checkNum(th, args, 1, "log")
		switch b {
		case 2:
			return []Value{math.Log2(x)}
		case 10:
			return []Value{math.Log10(x)}
		}
		return []Value{math.Log(x) / math.Log(b)}
	})
	reg(m, "abs", func(th *Thread, args []Value) []Value {
		if n, ok := argOr(args, 0).(int64); ok {
			if n < 0 {
				n = -n
			}
			return []Value{n}
		}
		return []Value{math.Abs(checkNum(th, args, 0, "abs"))}
	})
	reg(m, "floor", func(th *Thread, args []Value) []Value {
		if n, ok := argOr(args, 0).(int64); ok {
			return []Value{n}
		}
		return []Value{mathFloor(checkNum(th, args, 0, "floor"))}
	})
	reg(m, "ceil", func(th *Thread, args []Value) []Value {
		if n, ok := argOr(args, 0).(int64); ok {
			return []Value{n}
		}
		c := math.Ceil(checkNum(th, args, 0, "ceil"))
		if i, ok := floatToInt(c); ok {
			return []Value{i}
		}
		return []Value{c}
	})
	reg(m, "fmod", func(th *Thread, args []Value) []Value {
		a, aok := argOr(args, 0).(int64)
		b, bok := argOr(args, 1).(int64)
		if aok && bok {
			if b == 0 {
				argErr(th, 2, "fmod", "zero")
			}
			if b == -1 {
				return []Value{int64(0)}
			}
			return []Value{a % b}
		}
		return []Value{math.Mod(checkNum(th, args, 0, "fmod"), checkNum(th, args, 1, "fmod"))}
	})
	reg(m, "modf", func(th *Thread, args []Value) []Value {
		f := checkNum(th, args, 0, "modf")
		if math.IsInf(f, 0) {
			return []Value{f, 0.0}
		}
		ip := math.Trunc(f)
		fp := f - ip
		if math.IsNaN(f) {
			fp = f
		}
		return []Value{ip, fp}
	})
	reg(m, "tointeger", func(th *Thread, args []Value) []Value {
		checkAny(th, args, 0, "tointeger")
		switch v := args[0].(type) {
		case int64:
			return []Value{v}
		case float64:
			if i, ok := floatToInt(v); ok {
				return []Value{i}
			}
		case string:
			if n, ok := str2number(v); ok {
				if i, ok := toInteger(n); ok {
					return []Value{i}
				}
			}
		}
		return []Value{nil}
	})
	reg(m, "type", func(th *Thread, args []Value) []Value {
		switch checkAny(th, args, 0, "type").(type) {
		case int64:
			return []Value{"integer"}
		case float64:
			return []Value{"float"}
		}
		return []Value{nil}
	})
	reg(m, "ult", func(th *Thread, args []Value) []Value {
		return []Value{uint64(checkInt(th, args, 0, "ult")) < uint64(checkInt(th, args, 1, "ult"))}
	})
	minmax := func(name string, wantLess bool) {
		reg(m, name, func(th *Thread, args []Value) []Value {
			checkNum(th, args, 0, name)
			best := args[0]
			if s, ok := best.(string); ok {
				best, _ = str2number(s)
			}
			for i := 1; i < len(args); i++ {
				checkNum(th, args, i, name)
				v := args[i]
				if s, ok := v.(string); ok {
					v, _ = str2number(s)
				}
				if wantLess {
					if th.lessThan(v, best) {
						best = v
					}
				} else if th.lessThan(best, v) {
					best = v
				}
			}
			return []Value{best}
		})
	}
	minmax("min", true)
	minmax("max", false)
	reg(m, "random", func(th *Thread, args []Value) []Value {
		rv := rng.nextRand()
		var low, up int64
		switch len(args) {
		case 0:
			return []Value{float64(rv>>11) * (0.5 / (1 << 52))}
		case 1:
			low = 1
			up = checkInt(th, args, 0, "random")
			if up == 0 {
				return []Value{int64(rv)}
			}
		case 2:
			low = checkInt(th, args, 0, "random")
			up = checkInt(th, args, 1, "random")
		default:
			th.rtError("wrong number of arguments")
		}
		if low > up {
			argErr(th, len(args), "random", "interval is empty")
		}
		return []Value{int64(projectRand(rv, uint64(up)-uint64(low)) + uint64(low))}
	})
	reg(m, "randomseed", func(th *Thread, args []Value) []Value {
		var n1, n2 uint64
		if len(args) == 0 {
			n1 = uint64(time.Now().UnixNano())
			n2 = uint64(time.Now().Unix()) * 2654435761
		} else {
			if i, ok := args[0].(int64); ok {
				n1 = uint64(i)
			} else {
				f := checkNum(th, args, 0, "randomseed")
				if i, ok := floatToInt(f); ok {
					n1 = uint64(i)
				} else {
					n1 = math.Float64bits(f)
				}
			}
			n2 = uint64(optInt(th, args, 1, "randomseed", 0))
		}
		rng.seed(n1, n2)
		return []Value{int64(n1), int64(n2)}
	})
}
