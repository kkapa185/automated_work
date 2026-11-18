package mal

import (
	"fmt"
	"strings"
)

func nativeFn(f func(a []Value) Value) *Func { return &Func{Fn: f, Meta: Nil} }

func argc(name string, a []Value, n int) {
	if len(a) != n {
		Throw("%s: expected %d argument(s), got %d", name, n, len(a))
	}
}

func argcMin(name string, a []Value, n int) {
	if len(a) < n {
		Throw("%s: expected at least %d argument(s), got %d", name, n, len(a))
	}
}

func num2(name string, a []Value) (int, int) {
	argc(name, a, 2)
	x, ok1 := a[0].(int)
	y, ok2 := a[1].(int)
	if !ok1 || !ok2 {
		Throw("%s: arguments must be numbers", name)
	}
	return x, y
}

func joinStr(a []Value, readably bool, sep string) string {
	parts := make([]string, len(a))
	for i, v := range a {
		parts[i] = PrStr(v, readably)
	}
	return strings.Join(parts, sep)
}

// ReadStringValue implements read-string: a blank string reads as nil.
func ReadStringValue(s string) (v Value) {
	defer func() {
		if r := recover(); r != nil {
			if IsBlank(r) {
				v = Nil
				return
			}
			panic(r)
		}
	}()
	return ReadStr(s)
}

// Ns returns the core namespace implemented in Go.
func Ns() map[string]*Func {
	ns := map[string]*Func{}
	def := func(name string, f func(a []Value) Value) { ns[name] = nativeFn(f) }

	def("+", func(a []Value) Value { x, y := num2("+", a); return x + y })
	def("-", func(a []Value) Value { x, y := num2("-", a); return x - y })
	def("*", func(a []Value) Value { x, y := num2("*", a); return x * y })
	def("/", func(a []Value) Value {
		x, y := num2("/", a)
		if y == 0 {
			Throw("/: division by zero")
		}
		return x / y
	})
	def("<", func(a []Value) Value { x, y := num2("<", a); return x < y })
	def("<=", func(a []Value) Value { x, y := num2("<=", a); return x <= y })
	def(">", func(a []Value) Value { x, y := num2(">", a); return x > y })
	def(">=", func(a []Value) Value { x, y := num2(">=", a); return x >= y })
	def("=", func(a []Value) Value { argc("=", a, 2); return Equal(a[0], a[1]) })

	def("pr-str", func(a []Value) Value { return joinStr(a, true, " ") })
	def("str", func(a []Value) Value { return joinStr(a, false, "") })
	def("prn", func(a []Value) Value { fmt.Println(joinStr(a, true, " ")); return Nil })
	def("println", func(a []Value) Value { fmt.Println(joinStr(a, false, " ")); return Nil })

	def("list", func(a []Value) Value { return NewList(append([]Value{}, a...)...) })
	def("list?", func(a []Value) Value { argc("list?", a, 1); _, ok := a[0].(*List); return ok })
	def("empty?", func(a []Value) Value {
		argc("empty?", a, 1)
		items, ok := Seq(a[0])
		if !ok {
			Throw("empty?: argument must be a list or vector")
		}
		return len(items) == 0
	})
	def("count", func(a []Value) Value {
		argc("count", a, 1)
		if a[0] == Nil {
			return 0
		}
		items, ok := Seq(a[0])
		if !ok {
			Throw("count: argument must be a list or vector")
		}
		return len(items)
	})

	def("read-string", func(a []Value) Value {
		argc("read-string", a, 1)
		s, ok := a[0].(string)
		if !ok {
			Throw("read-string: argument must be a string")
		}
		return ReadStringValue(s)
	})
	def("slurp", func(a []Value) Value {
		argc("slurp", a, 1)
		s, ok := a[0].(string)
		if !ok {
			Throw("slurp: argument must be a string")
		}
		return ReadFile(s)
	})

	def("atom", func(a []Value) Value { argc("atom", a, 1); return &Atom{Val: a[0], Meta: Nil} })
	def("atom?", func(a []Value) Value { argc("atom?", a, 1); _, ok := a[0].(*Atom); return ok })
	atomArg := func(name string, v Value) *Atom {
		at, ok := v.(*Atom)
		if !ok {
			Throw("%s: argument must be an atom", name)
		}
		return at
	}
	def("deref", func(a []Value) Value { argc("deref", a, 1); return atomArg("deref", a[0]).Val })
	def("reset!", func(a []Value) Value {
		argc("reset!", a, 2)
		atomArg("reset!", a[0]).Val = a[1]
		return a[1]
	})
	def("swap!", func(a []Value) Value {
		argcMin("swap!", a, 2)
		at := atomArg("swap!", a[0])
		args := append([]Value{at.Val}, a[2:]...)
		at.Val = Call(a[1], args)
		return at.Val
	})
	AddCore2(ns)
	return ns
}
