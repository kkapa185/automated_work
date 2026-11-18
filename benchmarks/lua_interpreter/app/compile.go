package main

import (
	"fmt"
	"math"
)

type exprFn func(*Frame) Value
type multiFn func(*Frame) []Value
type stmtFn func(*Frame) ctl
type condFn func(*Frame) bool

type compiler struct {
	chunk string
}

var nextFn *GoFunction
var ipairsIter *GoFunction

func compileFunction(fb *FuncBody, chunk string) *Proto {
	c := &compiler{chunk: chunk}
	return c.function(fb)
}

func (c *compiler) function(fb *FuncBody) *Proto {
	p := &Proto{name: fb.name, chunk: c.chunk, line: fb.line, lastLine: fb.lastLine, nparams: len(fb.params),
		isVararg: fb.isVararg, nslots: fb.nslots, upvals: fb.upvals, isMain: fb.isMain}
	p.paramCapt = make([]bool, len(fb.params))
	for i, v := range fb.params {
		if v.captured {
			p.paramCapt[i] = true
			p.anyCapt = true
		}
	}
	p.body = c.block(fb.body)
	return p
}

func describe(e Expr) string {
	switch x := e.(type) {
	case *ELocal:
		return fmt.Sprintf(" (local '%s')", x.info.name)
	case *EUpval:
		return fmt.Sprintf(" (upvalue '%s')", x.name)
	case *EIndex:
		if k, ok := x.key.(*EStr); ok {
			if x.global {
				return fmt.Sprintf(" (global '%s')", k.s)
			}
			return fmt.Sprintf(" (field '%s')", k.s)
		}
	case *EMethod:
		return fmt.Sprintf(" (method '%s')", x.name)
	case *EStr:
		return fmt.Sprintf(" (constant '%s')", x.s)
	}
	return ""
}

func isMulti(e Expr) bool {
	switch e.(type) {
	case *ECall, *EMethod, *EVararg:
		return true
	}
	return false
}

// ---------- blocks & statements ----------

func (c *compiler) block(b *Block) stmtFn { return c.stmts(b.stmts) }

func (c *compiler) stmts(list []Stmt) stmtFn {
	var fns []stmtFn
	var labels map[*Label]int
	for i, s := range list {
		if l, ok := s.(*SLabel); ok {
			if labels == nil {
				labels = map[*Label]int{}
			}
			labels[l.label] = len(fns)
			continue
		}
		if sl, ok := s.(*SLocal); ok {
			var cv *VarInfo
			for _, v := range sl.vars {
				if v.attrib == attrClose {
					cv = v
				}
			}
			if cv != nil {
				decl := c.localStmt(sl)
				rest := c.stmts(list[i+1:])
				fns = append(fns, c.closeStmt(decl, cv, rest, sl.line))
				break
			}
		}
		fns = append(fns, c.stmt(s))
	}
	n := len(fns)
	if labels == nil {
		switch n {
		case 0:
			return func(*Frame) ctl { return cNone }
		case 1:
			return fns[0]
		case 2:
			a, b := fns[0], fns[1]
			return func(fr *Frame) ctl {
				if r := a(fr); r != cNone {
					return r
				}
				return b(fr)
			}
		case 3:
			a, b, d := fns[0], fns[1], fns[2]
			return func(fr *Frame) ctl {
				if r := a(fr); r != cNone {
					return r
				}
				if r := b(fr); r != cNone {
					return r
				}
				return d(fr)
			}
		}
		return func(fr *Frame) ctl {
			for _, f := range fns {
				if r := f(fr); r != cNone {
					return r
				}
			}
			return cNone
		}
	}
	return func(fr *Frame) ctl {
		for i := 0; i < n; i++ {
			if r := fns[i](fr); r != cNone {
				if r == cGoto {
					if idx, ok := labels[fr.gotoLabel]; ok {
						i = idx - 1
						continue
					}
				}
				return r
			}
		}
		return cNone
	}
}

func (c *compiler) readVar(v *VarInfo) exprFn {
	s := v.slot
	if v.captured {
		return func(fr *Frame) Value { return fr.slots[s].(*Cell).v }
	}
	return func(fr *Frame) Value { return fr.slots[s] }
}

func (c *compiler) closeStmt(decl stmtFn, cv *VarInfo, rest stmtFn, line int) stmtFn {
	read := c.readVar(cv)
	name := cv.name
	return func(fr *Frame) ctl {
		decl(fr)
		v := read(fr)
		if v == nil || v == false {
			return rest(fr)
		}
		th := fr.th
		if th.metaOf(v, "__close") == nil {
			fr.line = line
			th.rtError("variable '%s' got a non-closable value", name)
		}
		return th.withClose(fr, v, rest)
	}
}

func (th *Thread) withClose(fr *Frame, v Value, body stmtFn) (c ctl) {
	savedDepth := th.depth
	func() {
		defer func() {
			if r := recover(); r != nil {
				var errv Value
				if _, ok := r.(*coKill); ok {
					errv = nil
				} else if le := toLuaError(r); le != nil {
					errv = le.value
				} else {
					panic(r)
				}
				th.top, th.depth = fr, savedDepth
				if h := th.metaOf(v, "__close"); h != nil {
					th.callValue(h, []Value{v, errv})
				}
				panic(r)
			}
		}()
		c = body(fr)
	}()
	if h := th.metaOf(v, "__close"); h != nil {
		th.callValue(h, []Value{v, nil})
	}
	return c
}

func (c *compiler) setVarFn(v *VarInfo) func(fr *Frame, val Value) {
	s := v.slot
	if v.captured {
		return func(fr *Frame, val Value) { fr.slots[s] = &Cell{val} }
	}
	return func(fr *Frame, val Value) { fr.slots[s] = val }
}

func (c *compiler) localStmt(s *SLocal) stmtFn {
	nv := len(s.vars)
	if nv == 1 && len(s.exprs) == 1 && !isMulti(s.exprs[0]) {
		e := c.expr(s.exprs[0])
		v := s.vars[0]
		sl := v.slot
		if v.captured {
			return func(fr *Frame) ctl { fr.slots[sl] = &Cell{e(fr)}; return cNone }
		}
		return func(fr *Frame) ctl { fr.slots[sl] = e(fr); return cNone }
	}
	if len(s.exprs) == 0 {
		sets := make([]func(*Frame, Value), nv)
		for i, v := range s.vars {
			sets[i] = c.setVarFn(v)
		}
		return func(fr *Frame) ctl {
			for _, f := range sets {
				f(fr, nil)
			}
			return cNone
		}
	}
	list := c.argList(s.exprs, false)
	sets := make([]func(*Frame, Value), nv)
	for i, v := range s.vars {
		sets[i] = c.setVarFn(v)
	}
	return func(fr *Frame) ctl {
		vals := list(fr, nil)
		for i, f := range sets {
			var v Value
			if i < len(vals) {
				v = vals[i]
			}
			f(fr, v)
		}
		return cNone
	}
}

func (c *compiler) stmt(s Stmt) stmtFn {
	switch x := s.(type) {
	case *SLocal:
		return c.localStmt(x)
	case *SAssign:
		return c.assign(x)
	case *SCall:
		call := c.multi(x.call)
		return func(fr *Frame) ctl { call(fr); return cNone }
	case *SDo:
		return c.block(x.body)
	case *SWhile:
		cond, body := c.cond(x.cond), c.block(x.body)
		return func(fr *Frame) ctl {
			for cond(fr) {
				if r := body(fr); r != cNone {
					if r == cBreak {
						break
					}
					return r
				}
			}
			return cNone
		}
	case *SRepeat:
		cond, body := c.cond(x.cond), c.block(x.body)
		return func(fr *Frame) ctl {
			for {
				if r := body(fr); r != cNone {
					if r == cBreak {
						break
					}
					return r
				}
				if cond(fr) {
					break
				}
			}
			return cNone
		}
	case *SIf:
		return c.ifStmt(x)
	case *SNumFor:
		return c.numFor(x)
	case *SGenFor:
		return c.genFor(x)
	case *SLocalFunc:
		fe := c.expr(x.fn)
		sl := x.v.slot
		if x.v.captured {
			return func(fr *Frame) ctl {
				cell := &Cell{}
				fr.slots[sl] = cell
				cell.v = fe(fr)
				return cNone
			}
		}
		return func(fr *Frame) ctl { fr.slots[sl] = fe(fr); return cNone }
	case *SReturn:
		return c.returnStmt(x)
	case *SBreak:
		return func(*Frame) ctl { return cBreak }
	case *SGoto:
		l := x.label
		return func(fr *Frame) ctl { fr.gotoLabel = l; return cGoto }
	}
	panic(fmt.Sprintf("unknown statement %T", s))
}

func (c *compiler) ifStmt(x *SIf) stmtFn {
	n := len(x.conds)
	conds := make([]condFn, n)
	blocks := make([]stmtFn, n)
	for i := range x.conds {
		conds[i] = c.cond(x.conds[i])
		blocks[i] = c.block(x.blocks[i])
	}
	var els stmtFn
	if x.els != nil {
		els = c.block(x.els)
	}
	if n == 1 {
		c0, b0 := conds[0], blocks[0]
		if els == nil {
			return func(fr *Frame) ctl {
				if c0(fr) {
					return b0(fr)
				}
				return cNone
			}
		}
		return func(fr *Frame) ctl {
			if c0(fr) {
				return b0(fr)
			}
			return els(fr)
		}
	}
	return func(fr *Frame) ctl {
		for i := 0; i < n; i++ {
			if conds[i](fr) {
				return blocks[i](fr)
			}
		}
		if els != nil {
			return els(fr)
		}
		return cNone
	}
}

func (c *compiler) returnStmt(x *SReturn) stmtFn {
	line := x.line
	if len(x.exprs) == 0 {
		return func(fr *Frame) ctl { fr.ret = nil; return cReturn }
	}
	if x.tail {
		switch e := x.exprs[0].(type) {
		case *ECall:
			fnE := c.expr(e.fn)
			args := c.argList(e.args, false)
			desc := describe(e.fn)
			cl := e.line
			return func(fr *Frame) ctl {
				f := fnE(fr)
				a := args(fr, nil)
				fr.line = cl
				if k, ok := f.(*Closure); ok {
					fr.tailFn = k
					fr.tailArgs = a
					return cTail
				}
				fr.ret = callAny(fr, f, a, desc)
				return cReturn
			}
		case *EMethod:
			obj := c.expr(e.obj)
			dobj := describe(e.obj)
			args := c.argList(e.args, true)
			name := e.name
			desc := fmt.Sprintf(" (method '%s')", name)
			cl := e.line
			return func(fr *Frame) ctl {
				o := obj(fr)
				fr.line = cl
				f := fr.th.index(o, name, dobj)
				a := args(fr, o)
				fr.line = cl
				if k, ok := f.(*Closure); ok {
					fr.tailFn = k
					fr.tailArgs = a
					return cTail
				}
				fr.ret = callAny(fr, f, a, desc)
				return cReturn
			}
		}
	}
	if len(x.exprs) == 1 {
		if isMulti(x.exprs[0]) {
			m := c.multi(x.exprs[0])
			return func(fr *Frame) ctl { fr.ret = m(fr); return cReturn }
		}
		e := c.expr(x.exprs[0])
		_ = line
		return func(fr *Frame) ctl { fr.ret = []Value{e(fr)}; return cReturn }
	}
	list := c.argList(x.exprs, false)
	return func(fr *Frame) ctl { fr.ret = list(fr, nil); return cReturn }
}

func callAny(fr *Frame, f Value, a []Value, desc string) []Value {
	switch fv := f.(type) {
	case *Closure:
		return fr.th.callLua(fv, a)
	case *GoFunction:
		return fv.fn(fr.th, a)
	}
	return fr.th.callMeta(f, a, desc)
}

// ---------- assignment ----------

type assignTarget struct {
	kind int // 0 local, 1 upvalue, 2 index
	slot int
	capt bool
	obj  exprFn
	key  exprFn
	desc string
	line int
}

func (c *compiler) target(e Expr) *assignTarget {
	switch t := e.(type) {
	case *ELocal:
		return &assignTarget{kind: 0, slot: t.info.slot, capt: t.info.captured}
	case *EUpval:
		return &assignTarget{kind: 1, slot: t.idx}
	case *EIndex:
		return &assignTarget{kind: 2, obj: c.expr(t.obj), key: c.expr(t.key), desc: describe(t.obj), line: t.line}
	}
	panic("bad assignment target")
}

func (tg *assignTarget) store(fr *Frame, obj, key, val Value) {
	switch tg.kind {
	case 0:
		if tg.capt {
			fr.slots[tg.slot].(*Cell).v = val
		} else {
			fr.slots[tg.slot] = val
		}
	case 1:
		fr.fn.upvals[tg.slot].v = val
	case 2:
		if t, ok := obj.(*Table); ok && t.meta == nil {
			switch k := key.(type) {
			case string:
				t.setStr(k, val)
				return
			case int64:
				t.setInt(k, val)
				return
			}
		}
		fr.line = tg.line
		fr.th.setIndex(obj, key, val, tg.desc)
	}
}

func (c *compiler) assign(x *SAssign) stmtFn {
	if len(x.targets) == 1 && len(x.exprs) == 1 {
		val := c.expr(x.exprs[0])
		switch t := x.targets[0].(type) {
		case *ELocal:
			s := t.info.slot
			if t.info.captured {
				return func(fr *Frame) ctl { fr.slots[s].(*Cell).v = val(fr); return cNone }
			}
			return func(fr *Frame) ctl { fr.slots[s] = val(fr); return cNone }
		case *EUpval:
			i := t.idx
			return func(fr *Frame) ctl { fr.fn.upvals[i].v = val(fr); return cNone }
		case *EIndex:
			obj := c.expr(t.obj)
			desc := describe(t.obj)
			line := t.line
			if ks, ok := t.key.(*EStr); ok {
				k := ks.s
				return func(fr *Frame) ctl {
					o := obj(fr)
					v := val(fr)
					if tb, ok := o.(*Table); ok && tb.meta == nil {
						tb.setStr(k, v)
						return cNone
					}
					fr.line = line
					fr.th.setIndex(o, k, v, desc)
					return cNone
				}
			}
			key := c.expr(t.key)
			return func(fr *Frame) ctl {
				o := obj(fr)
				k := key(fr)
				v := val(fr)
				if tb, ok := o.(*Table); ok && tb.meta == nil {
					switch kk := k.(type) {
					case int64:
						tb.setInt(kk, v)
						return cNone
					case string:
						tb.setStr(kk, v)
						return cNone
					}
				}
				fr.line = line
				fr.th.setIndex(o, k, v, desc)
				return cNone
			}
		}
	}
	n := len(x.targets)
	tgs := make([]*assignTarget, n)
	for i, t := range x.targets {
		tgs[i] = c.target(t)
	}
	list := c.argList(x.exprs, false)
	return func(fr *Frame) ctl {
		objs := make([]Value, n)
		keys := make([]Value, n)
		for i, tg := range tgs {
			if tg.kind == 2 {
				objs[i] = tg.obj(fr)
				keys[i] = tg.key(fr)
			}
		}
		vals := list(fr, nil)
		for i := n - 1; i >= 0; i-- {
			var v Value
			if i < len(vals) {
				v = vals[i]
			}
			tgs[i].store(fr, objs[i], keys[i], v)
		}
		return cNone
	}
}

// ---------- loops ----------

func (c *compiler) numFor(x *SNumFor) stmtFn {
	start, limit := c.expr(x.start), c.expr(x.limit)
	var step exprFn
	if x.step != nil {
		step = c.expr(x.step)
	}
	body := c.block(x.body)
	set := c.setVarFn(x.v)
	slot := x.v.slot
	capt := x.v.captured
	line := x.line
	return func(fr *Frame) ctl {
		a, b := start(fr), limit(fr)
		var s Value = int64(1)
		if step != nil {
			s = step(fr)
		}
		th := fr.th
		ia, ok1 := a.(int64)
		is, ok2 := s.(int64)
		if ok1 && ok2 {
			if is == 0 {
				fr.line = line
				th.rtError("'for' step is zero")
			}
			var lim int64
			switch l := b.(type) {
			case int64:
				lim = l
			case float64:
				if math.IsNaN(l) {
					return cNone
				}
				var fl float64
				if is > 0 {
					fl = math.Floor(l)
				} else {
					fl = math.Ceil(l)
				}
				if fl >= 9223372036854775808.0 {
					lim = math.MaxInt64
				} else if fl < -9223372036854775808.0 {
					lim = math.MinInt64
				} else {
					lim = int64(fl)
				}
			default:
				fr.line = line
				if _, ok := toNumberNoStr(b); !ok {
					th.rtError("'for' limit must be a number")
				}
			}
			if is > 0 {
				if ia > lim {
					return cNone
				}
			} else if ia < lim {
				return cNone
			}
			var count uint64
			if is > 0 {
				count = (uint64(lim) - uint64(ia)) / uint64(is)
			} else {
				count = (uint64(ia) - uint64(lim)) / (uint64(-(is + 1)) + 1)
			}
			i := ia
			for {
				if capt {
					fr.slots[slot] = &Cell{i}
				} else {
					fr.slots[slot] = i
				}
				if r := body(fr); r != cNone {
					if r == cBreak {
						break
					}
					return r
				}
				if count == 0 {
					break
				}
				count--
				i += is
			}
			return cNone
		}
		fa, oka := toNumberNoStr(a)
		fb, okb := toNumberNoStr(b)
		fs, oks := toNumberNoStr(s)
		fr.line = line
		if !oka {
			th.rtError("'for' initial value must be a number")
		}
		if !okb {
			th.rtError("'for' limit must be a number")
		}
		if !oks {
			th.rtError("'for' step must be a number")
		}
		fl, _ := toFloat(fa)
		ff, _ := toFloat(fb)
		fst, _ := toFloat(fs)
		if fst == 0 {
			th.rtError("'for' step is zero")
		}
		for i := fl; (fst > 0 && i <= ff) || (fst < 0 && i >= ff); i += fst {
			set(fr, i)
			if r := body(fr); r != cNone {
				if r == cBreak {
					break
				}
				return r
			}
		}
		return cNone
	}
}

func toNumberNoStr(v Value) (Value, bool) {
	switch v.(type) {
	case int64, float64:
		return v, true
	}
	return nil, false
}

func (c *compiler) genFor(x *SGenFor) stmtFn {
	list := c.argList(x.exprs, false)
	body := c.block(x.body)
	nv := len(x.vars)
	sets := make([]func(*Frame, Value), nv)
	for i, v := range x.vars {
		sets[i] = c.setVarFn(v)
	}
	line := x.line
	return func(fr *Frame) ctl {
		vals := list(fr, nil)
		var f, s, ctlv, closing Value
		if len(vals) > 0 {
			f = vals[0]
		}
		if len(vals) > 1 {
			s = vals[1]
		}
		if len(vals) > 2 {
			ctlv = vals[2]
		}
		if len(vals) > 3 {
			closing = vals[3]
		}
		th := fr.th
		run := func(fr *Frame) ctl {
			if gf, ok := f.(*GoFunction); ok && ctlv == nil {
				if t, ok := s.(*Table); ok {
					if gf == nextFn {
						pos := 0
						for {
							k, v, np := t.nextAt(pos)
							if k == nil {
								return cNone
							}
							pos = np
							sets[0](fr, k)
							if nv > 1 {
								sets[1](fr, v)
								for j := 2; j < nv; j++ {
									sets[j](fr, nil)
								}
							}
							if r := body(fr); r != cNone {
								if r == cBreak {
									return cNone
								}
								return r
							}
						}
					}
				}
			}
			if gf, ok := f.(*GoFunction); ok && gf == ipairsIter {
				if i0, ok := ctlv.(int64); ok {
					t, isT := s.(*Table)
					for i := i0 + 1; ; i++ {
						var v Value
						if isT && t.meta == nil {
							v = t.getInt(i)
						} else {
							fr.line = line
							v = th.index(s, i, " (field '?')")
						}
						if v == nil {
							return cNone
						}
						sets[0](fr, i)
						if nv > 1 {
							sets[1](fr, v)
							for j := 2; j < nv; j++ {
								sets[j](fr, nil)
							}
						}
						if r := body(fr); r != cNone {
							if r == cBreak {
								return cNone
							}
							return r
						}
					}
				}
			}
			for {
				fr.line = line
				args := []Value{s, ctlv}
				var r []Value
				switch fv := f.(type) {
				case *Closure:
					r = th.callLua(fv, args)
				case *GoFunction:
					r = fv.fn(th, args)
				default:
					r = th.callMeta(f, args, " (for iterator 'for iterator')")
				}
				var v0 Value
				if len(r) > 0 {
					v0 = r[0]
				}
				if v0 == nil {
					return cNone
				}
				ctlv = v0
				for j := 0; j < nv; j++ {
					var v Value
					if j < len(r) {
						v = r[j]
					}
					sets[j](fr, v)
				}
				if rr := body(fr); rr != cNone {
					if rr == cBreak {
						return cNone
					}
					return rr
				}
			}
		}
		if closing == nil || closing == false {
			return run(fr)
		}
		if th.metaOf(closing, "__close") == nil {
			fr.line = line
			th.rtError("variable '(for state)' got a non-closable value")
		}
		return th.withClose(fr, closing, run)
	}
}

// ---------- expressions ----------

func (c *compiler) multi(e Expr) multiFn {
	switch x := e.(type) {
	case *ECall:
		return c.call(x)
	case *EMethod:
		return c.method(x)
	case *EVararg:
		return func(fr *Frame) []Value { return fr.varargs }
	}
	panic("not a multi expression")
}

// argList compiles an expression list; the returned function receives an
// optional leading "self" value (used when self==true).
func (c *compiler) argList(list []Expr, self bool) func(*Frame, Value) []Value {
	n := len(list)
	if n == 0 {
		if self {
			return func(fr *Frame, s Value) []Value { return []Value{s} }
		}
		return func(*Frame, Value) []Value { return nil }
	}
	lastMulti := isMulti(list[n-1])
	fns := make([]exprFn, 0, n)
	cnt := n
	if lastMulti {
		cnt = n - 1
	}
	for i := 0; i < cnt; i++ {
		fns = append(fns, c.expr(list[i]))
	}
	var lastM multiFn
	if lastMulti {
		lastM = c.multi(list[n-1])
	}
	off := 0
	if self {
		off = 1
	}
	if !lastMulti {
		switch {
		case cnt == 1 && !self:
			f0 := fns[0]
			return func(fr *Frame, _ Value) []Value { return []Value{f0(fr)} }
		case cnt == 2 && !self:
			f0, f1 := fns[0], fns[1]
			return func(fr *Frame, _ Value) []Value {
				a := f0(fr)
				return []Value{a, f1(fr)}
			}
		}
		return func(fr *Frame, s Value) []Value {
			out := make([]Value, cnt+off)
			if self {
				out[0] = s
			}
			for i, f := range fns {
				out[i+off] = f(fr)
			}
			return out
		}
	}
	return func(fr *Frame, s Value) []Value {
		out := make([]Value, cnt+off, cnt+off+4)
		if self {
			out[0] = s
		}
		for i, f := range fns {
			out[i+off] = f(fr)
		}
		rest := lastM(fr)
		if cnt+off == 0 {
			return rest
		}
		return append(out, rest...)
	}
}

func (c *compiler) call(e *ECall) multiFn {
	fnE := c.expr(e.fn)
	desc := describe(e.fn)
	args := c.argList(e.args, false)
	line := e.line
	return func(fr *Frame) []Value {
		f := fnE(fr)
		a := args(fr, nil)
		fr.line = line
		switch fv := f.(type) {
		case *Closure:
			return fr.th.callLua(fv, a)
		case *GoFunction:
			return fv.fn(fr.th, a)
		}
		return fr.th.callMeta(f, a, desc)
	}
}

func (c *compiler) method(e *EMethod) multiFn {
	obj := c.expr(e.obj)
	dobj := describe(e.obj)
	name := e.name
	desc := fmt.Sprintf(" (method '%s')", name)
	args := c.argList(e.args, true)
	line := e.line
	return func(fr *Frame) []Value {
		o := obj(fr)
		var f Value
		if t, ok := o.(*Table); ok {
			f = t.getStr(name)
			if f == nil && t.meta != nil {
				fr.line = line
				f = fr.th.index(o, name, dobj)
			}
		} else {
			fr.line = line
			f = fr.th.index(o, name, dobj)
		}
		a := args(fr, o)
		fr.line = line
		switch fv := f.(type) {
		case *Closure:
			return fr.th.callLua(fv, a)
		case *GoFunction:
			return fv.fn(fr.th, a)
		}
		return fr.th.callMeta(f, a, desc)
	}
}

func constFn(v Value) exprFn { return func(*Frame) Value { return v } }

func (c *compiler) expr(e Expr) exprFn {
	switch x := e.(type) {
	case *ENil:
		return constFn(nil)
	case *ETrue:
		return constFn(true)
	case *EFalse:
		return constFn(false)
	case *ENum:
		return constFn(x.v)
	case *EStr:
		return constFn(x.s)
	case *EVararg:
		return func(fr *Frame) Value {
			if len(fr.varargs) > 0 {
				return fr.varargs[0]
			}
			return nil
		}
	case *ELocal:
		return c.readVar(x.info)
	case *EUpval:
		i := x.idx
		return func(fr *Frame) Value { return fr.fn.upvals[i].v }
	case *EParen:
		return c.expr(x.e)
	case *ECall, *EMethod:
		m := c.multi(x)
		return func(fr *Frame) Value {
			r := m(fr)
			if len(r) > 0 {
				return r[0]
			}
			return nil
		}
	case *EFunc:
		p := c.function(x.fb)
		descs := p.upvals
		return func(fr *Frame) Value {
			ups := make([]*Cell, len(descs))
			for i, d := range descs {
				if d.fromLocal {
					ups[i] = fr.slots[d.slot].(*Cell)
				} else {
					ups[i] = fr.fn.upvals[d.idx]
				}
			}
			return &Closure{proto: p, upvals: ups}
		}
	case *EIndex:
		return c.indexExpr(x)
	case *EBin:
		return c.binary(x)
	case *EUn:
		return c.unary(x)
	case *ETable:
		return c.tableCons(x)
	}
	panic(fmt.Sprintf("unknown expression %T", e))
}

func (c *compiler) indexExpr(x *EIndex) exprFn {
	obj := c.expr(x.obj)
	desc := describe(x.obj)
	line := x.line
	if ks, ok := x.key.(*EStr); ok {
		k := ks.s
		return func(fr *Frame) Value {
			o := obj(fr)
			if t, ok := o.(*Table); ok {
				v := t.getStr(k)
				if v != nil || t.meta == nil {
					return v
				}
			}
			fr.line = line
			return fr.th.index(o, k, desc)
		}
	}
	key := c.expr(x.key)
	return func(fr *Frame) Value {
		o := obj(fr)
		k := key(fr)
		if t, ok := o.(*Table); ok {
			var v Value
			if i, ok := k.(int64); ok {
				v = t.getInt(i)
			} else {
				v = t.get(k)
			}
			if v != nil || t.meta == nil {
				return v
			}
		}
		fr.line = line
		return fr.th.index(o, k, desc)
	}
}

func (c *compiler) tableCons(x *ETable) exprFn {
	type item struct {
		key, val exprFn
		multi    multiFn
	}
	items := make([]item, len(x.items))
	npos := 0
	for i, it := range x.items {
		if it.key == nil {
			npos++
			if i == len(x.items)-1 && isMulti(it.val) {
				items[i] = item{multi: c.multi(it.val)}
				continue
			}
			items[i] = item{val: c.expr(it.val)}
		} else {
			items[i] = item{key: c.expr(it.key), val: c.expr(it.val)}
		}
	}
	nhash := len(x.items) - npos
	line := x.line
	return func(fr *Frame) Value {
		t := newTable(0, nhash)
		var pos []Value
		if npos > 0 {
			pos = make([]Value, 0, npos)
		}
		for i := range items {
			it := &items[i]
			switch {
			case it.multi != nil:
				pos = append(pos, it.multi(fr)...)
			case it.key == nil:
				pos = append(pos, it.val(fr))
			default:
				k := it.key(fr)
				v := it.val(fr)
				if k == nil {
					fr.line = line
					fr.th.rtError("index is nil")
				}
				if isNaN(k) {
					fr.line = line
					fr.th.rtError("index is NaN")
				}
				t.set(k, v)
			}
		}
		if len(pos) > 0 {
			t.adoptArray(pos)
		}
		return t
	}
}

func (c *compiler) unary(x *EUn) exprFn {
	e := c.expr(x.e)
	d := describe(x.e)
	line := x.line
	switch x.op {
	case opNot:
		cd := c.cond(x.e)
		return func(fr *Frame) Value { return !cd(fr) }
	case opNeg:
		return func(fr *Frame) Value {
			v := e(fr)
			switch n := v.(type) {
			case int64:
				return -n
			case float64:
				return -n
			}
			fr.line = line
			return fr.th.unm(v, d)
		}
	case opLen:
		return func(fr *Frame) Value {
			v := e(fr)
			switch n := v.(type) {
			case string:
				return int64(len(n))
			case *Table:
				if n.meta == nil {
					return n.length()
				}
			}
			fr.line = line
			return fr.th.length(v, d)
		}
	case opBnot:
		return func(fr *Frame) Value {
			v := e(fr)
			if n, ok := v.(int64); ok {
				return ^n
			}
			fr.line = line
			return fr.th.bnot(v, d)
		}
	}
	panic("bad unary op")
}

func (c *compiler) cond(e Expr) condFn {
	switch x := e.(type) {
	case *ETrue:
		return func(*Frame) bool { return true }
	case *EFalse, *ENil:
		return func(*Frame) bool { return false }
	case *EParen:
		if !isMulti(x.e) {
			return c.cond(x.e)
		}
	case *EUn:
		if x.op == opNot {
			in := c.cond(x.e)
			return func(fr *Frame) bool { return !in(fr) }
		}
	case *EBin:
		l, r := c.expr(x.l), c.expr(x.r)
		line := x.line
		switch x.op {
		case opAnd:
			cl, cr := c.cond(x.l), c.cond(x.r)
			return func(fr *Frame) bool { return cl(fr) && cr(fr) }
		case opOr:
			cl, cr := c.cond(x.l), c.cond(x.r)
			return func(fr *Frame) bool { return cl(fr) || cr(fr) }
		case opEq:
			return func(fr *Frame) bool {
				a, b := l(fr), r(fr)
				if rawEquals(a, b) {
					return true
				}
				fr.line = line
				return fr.th.equals(a, b)
			}
		case opNe:
			return func(fr *Frame) bool {
				a, b := l(fr), r(fr)
				if rawEquals(a, b) {
					return false
				}
				fr.line = line
				return !fr.th.equals(a, b)
			}
		case opLt:
			return func(fr *Frame) bool {
				a, b := l(fr), r(fr)
				if x, ok := a.(int64); ok {
					if y, ok := b.(int64); ok {
						return x < y
					}
				}
				fr.line = line
				return fr.th.lessThan(a, b)
			}
		case opLe:
			return func(fr *Frame) bool {
				a, b := l(fr), r(fr)
				if x, ok := a.(int64); ok {
					if y, ok := b.(int64); ok {
						return x <= y
					}
				}
				fr.line = line
				return fr.th.lessEq(a, b)
			}
		case opGt:
			return func(fr *Frame) bool {
				a, b := l(fr), r(fr)
				if x, ok := a.(int64); ok {
					if y, ok := b.(int64); ok {
						return x > y
					}
				}
				fr.line = line
				return fr.th.lessThan(b, a)
			}
		case opGe:
			return func(fr *Frame) bool {
				a, b := l(fr), r(fr)
				if x, ok := a.(int64); ok {
					if y, ok := b.(int64); ok {
						return x >= y
					}
				}
				fr.line = line
				return fr.th.lessEq(b, a)
			}
		}
	}
	ex := c.expr(e)
	return func(fr *Frame) bool {
		v := ex(fr)
		if b, ok := v.(bool); ok {
			return b
		}
		return v != nil
	}
}

func (c *compiler) binary(x *EBin) exprFn {
	switch x.op {
	case opAnd:
		l, r := c.expr(x.l), c.expr(x.r)
		return func(fr *Frame) Value {
			v := l(fr)
			if !truthy(v) {
				return v
			}
			return r(fr)
		}
	case opOr:
		l, r := c.expr(x.l), c.expr(x.r)
		return func(fr *Frame) Value {
			v := l(fr)
			if truthy(v) {
				return v
			}
			return r(fr)
		}
	case opEq, opNe, opLt, opLe, opGt, opGe:
		cd := c.cond(x)
		return func(fr *Frame) Value { return cd(fr) }
	case opConcat:
		var parts []Expr
		var cur Expr = x
		for {
			b, ok := cur.(*EBin)
			if ok && b.op == opConcat {
				parts = append(parts, b.l)
				cur = b.r
				continue
			}
			parts = append(parts, cur)
			break
		}
		fns := make([]exprFn, len(parts))
		descs := make([]string, len(parts))
		for i, p := range parts {
			fns[i] = c.expr(p)
			descs[i] = describe(p)
		}
		line := x.line
		if len(fns) == 2 {
			f0, f1 := fns[0], fns[1]
			d0, d1 := descs[0], descs[1]
			return func(fr *Frame) Value {
				a := f0(fr)
				b := f1(fr)
				if s1, ok := a.(string); ok {
					if s2, ok := b.(string); ok {
						return s1 + s2
					}
				}
				fr.line = line
				return fr.th.concat2(a, b, d0, d1)
			}
		}
		return func(fr *Frame) Value {
			vals := make([]Value, len(fns))
			for i, f := range fns {
				vals[i] = f(fr)
			}
			fr.line = line
			return fr.th.concat(vals, descs)
		}
	}
	l, r := c.expr(x.l), c.expr(x.r)
	da, db := describe(x.l), describe(x.r)
	line := x.line
	op := x.op
	switch op {
	case opAdd:
		return func(fr *Frame) Value {
			a, b := l(fr), r(fr)
			switch x := a.(type) {
			case int64:
				switch y := b.(type) {
				case int64:
					return x + y
				case float64:
					return float64(x) + y
				}
			case float64:
				switch y := b.(type) {
				case float64:
					return x + y
				case int64:
					return x + float64(y)
				}
			}
			fr.line = line
			return fr.th.arith(op, a, b, da, db)
		}
	case opSub:
		return func(fr *Frame) Value {
			a, b := l(fr), r(fr)
			switch x := a.(type) {
			case int64:
				switch y := b.(type) {
				case int64:
					return x - y
				case float64:
					return float64(x) - y
				}
			case float64:
				switch y := b.(type) {
				case float64:
					return x - y
				case int64:
					return x - float64(y)
				}
			}
			fr.line = line
			return fr.th.arith(op, a, b, da, db)
		}
	case opMul:
		return func(fr *Frame) Value {
			a, b := l(fr), r(fr)
			switch x := a.(type) {
			case int64:
				switch y := b.(type) {
				case int64:
					return x * y
				case float64:
					return float64(x) * y
				}
			case float64:
				switch y := b.(type) {
				case float64:
					return x * y
				case int64:
					return x * float64(y)
				}
			}
			fr.line = line
			return fr.th.arith(op, a, b, da, db)
		}
	case opDiv:
		return func(fr *Frame) Value {
			a, b := l(fr), r(fr)
			if x, ok := a.(float64); ok {
				if y, ok := b.(float64); ok {
					return x / y
				}
			}
			fr.line = line
			return fr.th.arith(op, a, b, da, db)
		}
	}
	return func(fr *Frame) Value {
		a, b := l(fr), r(fr)
		fr.line = line
		return fr.th.arith(op, a, b, da, db)
	}
}

// newMainClosure builds the closure for a compiled chunk with the given _ENV.
func newMainClosure(p *Proto, env Value) *Closure {
	return &Closure{proto: p, upvals: []*Cell{{v: env}}}
}
