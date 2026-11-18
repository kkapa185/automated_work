package main

import (
	"strings"
)

// ---------- utf8 ----------

var utf8Limits = [...]uint32{^uint32(0), 0x80, 0x800, 0x10000, 0x200000, 0x4000000}

// utf8Decode decodes one sequence at s[i:]; returns code and length, or length 0 if invalid.
func utf8Decode(s string, i int, strict bool) (uint32, int) {
	c := uint32(s[i])
	if c < 0x80 {
		return c, 1
	}
	var res uint32
	count := 0
	for ; c&0x40 != 0; c <<= 1 {
		count++
		if i+count >= len(s) {
			return 0, 0
		}
		cc := uint32(s[i+count])
		if cc&0xC0 != 0x80 {
			return 0, 0
		}
		res = (res << 6) | (cc & 0x3F)
	}
	res |= (c & 0x7F) << uint(count*5)
	if count > 5 || res > 0x7FFFFFFF || res < utf8Limits[count] {
		return 0, 0
	}
	if strict && (res > 0x10FFFF || (res >= 0xD800 && res <= 0xDFFF)) {
		return 0, 0
	}
	return res, count + 1
}

func uPosRelat(pos, l int64) int64 {
	if pos >= 0 {
		return pos
	} else if -pos > l {
		return 0
	}
	return l + pos + 1
}

func isCont(s string, i int) bool { return i < len(s) && s[i]&0xC0 == 0x80 }

func openUTF8(th *Thread) {
	u := newTable(0, 8)
	G.setStr("utf8", u)
	loadedTable.setStr("utf8", u)
	u.setStr("charpattern", "[\x00-\x7F\xC2-\xFD][\x80-\xBF]*")
	reg(u, "char", func(th *Thread, args []Value) []Value {
		var b strings.Builder
		for i := range args {
			c := checkInt(th, args, i, "char")
			if uint64(c) > 0x7FFFFFFF {
				argErr(th, i+1, "char", "value out of range")
			}
			b.WriteString(utf8Encode(uint32(c)))
		}
		return []Value{b.String()}
	})
	reg(u, "codepoint", func(th *Thread, args []Value) []Value {
		s := checkStr(th, args, 0, "codepoint")
		l := int64(len(s))
		i := uPosRelat(optInt(th, args, 1, "codepoint", 1), l)
		j := uPosRelat(optInt(th, args, 2, "codepoint", i), l)
		lax := truthy(argOr(args, 3))
		if i < 1 {
			argErr(th, 2, "codepoint", "out of bounds")
		}
		if j > l {
			argErr(th, 3, "codepoint", "out of bounds")
		}
		if i > j {
			return nil
		}
		var out []Value
		p := int(i - 1)
		for p < int(j) {
			c, n := utf8Decode(s, p, !lax)
			if n == 0 {
				th.rtError("invalid UTF-8 code")
			}
			out = append(out, int64(c))
			p += n
		}
		return out
	})
	reg(u, "len", func(th *Thread, args []Value) []Value {
		s := checkStr(th, args, 0, "len")
		l := int64(len(s))
		i := uPosRelat(optInt(th, args, 1, "len", 1), l)
		j := uPosRelat(optInt(th, args, 2, "len", -1), l)
		lax := truthy(argOr(args, 3))
		if !(1 <= i && i <= l+1) {
			argErr(th, 2, "len", "initial position out of bounds")
		}
		if j > l {
			argErr(th, 3, "len", "final position out of bounds")
		}
		n := int64(0)
		p := int(i - 1)
		for p < int(j) {
			_, k := utf8Decode(s, p, !lax)
			if k == 0 {
				return []Value{nil, int64(p + 1)}
			}
			p += k
			n++
		}
		return []Value{n}
	})
	reg(u, "offset", func(th *Thread, args []Value) []Value {
		s := checkStr(th, args, 0, "offset")
		l := int64(len(s))
		n := checkInt(th, args, 1, "offset")
		def := int64(1)
		if n < 0 {
			def = l + 1
		}
		i := optInt(th, args, 2, "offset", def)
		if i < 0 {
			if -i > l {
				i = 0
			} else {
				i = l + i + 1
			}
		}
		if !(1 <= i && i <= l+1) {
			argErr(th, 3, "offset", "position out of bounds")
		}
		p := int(i - 1)
		if n == 0 {
			for p > 0 && isCont(s, p) {
				p--
			}
			return []Value{int64(p + 1)}
		}
		if isCont(s, p) {
			th.rtError("initial position is a continuation byte")
		}
		if n < 0 {
			for n < 0 && p > 0 {
				for {
					p--
					if !(p > 0 && isCont(s, p)) {
						break
					}
				}
				n++
			}
		} else {
			n--
			for n > 0 && p < int(l) {
				for {
					p++
					if !isCont(s, p) {
						break
					}
				}
				n--
			}
		}
		if n == 0 {
			return []Value{int64(p + 1)}
		}
		return []Value{nil}
	})
	reg(u, "codes", func(th *Thread, args []Value) []Value {
		s := checkStr(th, args, 0, "codes")
		lax := truthy(argOr(args, 1))
		iter := &GoFunction{name: "codes_iter", fn: func(th *Thread, a []Value) []Value {
			str := checkStr(th, a, 0, "codes")
			i := int(checkInt(th, a, 1, "codes"))
			// skip continuation bytes of the previous character
			if i > 0 {
				for isCont(str, i) {
					i++
				}
			}
			if i >= len(str) {
				return []Value{nil}
			}
			c, n := utf8Decode(str, i, !lax)
			if n == 0 || isCont(str, i+n) {
				th.rtError("invalid UTF-8 code")
			}
			return []Value{int64(i + 1), int64(c)}
		}}
		return []Value{iter, s, int64(0)}
	})
}

// ---------- coroutine ----------

var mainCo = &Coroutine{status: "running"}

func newCoroutine(fn Value) *Coroutine {
	co := &Coroutine{fn: fn, status: "suspended"}
	co.resumeCh = make(chan []Value)
	co.yieldCh = make(chan coMsg)
	co.th = &Thread{co: co}
	return co
}

func (co *Coroutine) run(args []Value) {
	defer func() {
		r := recover()
		if r == nil {
			return
		}
		if _, ok := r.(*coKill); ok {
			co.yieldCh <- coMsg{done: true}
			return
		}
		le := toLuaError(r)
		if le == nil {
			le = &LuaError{value: "internal error"}
		}
		co.yieldCh <- coMsg{err: le, done: true}
	}()
	res := co.th.call(co.fn, args)
	co.yieldCh <- coMsg{vals: res, done: true}
}

// resume transfers control to co. Returns (values, error).
func (th *Thread) resume(co *Coroutine, args []Value) ([]Value, *LuaError) {
	if co.status != "suspended" {
		msg := "cannot resume non-suspended coroutine"
		if co.status == "dead" {
			msg = "cannot resume dead coroutine"
		}
		return nil, &LuaError{value: msg}
	}
	cur := th.co
	if cur == nil {
		cur = mainCo
	}
	cur.status = "normal"
	co.status = "running"
	co.parent = th
	if !co.started {
		co.started = true
		go co.run(args)
	} else {
		co.resumeCh <- args
	}
	msg := <-co.yieldCh
	cur.status = "running"
	if msg.done {
		co.status = "dead"
		if msg.err != nil {
			co.err = msg.err
			return nil, msg.err
		}
		return msg.vals, nil
	}
	co.status = "suspended"
	return msg.vals, nil
}

func (th *Thread) yield(args []Value) []Value {
	co := th.co
	if co == nil {
		th.rtError("attempt to yield from outside a coroutine")
	}
	co.yieldCh <- coMsg{vals: args}
	r, ok := <-co.resumeCh
	if !ok {
		panic(&coKill{})
	}
	return r
}

func checkCo(th *Thread, args []Value, i int, fname string) *Coroutine {
	if i < len(args) {
		if co, ok := args[i].(*Coroutine); ok {
			return co
		}
	}
	typeErr(th, args, i, fname, "coroutine")
	return nil
}

func openCoroutine(th *Thread) {
	c := newTable(0, 8)
	G.setStr("coroutine", c)
	loadedTable.setStr("coroutine", c)
	reg(c, "create", func(th *Thread, args []Value) []Value {
		switch argOr(args, 0).(type) {
		case *Closure, *GoFunction:
		default:
			typeErr(th, args, 0, "create", "function")
		}
		return []Value{newCoroutine(args[0])}
	})
	reg(c, "resume", func(th *Thread, args []Value) []Value {
		co := checkCo(th, args, 0, "resume")
		res, err := th.resume(co, args[1:])
		if err != nil {
			return []Value{false, err.value}
		}
		return append([]Value{true}, res...)
	})
	reg(c, "yield", func(th *Thread, args []Value) []Value { return th.yield(args) })
	reg(c, "status", func(th *Thread, args []Value) []Value {
		return []Value{checkCo(th, args, 0, "status").status}
	})
	reg(c, "isyieldable", func(th *Thread, args []Value) []Value {
		if len(args) > 0 {
			co := checkCo(th, args, 0, "isyieldable")
			return []Value{co != mainCo}
		}
		return []Value{th.co != nil}
	})
	reg(c, "running", func(th *Thread, args []Value) []Value {
		if th.co == nil {
			return []Value{mainCo, true}
		}
		return []Value{th.co, false}
	})
	reg(c, "wrap", func(th *Thread, args []Value) []Value {
		switch argOr(args, 0).(type) {
		case *Closure, *GoFunction:
		default:
			typeErr(th, args, 0, "wrap", "function")
		}
		co := newCoroutine(args[0])
		return []Value{&GoFunction{name: "wrap", fn: func(th *Thread, a []Value) []Value {
			res, err := th.resume(co, a)
			if err != nil {
				v := err.value
				if s, ok := v.(string); ok {
					v = th.whereLevel(1) + s
				}
				th.throw(v)
			}
			return res
		}}}
	})
	reg(c, "close", func(th *Thread, args []Value) []Value {
		co := checkCo(th, args, 0, "close")
		switch co.status {
		case "suspended":
			if co.started {
				close(co.resumeCh)
				msg := <-co.yieldCh
				co.status = "dead"
				if msg.err != nil {
					return []Value{false, msg.err.value}
				}
			}
			co.status = "dead"
			return []Value{true}
		case "dead":
			if co.err != nil {
				e := co.err
				co.err = nil
				return []Value{false, e.value}
			}
			return []Value{true}
		}
		th.rtError("cannot close a %s coroutine", co.status)
		return nil
	})
}
