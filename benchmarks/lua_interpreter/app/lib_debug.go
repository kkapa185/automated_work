package main

func frameAtLevel(th *Thread, level int) *Frame {
	fr := th.top
	for i := 1; i < level && fr != nil; i++ {
		fr = fr.parent
	}
	if level < 1 {
		return nil
	}
	return fr
}

func funcInfo(th *Thread, f Value) *Table {
	t := newTable(0, 12)
	switch fn := f.(type) {
	case *Closure:
		p := fn.proto
		t.setStr("source", "@"+p.chunk)
		t.setStr("short_src", p.chunk)
		what := "Lua"
		if p.isMain {
			what = "main"
		}
		t.setStr("what", what)
		t.setStr("linedefined", int64(p.line))
		t.setStr("lastlinedefined", int64(p.lastLine))
		t.setStr("nups", int64(len(fn.upvals)))
		t.setStr("nparams", int64(p.nparams))
		t.setStr("isvararg", p.isVararg)
	default:
		t.setStr("source", "=[C]")
		t.setStr("short_src", "[C]")
		t.setStr("what", "C")
		t.setStr("linedefined", int64(-1))
		t.setStr("lastlinedefined", int64(-1))
		t.setStr("nups", int64(0))
		t.setStr("nparams", int64(0))
		t.setStr("isvararg", true)
	}
	t.setStr("currentline", int64(-1))
	t.setStr("namewhat", "")
	t.setStr("istailcall", false)
	t.setStr("func", f)
	return t
}

func openDebug(th *Thread) {
	d := newTable(0, 16)
	G.setStr("debug", d)
	loadedTable.setStr("debug", d)
	reg(d, "traceback", func(th *Thread, args []Value) []Value {
		if _, ok := argOr(args, 0).(*Coroutine); ok {
			args = args[1:]
		}
		msg := argOr(args, 0)
		if msg != nil {
			if _, ok := msg.(string); !ok {
				if _, ok := toNumber(msg); !ok {
					return []Value{msg}
				}
			}
		}
		level := int(optInt(th, args, 1, "traceback", 1))
		m := ""
		if msg != nil {
			m = th.tostr(msg)
		}
		return []Value{th.traceback(m, frameAtLevel(th, level))}
	})
	reg(d, "getinfo", func(th *Thread, args []Value) []Value {
		if _, ok := argOr(args, 0).(*Coroutine); ok {
			args = args[1:]
		}
		switch f := argOr(args, 0).(type) {
		case *Closure, *GoFunction:
			return []Value{funcInfo(th, f)}
		}
		level := checkInt(th, args, 0, "getinfo")
		if level < 0 {
			return []Value{nil}
		}
		if level == 0 {
			return []Value{funcInfo(th, &GoFunction{name: "getinfo"})}
		}
		fr := frameAtLevel(th, int(level))
		if fr == nil {
			return []Value{nil}
		}
		if fr.marker || fr.fn == nil {
			return []Value{funcInfo(th, &GoFunction{name: "?"})}
		}
		t := funcInfo(th, fr.fn)
		t.setStr("currentline", int64(fr.line))
		return []Value{t}
	})
	reg(d, "sethook", func(th *Thread, args []Value) []Value { return nil })
	reg(d, "gethook", func(th *Thread, args []Value) []Value { return []Value{nil} })
	reg(d, "getlocal", func(th *Thread, args []Value) []Value { return []Value{nil} })
	reg(d, "getregistry", func(th *Thread, args []Value) []Value { return []Value{newTable(0, 0)} })
	reg(d, "getmetatable", func(th *Thread, args []Value) []Value {
		mt := th.getMeta(checkAny(th, args, 0, "getmetatable"))
		if mt == nil {
			return []Value{nil}
		}
		return []Value{mt}
	})
	reg(d, "setmetatable", func(th *Thread, args []Value) []Value {
		var mt *Table
		switch m := argOr(args, 1).(type) {
		case nil:
		case *Table:
			mt = m
		default:
			typeErr(th, args, 1, "setmetatable", "nil or table")
		}
		switch o := argOr(args, 0).(type) {
		case *Table:
			o.meta = mt
		case *Userdata:
			o.meta = mt
		case string:
			stringMeta = mt
		}
		return []Value{argOr(args, 0)}
	})
	reg(d, "getupvalue", func(th *Thread, args []Value) []Value {
		cl, ok := argOr(args, 0).(*Closure)
		i := int(checkInt(th, args, 1, "getupvalue"))
		if !ok || i < 1 || i > len(cl.upvals) {
			return []Value{nil}
		}
		return []Value{cl.proto.upvals[i-1].name, cl.upvals[i-1].v}
	})
	reg(d, "setupvalue", func(th *Thread, args []Value) []Value {
		cl, ok := argOr(args, 0).(*Closure)
		i := int(checkInt(th, args, 1, "setupvalue"))
		if !ok || i < 1 || i > len(cl.upvals) {
			return []Value{nil}
		}
		cl.upvals[i-1].v = argOr(args, 2)
		return []Value{cl.proto.upvals[i-1].name}
	})
	reg(d, "upvalueid", func(th *Thread, args []Value) []Value {
		cl, ok := argOr(args, 0).(*Closure)
		i := int(checkInt(th, args, 1, "upvalueid"))
		if !ok || i < 1 || i > len(cl.upvals) {
			return []Value{nil}
		}
		return []Value{&Userdata{data: cl.upvals[i-1]}}
	})
}
