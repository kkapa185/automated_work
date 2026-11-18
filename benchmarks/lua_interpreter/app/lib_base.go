package main

import (
	"fmt"
	"os"
	"runtime"
	"strings"
)

var G *Table
var packageTable *Table
var loadedTable *Table

func reg(t *Table, name string, fn func(th *Thread, args []Value) []Value) *GoFunction {
	f := &GoFunction{name: name, fn: fn}
	t.setStr(name, f)
	return f
}

// ---- argument helpers ----

func argErr(th *Thread, n int, fname, msg string) {
	th.rtError("bad argument #%d to '%s' (%s)", n, fname, msg)
}

func typeErr(th *Thread, args []Value, i int, fname, expected string) {
	got := "no value"
	if i < len(args) {
		got = th.objTypeName(args[i])
	}
	argErr(th, i+1, fname, expected+" expected, got "+got)
}

func checkAny(th *Thread, args []Value, i int, fname string) Value {
	if i >= len(args) {
		argErr(th, i+1, fname, "value expected")
	}
	return args[i]
}

func checkTable(th *Thread, args []Value, i int, fname string) *Table {
	if i < len(args) {
		if t, ok := args[i].(*Table); ok {
			return t
		}
	}
	typeErr(th, args, i, fname, "table")
	return nil
}

func checkInt(th *Thread, args []Value, i int, fname string) int64 {
	if i < len(args) {
		switch v := args[i].(type) {
		case int64:
			return v
		case float64:
			if n, ok := floatToInt(v); ok {
				return n
			}
			argErr(th, i+1, fname, "number has no integer representation")
		case string:
			if n, ok := str2number(v); ok {
				if k, ok := toInteger(n); ok {
					return k
				}
				argErr(th, i+1, fname, "number has no integer representation")
			}
		}
	}
	typeErr(th, args, i, fname, "number")
	return 0
}

func optInt(th *Thread, args []Value, i int, fname string, def int64) int64 {
	if i >= len(args) || args[i] == nil {
		return def
	}
	return checkInt(th, args, i, fname)
}

func checkNum(th *Thread, args []Value, i int, fname string) float64 {
	if i < len(args) {
		if f, ok := toFloat(args[i]); ok {
			return f
		}
	}
	typeErr(th, args, i, fname, "number")
	return 0
}

func checkStr(th *Thread, args []Value, i int, fname string) string {
	if i < len(args) {
		switch v := args[i].(type) {
		case string:
			return v
		case int64, float64:
			return numToString(v)
		}
	}
	typeErr(th, args, i, fname, "string")
	return ""
}

func optStr(th *Thread, args []Value, i int, fname string, def string) string {
	if i >= len(args) || args[i] == nil {
		return def
	}
	return checkStr(th, args, i, fname)
}

func argOr(args []Value, i int) Value {
	if i < len(args) {
		return args[i]
	}
	return nil
}

// ---- chunk loading ----

func (th *Thread) loadChunk(src, chunkname string, env Value) (Value, error) {
	if len(src) > 0 && src[0] == 0x1b {
		return nil, fmt.Errorf("%s: bad binary format (precompiled chunks are not supported)", chunkID(chunkname))
	}
	short := chunkID(chunkname)
	fb, err := parseChunk(src, short)
	if err != nil {
		return nil, err
	}
	p := compileFunction(fb, short)
	return newMainClosure(p, env), nil
}

func readFileChunk(path string) (string, error) {
	var data []byte
	var err error
	if path == "" {
		data, err = readAllStdin()
	} else {
		data, err = os.ReadFile(path)
	}
	if err != nil {
		return "", err
	}
	s := string(data)
	if len(s) > 0 && s[0] == '#' {
		i := strings.IndexByte(s, '\n')
		if i < 0 {
			s = ""
		} else {
			s = "--" + s[i:] // keep line numbering
		}
	}
	return s, nil
}

func tostringFn(th *Thread, args []Value) []Value {
	return []Value{th.tostr(checkAny(th, args, 0, "tostring"))}
}

func openBase(th *Thread) {
	G = newTable(0, 64)
	g := G
	g.setStr("_G", g)
	g.setStr("_VERSION", "Lua 5.4")

	reg(g, "print", func(th *Thread, args []Value) []Value {
		for i, a := range args {
			if i > 0 {
				stdout.WriteByte('\t')
			}
			stdout.WriteString(th.tostr(a))
		}
		stdout.WriteByte('\n')
		return nil
	})
	reg(g, "type", func(th *Thread, args []Value) []Value {
		return []Value{typeName(checkAny(th, args, 0, "type"))}
	})
	reg(g, "tostring", tostringFn)
	reg(g, "tonumber", func(th *Thread, args []Value) []Value {
		if len(args) < 2 || args[1] == nil {
			v := checkAny(th, args, 0, "tonumber")
			switch x := v.(type) {
			case int64, float64:
				return []Value{x}
			case string:
				if n, ok := str2number(x); ok {
					return []Value{n}
				}
			}
			return []Value{nil}
		}
		base := checkInt(th, args, 1, "tonumber")
		s, ok := args[0].(string)
		if !ok {
			typeErr(th, args, 0, "tonumber", "string")
		}
		if base < 2 || base > 36 {
			argErr(th, 2, "tonumber", "base out of range")
		}
		s = strings.TrimFunc(s, func(r rune) bool { return r < 128 && isSpaceC(byte(r)) })
		neg := false
		if strings.HasPrefix(s, "-") {
			neg = true
			s = s[1:]
		} else if strings.HasPrefix(s, "+") {
			s = s[1:]
		}
		if s == "" {
			return []Value{nil}
		}
		var n int64
		for i := 0; i < len(s); i++ {
			c := s[i]
			var d int64
			switch {
			case c >= '0' && c <= '9':
				d = int64(c - '0')
			case c >= 'a' && c <= 'z':
				d = int64(c-'a') + 10
			case c >= 'A' && c <= 'Z':
				d = int64(c-'A') + 10
			default:
				return []Value{nil}
			}
			if d >= base {
				return []Value{nil}
			}
			n = n*base + d
		}
		if neg {
			n = -n
		}
		return []Value{n}
	})
	nextFn = reg(g, "next", func(th *Thread, args []Value) []Value {
		t := checkTable(th, args, 0, "next")
		pos, ok := t.posOf(argOr(args, 1))
		if !ok {
			th.rtError("invalid key to 'next'")
		}
		k, v, _ := t.nextAt(pos)
		if k == nil {
			return []Value{nil}
		}
		return []Value{k, v}
	})
	reg(g, "pairs", func(th *Thread, args []Value) []Value {
		v := checkAny(th, args, 0, "pairs")
		if h := th.metaOf(v, "__pairs"); h != nil {
			r := th.call(h, []Value{v})
			out := make([]Value, 3)
			copy(out, r)
			return out
		}
		if _, ok := v.(*Table); !ok {
			argErr(th, 1, "for iterator", "table expected, got "+th.objTypeName(v))
		}
		return []Value{nextFn, v, nil}
	})
	ipairsIter = &GoFunction{name: "ipairs_iter", fn: func(th *Thread, args []Value) []Value {
		i := checkInt(th, args, 1, "ipairs") + 1
		v := th.index(args[0], i, " (field '?')")
		if v == nil {
			return []Value{nil}
		}
		return []Value{i, v}
	}}
	reg(g, "ipairs", func(th *Thread, args []Value) []Value {
		v := checkAny(th, args, 0, "ipairs")
		return []Value{ipairsIter, v, int64(0)}
	})
	reg(g, "select", func(th *Thread, args []Value) []Value {
		if s, ok := argOr(args, 0).(string); ok && s == "#" {
			return []Value{int64(len(args) - 1)}
		}
		n := checkInt(th, args, 0, "select")
		cnt := int64(len(args) - 1)
		if n < 0 {
			n = cnt + n
			if n < 0 {
				argErr(th, 1, "select", "index out of range")
			}
			return args[1+n:]
		}
		if n == 0 {
			argErr(th, 1, "select", "index out of range")
		}
		if n > cnt {
			return nil
		}
		return args[n:]
	})
	reg(g, "rawget", func(th *Thread, args []Value) []Value {
		t := checkTable(th, args, 0, "rawget")
		return []Value{t.get(checkAny(th, args, 1, "rawget"))}
	})
	reg(g, "rawset", func(th *Thread, args []Value) []Value {
		t := checkTable(th, args, 0, "rawset")
		k := checkAny(th, args, 1, "rawset")
		v := checkAny(th, args, 2, "rawset")
		th.checkKey(k)
		t.set(k, v)
		return []Value{t}
	})
	reg(g, "rawequal", func(th *Thread, args []Value) []Value {
		return []Value{rawEquals(checkAny(th, args, 0, "rawequal"), checkAny(th, args, 1, "rawequal"))}
	})
	reg(g, "rawlen", func(th *Thread, args []Value) []Value {
		switch v := argOr(args, 0).(type) {
		case *Table:
			return []Value{v.length()}
		case string:
			return []Value{int64(len(v))}
		}
		argErr(th, 1, "rawlen", "table or string expected")
		return nil
	})
	reg(g, "setmetatable", func(th *Thread, args []Value) []Value {
		t := checkTable(th, args, 0, "setmetatable")
		var mt *Table
		switch m := argOr(args, 1).(type) {
		case nil:
			if len(args) < 2 {
				typeErr(th, args, 1, "setmetatable", "nil or table")
			}
		case *Table:
			mt = m
		default:
			typeErr(th, args, 1, "setmetatable", "nil or table")
		}
		if t.meta != nil && t.meta.getStr("__metatable") != nil {
			th.rtError("cannot change a protected metatable")
		}
		t.meta = mt
		return []Value{t}
	})
	reg(g, "getmetatable", func(th *Thread, args []Value) []Value {
		mt := th.getMeta(checkAny(th, args, 0, "getmetatable"))
		if mt == nil {
			return []Value{nil}
		}
		if p := mt.getStr("__metatable"); p != nil {
			return []Value{p}
		}
		return []Value{mt}
	})
	reg(g, "assert", func(th *Thread, args []Value) []Value {
		v := checkAny(th, args, 0, "assert")
		if truthy(v) {
			return args
		}
		if len(args) > 1 {
			th.throw(args[1])
		}
		th.rtError("assertion failed!")
		return nil
	})
	reg(g, "error", func(th *Thread, args []Value) []Value {
		v := argOr(args, 0)
		level := optInt(th, args, 1, "error", 1)
		if s, ok := v.(string); ok && level > 0 {
			v = th.whereLevel(int(level)) + s
		}
		th.throw(v)
		return nil
	})
	reg(g, "pcall", func(th *Thread, args []Value) []Value {
		if len(args) == 0 {
			argErr(th, 1, "pcall", "value expected")
		}
		res, err := th.pcall(args[0], args[1:], nil)
		if err != nil {
			return []Value{false, err.value}
		}
		return append([]Value{true}, res...)
	})
	reg(g, "xpcall", func(th *Thread, args []Value) []Value {
		if len(args) < 2 {
			argErr(th, 2, "xpcall", "value expected")
		}
		res, err := th.pcall(args[0], args[2:], args[1])
		if err != nil {
			return []Value{false, err.value}
		}
		return append([]Value{true}, res...)
	})
	reg(g, "collectgarbage", func(th *Thread, args []Value) []Value {
		opt := optStr(th, args, 0, "collectgarbage", "collect")
		switch opt {
		case "count":
			var ms runtime.MemStats
			runtime.ReadMemStats(&ms)
			return []Value{float64(ms.HeapAlloc) / 1024.0, int64(0)}[:1]
		case "collect":
			runtime.GC()
			return []Value{int64(0)}
		case "step":
			return []Value{true}
		case "isrunning":
			return []Value{true}
		case "incremental", "generational":
			return []Value{"incremental"}
		case "stop", "restart", "setpause", "setstepmul":
			return []Value{int64(0)}
		}
		argErr(th, 1, "collectgarbage", "invalid option '"+opt+"'")
		return nil
	})
	reg(g, "load", func(th *Thread, args []Value) []Value {
		var src string
		chunkname := ""
		switch c := argOr(args, 0).(type) {
		case string:
			src = c
			chunkname = c
		case *Closure, *GoFunction:
			var sb strings.Builder
			for {
				r := th.call1(c)
				s, ok := r.(string)
				if !ok {
					if r != nil {
						return []Value{nil, "reader function must return a string"}
					}
					break
				}
				if s == "" {
					break
				}
				sb.WriteString(s)
			}
			src = sb.String()
			chunkname = "=(load)"
		default:
			typeErr(th, args, 0, "load", "string")
		}
		if len(args) > 1 && args[1] != nil {
			chunkname = checkStr(th, args, 1, "load")
		}
		mode := optStr(th, args, 2, "load", "bt")
		if !strings.Contains(mode, "t") {
			return []Value{nil, fmt.Sprintf("attempt to load a text chunk (mode is '%s')", mode)}
		}
		var env Value = G
		if len(args) >= 4 {
			env = args[3]
		}
		f, err := th.loadChunk(src, chunkname, env)
		if err != nil {
			return []Value{nil, err.Error()}
		}
		return []Value{f}
	})
	reg(g, "loadfile", func(th *Thread, args []Value) []Value {
		name := optStr(th, args, 0, "loadfile", "")
		src, err := readFileChunk(name)
		if err != nil {
			return []Value{nil, "cannot open " + name}
		}
		var env Value = G
		if len(args) >= 3 {
			env = args[2]
		}
		cn := "@" + name
		if name == "" {
			cn = "=stdin"
		}
		f, err := th.loadChunk(src, cn, env)
		if err != nil {
			return []Value{nil, err.Error()}
		}
		return []Value{f}
	})
	reg(g, "dofile", func(th *Thread, args []Value) []Value {
		name := optStr(th, args, 0, "dofile", "")
		src, err := readFileChunk(name)
		if err != nil {
			th.rtError("cannot open %s", name)
		}
		cn := "@" + name
		if name == "" {
			cn = "=stdin"
		}
		f, err := th.loadChunk(src, cn, G)
		if err != nil {
			th.throw(err.Error())
		}
		return th.call(f, nil)
	})
	openPackage(th)
}

func openPackage(th *Thread) {
	pkg := newTable(0, 8)
	packageTable = pkg
	loadedTable = newTable(0, 16)
	pkg.setStr("loaded", loadedTable)
	pkg.setStr("preload", newTable(0, 0))
	pkg.setStr("path", "./?.lua;./?/init.lua")
	pkg.setStr("cpath", "")
	pkg.setStr("config", "/\n;\n?\n!\n-\n")
	G.setStr("package", pkg)
	loadedTable.setStr("_G", G)
	loadedTable.setStr("package", pkg)

	searchpath := func(th *Thread, name, path, sep, rep string) (string, string) {
		if sep != "" {
			name = strings.ReplaceAll(name, sep, rep)
		}
		var tried strings.Builder
		for _, tmpl := range strings.Split(path, ";") {
			if tmpl == "" {
				continue
			}
			fn := strings.ReplaceAll(tmpl, "?", name)
			if st, err := os.Stat(fn); err == nil && !st.IsDir() {
				return fn, ""
			}
			tried.WriteString("\n\tno file '" + fn + "'")
		}
		return "", tried.String()
	}
	reg(pkg, "searchpath", func(th *Thread, args []Value) []Value {
		name := checkStr(th, args, 0, "searchpath")
		path := checkStr(th, args, 1, "searchpath")
		sep := optStr(th, args, 2, "searchpath", ".")
		rep := optStr(th, args, 3, "searchpath", "/")
		fn, tried := searchpath(th, name, path, sep, rep)
		if fn == "" {
			return []Value{nil, tried}
		}
		return []Value{fn}
	})
	searchers := newTable(2, 0)
	searchers.setInt(1, &GoFunction{name: "searcher_preload", fn: func(th *Thread, args []Value) []Value {
		name := checkStr(th, args, 0, "require")
		if pre, ok := pkg.getStr("preload").(*Table); ok {
			if l := pre.getStr(name); l != nil {
				return []Value{l, ":preload:"}
			}
		}
		return []Value{"\n\tno field package.preload['" + name + "']"}
	}})
	searchers.setInt(2, &GoFunction{name: "searcher_Lua", fn: func(th *Thread, args []Value) []Value {
		name := checkStr(th, args, 0, "require")
		path, ok := pkg.getStr("path").(string)
		if !ok {
			th.rtError("'package.path' must be a string")
		}
		fn, tried := searchpath(th, name, path, ".", "/")
		if fn == "" {
			return []Value{tried}
		}
		src, err := readFileChunk(fn)
		if err != nil {
			th.rtError("error loading module '%s' from file '%s':\n\tcannot read", name, fn)
		}
		f, err := th.loadChunk(src, "@"+fn, G)
		if err != nil {
			th.rtError("error loading module '%s' from file '%s':\n\t%s", name, fn, err.Error())
		}
		return []Value{f, fn}
	}})
	pkg.setStr("searchers", searchers)
	reg(G, "require", func(th *Thread, args []Value) []Value {
		name := checkStr(th, args, 0, "require")
		if v := loadedTable.getStr(name); v != nil {
			return []Value{v}
		}
		srch, ok := pkg.getStr("searchers").(*Table)
		if !ok {
			th.rtError("'package.searchers' must be a table")
		}
		var msg strings.Builder
		for i := int64(1); ; i++ {
			s := srch.getInt(i)
			if s == nil {
				th.rtError("module '%s' not found:%s", name, msg.String())
			}
			r := th.call(s, []Value{name})
			if len(r) > 0 {
				switch l := r[0].(type) {
				case *Closure, *GoFunction:
					var extra Value
					if len(r) > 1 {
						extra = r[1]
					}
					res := th.call(l, []Value{name, extra})
					rv := first(res)
					if rv != nil {
						loadedTable.setStr(name, rv)
					} else if loadedTable.getStr(name) == nil {
						loadedTable.setStr(name, true)
					}
					return []Value{loadedTable.getStr(name), extra}
				case string:
					msg.WriteString(l)
				}
			}
		}
	})
}
