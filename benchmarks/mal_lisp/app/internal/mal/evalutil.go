package mal

import (
	"fmt"
	"os"
	"runtime/debug"
)

// Evaluator is the EVAL function of a step; helpers below are parameterised by it.
type Evaluator func(ast Value, env *Env) Value

// Init raises the goroutine stack limit so deep non-tail recursion works.
func Init() { debug.SetMaxStack(8 << 30) }

// MaxDepth bounds nested (non-tail) evaluation so runaway recursion becomes a
// catchable mal error instead of a fatal Go stack overflow.
const MaxDepth = 400000

var depth int

// ResetDepth restores the nesting counter after an exception unwound the stack.
func ResetDepth(d int) { depth = d }

// Depth returns the current nesting counter.
func Depth() int { return depth }

// Guard runs one EVAL step while tracking the nesting depth.
func Guard(eval Evaluator, ast Value, env *Env) Value {
	depth++
	if depth > MaxDepth {
		Throw("stack overflow: recursion too deep")
	}
	v := eval(ast, env)
	depth--
	return v
}

// EvalAll evaluates every item.
func EvalAll(eval Evaluator, items []Value, env *Env) []Value {
	out := make([]Value, len(items))
	for i, it := range items {
		out[i] = eval(it, env)
	}
	return out
}

// DebugEval prints "EVAL: ast" when DEBUG-EVAL is set to a truthy value in env.
func DebugEval(ast Value, env *Env) {
	if d, ok := env.Lookup("DEBUG-EVAL"); ok && Truthy(d) {
		fmt.Println("EVAL: " + PrStr(ast, true))
	}
}

// EvalSeq evaluates collection literals and symbols (the "eval_ast" cases)
// and returns ast itself for everything else.
func EvalLiteral(eval Evaluator, ast Value, env *Env) Value {
	switch a := ast.(type) {
	case Symbol:
		return env.Get(a)
	case *Vector:
		return &Vector{Items: EvalAll(eval, a.Items, env), Meta: Nil}
	case *HashMap:
		h := NewHashMap()
		for i, k := range a.Keys {
			h.Set(k, eval(a.Vals[i], env))
		}
		return h
	}
	return ast
}

// LetEnv builds the environment of a let* form from its bindings sequence.
func LetEnv(eval Evaluator, env *Env, bindings Value) *Env {
	binds, ok := Seq(bindings)
	if !ok {
		Throw("let*: bindings must be a list or vector")
	}
	if len(binds)%2 != 0 {
		Throw("let*: odd number of binding forms")
	}
	inner := NewEnv(env, nil, nil)
	for i := 0; i < len(binds); i += 2 {
		k, ok := binds[i].(Symbol)
		if !ok {
			Throw("let*: binding name must be a symbol, got %s", PrStr(binds[i], true))
		}
		inner.Set(k, eval(binds[i+1], inner))
	}
	return inner
}

// NewClosure creates the value of a fn* form.
func NewClosure(eval Evaluator, env *Env, params, body Value) *Func {
	ps, ok := Seq(params)
	if !ok {
		Throw("fn*: parameters must be a list or vector")
	}
	for _, p := range ps {
		if _, ok := p.(Symbol); !ok {
			Throw("fn*: parameter must be a symbol, got %s", PrStr(p, true))
		}
	}
	f := &Func{Env: env, Params: ps, Body: body, Meta: Nil}
	f.Fn = func(args []Value) Value { return eval(body, NewEnv(env, ps, args)) }
	return f
}

// CheckArgs throws unless the form has exactly n arguments after the head
// (or between n and max if max >= 0 and differs).
func CheckForm(name string, items []Value, min, max int) {
	n := len(items) - 1
	if n < min || (max >= 0 && n > max) {
		Throw("%s: wrong number of arguments (%d)", name, n)
	}
}

// Call applies a function value to evaluated arguments.
func Call(f Value, args []Value) Value {
	fn, ok := f.(*Func)
	if !ok {
		Throw("attempt to call non-function: %s", PrStr(f, true))
	}
	return fn.Fn(args)
}

// ReadFile returns the contents of a file or throws.
func ReadFile(name string) string {
	b, err := os.ReadFile(name)
	if err != nil {
		Throw("slurp: cannot read '%s': %v", name, err)
	}
	return string(b)
}

func isSym(v Value, name string) bool { s, ok := v.(Symbol); return ok && string(s) == name }

// startsWith reports whether items begins with the given symbol.
func startsWith(items []Value, name string) bool { return len(items) > 0 && isSym(items[0], name) }

// qqList processes the elements of a list (or vector) for quasiquote,
// building (cons e1 (cons e2 ... ())) / (concat spliced rest) from the right.
func qqList(items []Value) Value {
	var res Value = NewList()
	for i := len(items) - 1; i >= 0; i-- {
		if l, ok := items[i].(*List); ok && startsWith(l.Items, "splice-unquote") {
			if len(l.Items) != 2 {
				Throw("splice-unquote: expected exactly 1 argument")
			}
			res = NewList(Symbol("concat"), l.Items[1], res)
		} else {
			res = NewList(Symbol("cons"), Quasiquote(items[i]), res)
		}
	}
	return res
}

// Quasiquote expands a quasiquoted form into plain list-building code.
func Quasiquote(ast Value) Value {
	switch a := ast.(type) {
	case *List:
		if startsWith(a.Items, "unquote") {
			if len(a.Items) != 2 {
				Throw("unquote: expected exactly 1 argument")
			}
			return a.Items[1]
		}
		return qqList(a.Items)
	case *Vector:
		return NewList(Symbol("vec"), qqList(a.Items))
	case *HashMap, Symbol:
		return NewList(Symbol("quote"), ast)
	}
	return ast
}

// macroFn returns the macro the form calls, if it is a macro call.
func macroFn(ast Value, env *Env) (*Func, []Value, bool) {
	l, ok := ast.(*List)
	if !ok || len(l.Items) == 0 {
		return nil, nil, false
	}
	s, ok := l.Items[0].(Symbol)
	if !ok {
		return nil, nil, false
	}
	v, ok := env.Lookup(s)
	if !ok {
		return nil, nil, false
	}
	f, ok := v.(*Func)
	if !ok || !f.IsMacro {
		return nil, nil, false
	}
	return f, l.Items[1:], true
}

// MacroExpand expands ast while it is a macro call.
func MacroExpand(ast Value, env *Env) Value {
	for {
		f, args, ok := macroFn(ast, env)
		if !ok {
			return ast
		}
		ast = f.Fn(args)
	}
}

// Try evaluates body and reports a thrown exception instead of propagating it.
// The exception value is the thrown mal value, or the message string for
// native errors.
func Try(body func() Value) (res Value, exc Value, caught bool) {
	saved := depth
	defer func() {
		if r := recover(); r != nil {
			depth = saved
			if IsBlank(r) {
				panic(r)
			}
			if me, ok := r.(*MalError); ok {
				exc, caught = me.Val, true
				return
			}
			exc, caught = ErrorText(r), true
		}
	}()
	return body(), nil, false
}

// CatchClause validates (catch* sym body) and returns its parts.
func CatchClause(v Value) (Symbol, Value) {
	l, ok := v.(*List)
	if !ok || !startsWith(l.Items, "catch*") || len(l.Items) != 3 {
		Throw("try*: expected (catch* name body)")
	}
	name, ok := l.Items[1].(Symbol)
	if !ok {
		Throw("catch*: name must be a symbol")
	}
	return name, l.Items[2]
}
