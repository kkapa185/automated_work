package mal

import (
	"time"
)

func seqArg(name string, v Value) []Value {
	items, ok := Seq(v)
	if !ok {
		Throw("%s: argument must be a list or vector, got %s", name, PrStr(v, true))
	}
	return items
}

func mapArg(name string, v Value) *HashMap {
	h, ok := v.(*HashMap)
	if !ok {
		Throw("%s: argument must be a hash-map, got %s", name, PrStr(v, true))
	}
	return h
}

func checkKeyArg(name string, k Value) {
	switch k.(type) {
	case string, Keyword:
	default:
		Throw("%s: key must be a string or keyword, got %s", name, PrStr(k, true))
	}
}

// metaOf returns the metadata of v (nil for kinds without metadata).
func metaOf(v Value) Value {
	switch x := v.(type) {
	case *List:
		return x.Meta
	case *Vector:
		return x.Meta
	case *HashMap:
		return x.Meta
	case *Func:
		return x.Meta
	case *Atom:
		return x.Meta
	}
	Throw("meta: unsupported type %s", PrStr(v, true))
	return nil
}

// withMeta returns a copy of v carrying meta; the original is untouched.
func withMeta(v, meta Value) Value {
	switch x := v.(type) {
	case *List:
		return &List{Items: x.Items, Meta: meta}
	case *Vector:
		return &Vector{Items: x.Items, Meta: meta}
	case *HashMap:
		h := x.Copy()
		h.Meta = meta
		return h
	case *Func:
		c := *x
		c.Meta = meta
		return &c
	}
	Throw("with-meta: unsupported type %s", PrStr(v, true))
	return nil
}

// AsMacro returns a copy of the user function f flagged as a macro.
func AsMacro(f Value) Value {
	fn, ok := f.(*Func)
	if !ok || fn.Env == nil {
		Throw("defmacro!: value must be a function created with fn*, got %s", PrStr(f, true))
	}
	c := *fn
	c.IsMacro = true
	return &c
}

// AddCore2 adds the sequence, hash-map, predicate, exception and metadata
// functions (steps 7 - A) to ns.
func AddCore2(ns map[string]*Func) {
	def := func(name string, f func(a []Value) Value) { ns[name] = nativeFn(f) }

	def("cons", func(a []Value) Value {
		argc("cons", a, 2)
		rest := seqArg("cons", a[1])
		return NewList(append([]Value{a[0]}, rest...)...)
	})
	def("concat", func(a []Value) Value {
		out := []Value{}
		for _, v := range a {
			out = append(out, seqArg("concat", v)...)
		}
		return NewList(out...)
	})
	def("vec", func(a []Value) Value {
		argc("vec", a, 1)
		if v, ok := a[0].(*Vector); ok {
			return v
		}
		return NewVector(append([]Value{}, seqArg("vec", a[0])...)...)
	})
	def("nth", func(a []Value) Value {
		argc("nth", a, 2)
		items := seqArg("nth", a[0])
		i, ok := a[1].(int)
		if !ok {
			Throw("nth: index must be a number")
		}
		if i < 0 || i >= len(items) {
			Throw("nth: index out of range")
		}
		return items[i]
	})
	def("first", func(a []Value) Value {
		argc("first", a, 1)
		if a[0] == Nil {
			return Nil
		}
		items := seqArg("first", a[0])
		if len(items) == 0 {
			return Nil
		}
		return items[0]
	})
	def("rest", func(a []Value) Value {
		argc("rest", a, 1)
		if a[0] == Nil {
			return NewList()
		}
		items := seqArg("rest", a[0])
		if len(items) == 0 {
			return NewList()
		}
		return NewList(append([]Value{}, items[1:]...)...)
	})

	def("throw", func(a []Value) Value { argc("throw", a, 1); panic(&MalError{Val: a[0]}) })
	def("apply", func(a []Value) Value {
		argcMin("apply", a, 2)
		args := append([]Value{}, a[1:len(a)-1]...)
		args = append(args, seqArg("apply", a[len(a)-1])...)
		return Call(a[0], args)
	})
	def("map", func(a []Value) Value {
		argc("map", a, 2)
		items := seqArg("map", a[1])
		out := make([]Value, len(items))
		for i, it := range items {
			out[i] = Call(a[0], []Value{it})
		}
		return NewList(out...)
	})

	pred := func(name string, f func(v Value) bool) {
		def(name, func(a []Value) Value { argc(name, a, 1); return f(a[0]) })
	}
	pred("nil?", func(v Value) bool { return v == Nil })
	pred("true?", func(v Value) bool { b, ok := v.(bool); return ok && b })
	pred("false?", func(v Value) bool { b, ok := v.(bool); return ok && !b })
	pred("symbol?", func(v Value) bool { _, ok := v.(Symbol); return ok })
	pred("keyword?", func(v Value) bool { _, ok := v.(Keyword); return ok })
	pred("vector?", func(v Value) bool { _, ok := v.(*Vector); return ok })
	pred("map?", func(v Value) bool { _, ok := v.(*HashMap); return ok })
	pred("sequential?", func(v Value) bool { _, ok := Seq(v); return ok })
	pred("string?", func(v Value) bool { _, ok := v.(string); return ok })
	pred("number?", func(v Value) bool { _, ok := v.(int); return ok })
	pred("fn?", func(v Value) bool { f, ok := v.(*Func); return ok && !f.IsMacro })
	pred("macro?", func(v Value) bool { f, ok := v.(*Func); return ok && f.IsMacro })

	def("symbol", func(a []Value) Value {
		argc("symbol", a, 1)
		if s, ok := a[0].(Symbol); ok {
			return s
		}
		s, ok := a[0].(string)
		if !ok {
			Throw("symbol: argument must be a string")
		}
		return Symbol(s)
	})
	def("keyword", func(a []Value) Value {
		argc("keyword", a, 1)
		if k, ok := a[0].(Keyword); ok {
			return k
		}
		s, ok := a[0].(string)
		if !ok {
			Throw("keyword: argument must be a string")
		}
		return Keyword(s)
	})
	def("vector", func(a []Value) Value { return NewVector(append([]Value{}, a...)...) })

	def("hash-map", func(a []Value) Value {
		if len(a)%2 != 0 {
			Throw("hash-map: odd number of arguments")
		}
		h := NewHashMap()
		for i := 0; i < len(a); i += 2 {
			checkKeyArg("hash-map", a[i])
			h.Set(a[i], a[i+1])
		}
		return h
	})
	def("assoc", func(a []Value) Value {
		argcMin("assoc", a, 1)
		if (len(a)-1)%2 != 0 {
			Throw("assoc: odd number of key/value arguments")
		}
		h := mapArg("assoc", a[0]).Copy()
		for i := 1; i < len(a); i += 2 {
			checkKeyArg("assoc", a[i])
			h.Set(a[i], a[i+1])
		}
		return h
	})
	def("dissoc", func(a []Value) Value {
		argcMin("dissoc", a, 1)
		return mapArg("dissoc", a[0]).Without(a[1:])
	})
	def("get", func(a []Value) Value {
		argc("get", a, 2)
		if a[0] == Nil {
			return Nil
		}
		if v, ok := mapArg("get", a[0]).Get(a[1]); ok {
			return v
		}
		return Nil
	})
	def("contains?", func(a []Value) Value {
		argc("contains?", a, 2)
		if a[0] == Nil {
			return false
		}
		_, ok := mapArg("contains?", a[0]).Get(a[1])
		return ok
	})
	def("keys", func(a []Value) Value {
		argc("keys", a, 1)
		return NewList(append([]Value{}, mapArg("keys", a[0]).Keys...)...)
	})
	def("vals", func(a []Value) Value {
		argc("vals", a, 1)
		return NewList(append([]Value{}, mapArg("vals", a[0]).Vals...)...)
	})

	def("readline", func(a []Value) Value {
		argc("readline", a, 1)
		p, ok := a[0].(string)
		if !ok {
			Throw("readline: prompt must be a string")
		}
		line, ok := Readline(p)
		if !ok {
			return Nil
		}
		return line
	})
	def("time-ms", func(a []Value) Value { return int(time.Now().UnixMilli()) })
	def("meta", func(a []Value) Value { argc("meta", a, 1); return metaOf(a[0]) })
	def("with-meta", func(a []Value) Value { argc("with-meta", a, 2); return withMeta(a[0], a[1]) })
	def("conj", func(a []Value) Value {
		argcMin("conj", a, 1)
		switch c := a[0].(type) {
		case *List:
			items := make([]Value, 0, len(c.Items)+len(a)-1)
			for i := len(a) - 1; i >= 1; i-- {
				items = append(items, a[i])
			}
			return NewList(append(items, c.Items...)...)
		case *Vector:
			return NewVector(append(append([]Value{}, c.Items...), a[1:]...)...)
		}
		if a[0] == Nil {
			items := make([]Value, 0, len(a)-1)
			for i := len(a) - 1; i >= 1; i-- {
				items = append(items, a[i])
			}
			return NewList(items...)
		}
		Throw("conj: first argument must be a list or vector")
		return nil
	})
	def("seq", func(a []Value) Value {
		argc("seq", a, 1)
		switch c := a[0].(type) {
		case *List:
			if len(c.Items) == 0 {
				return Nil
			}
			return c
		case *Vector:
			if len(c.Items) == 0 {
				return Nil
			}
			return NewList(append([]Value{}, c.Items...)...)
		case string:
			if c == "" {
				return Nil
			}
			out := []Value{}
			for _, r := range c {
				out = append(out, string(r))
			}
			return NewList(out...)
		}
		if a[0] == Nil {
			return Nil
		}
		Throw("seq: argument must be a list, vector, string or nil")
		return nil
	})
}
