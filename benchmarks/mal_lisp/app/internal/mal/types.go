// Package mal holds the pieces shared by every step: types, reader,
// printer, environments, the REPL loop and (from step 4) the core namespace.
package mal

import "fmt"

// Value is any mal value. Concrete representations:
//
//	NilT (the Nil singleton), bool, int, string, Symbol, Keyword,
//	*List, *Vector, *HashMap, *Func, *Atom
type Value interface{}

type nilT struct{}

// Nil is the mal nil value.
var Nil Value = nilT{}

// Symbol is a mal symbol.
type Symbol string

// Keyword is a mal keyword, stored without the leading colon.
type Keyword string

// List is a mal list. Meta is Nil or a hash-map.
type List struct {
	Items []Value
	Meta  Value
}

// Vector is a mal vector.
type Vector struct {
	Items []Value
	Meta  Value
}

// Func is a function value: either native (Fn only) or a user closure.
type Func struct {
	Fn      func(args []Value) Value
	Env     *Env    // closure environment (user functions)
	Params  []Value // parameter symbols (user functions)
	Body    Value   // body (user functions)
	IsMacro bool
	Meta    Value
}

// Atom is a mutable reference cell.
type Atom struct {
	Val  Value
	Meta Value
}

// MalError is the panic payload for every mal exception.
type MalError struct{ Val Value }

func (e *MalError) Error() string { return PrStr(e.Val, false) }

// Throw raises a mal exception carrying a formatted string.
func Throw(format string, args ...interface{}) {
	panic(&MalError{Val: fmt.Sprintf(format, args...)})
}

// NewList builds a list from items.
func NewList(items ...Value) *List { return &List{Items: items, Meta: Nil} }

// NewVector builds a vector from items.
func NewVector(items ...Value) *Vector { return &Vector{Items: items, Meta: Nil} }

// IsSeq reports whether v is a list or vector, returning its items.
func Seq(v Value) ([]Value, bool) {
	switch s := v.(type) {
	case *List:
		return s.Items, true
	case *Vector:
		return s.Items, true
	}
	return nil, false
}

// Truthy: everything except nil and false.
func Truthy(v Value) bool {
	if v == Nil {
		return false
	}
	if b, ok := v.(bool); ok {
		return b
	}
	return true
}

// HashMap is an insertion-ordered map with string/keyword keys.
type HashMap struct {
	Keys []Value
	Vals []Value
	idx  map[Value]int
	Meta Value
}

// NewHashMap returns an empty hash-map.
func NewHashMap() *HashMap { return &HashMap{idx: map[Value]int{}, Meta: Nil} }

func checkKey(k Value) {
	switch k.(type) {
	case string, Keyword:
	default:
		Throw("hash-map key must be a string or keyword, got %s", PrStr(k, true))
	}
}

// Get returns the value for k.
func (h *HashMap) Get(k Value) (Value, bool) {
	i, ok := h.idx[k]
	if !ok {
		return nil, false
	}
	return h.Vals[i], true
}

// Set mutates h; only used while constructing a fresh map.
func (h *HashMap) Set(k, v Value) {
	checkKey(k)
	if i, ok := h.idx[k]; ok {
		h.Vals[i] = v
		return
	}
	h.idx[k] = len(h.Keys)
	h.Keys = append(h.Keys, k)
	h.Vals = append(h.Vals, v)
}

// Copy returns a shallow copy (metadata is kept).
func (h *HashMap) Copy() *HashMap {
	n := &HashMap{
		Keys: append([]Value(nil), h.Keys...),
		Vals: append([]Value(nil), h.Vals...),
		idx:  make(map[Value]int, len(h.idx)),
		Meta: h.Meta,
	}
	for k, i := range h.idx {
		n.idx[k] = i
	}
	return n
}

// Without returns a copy lacking the given keys.
func (h *HashMap) Without(keys []Value) *HashMap {
	drop := map[Value]bool{}
	for _, k := range keys {
		drop[k] = true
	}
	n := NewHashMap()
	n.Meta = h.Meta
	for i, k := range h.Keys {
		if !drop[k] {
			n.Set(k, h.Vals[i])
		}
	}
	return n
}

// Equal implements mal `=`: lists and vectors compare element-wise.
func Equal(a, b Value) bool {
	as, aok := Seq(a)
	bs, bok := Seq(b)
	if aok || bok {
		if !(aok && bok) || len(as) != len(bs) {
			return false
		}
		for i := range as {
			if !Equal(as[i], bs[i]) {
				return false
			}
		}
		return true
	}
	if ah, ok := a.(*HashMap); ok {
		bh, ok := b.(*HashMap)
		if !ok || len(ah.Keys) != len(bh.Keys) {
			return false
		}
		for i, k := range ah.Keys {
			bv, ok := bh.Get(k)
			if !ok || !Equal(ah.Vals[i], bv) {
				return false
			}
		}
		return true
	}
	switch a.(type) {
	case *Func, *Atom:
		return a == b
	}
	return a == b
}
