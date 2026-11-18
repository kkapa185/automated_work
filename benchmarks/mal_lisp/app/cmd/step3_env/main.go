package main

import (
	"fmt"

	"mal/internal/mal"
)

func READ(s string) mal.Value { return mal.ReadStr(s) }

func evalAll(items []mal.Value, env *mal.Env) []mal.Value {
	out := make([]mal.Value, len(items))
	for i, it := range items {
		out[i] = EVAL(it, env)
	}
	return out
}

func EVAL(ast mal.Value, env *mal.Env) mal.Value {
	if d, ok := env.Lookup("DEBUG-EVAL"); ok && mal.Truthy(d) {
		fmt.Println("EVAL: " + mal.PrStr(ast, true))
	}
	switch a := ast.(type) {
	case mal.Symbol:
		return env.Get(a)
	case *mal.Vector:
		return &mal.Vector{Items: evalAll(a.Items, env), Meta: mal.Nil}
	case *mal.HashMap:
		h := mal.NewHashMap()
		for i, k := range a.Keys {
			h.Set(k, EVAL(a.Vals[i], env))
		}
		return h
	case *mal.List:
		if len(a.Items) == 0 {
			return ast
		}
		if sym, ok := a.Items[0].(mal.Symbol); ok {
			switch sym {
			case "def!":
				if len(a.Items) != 3 {
					mal.Throw("def!: expected 2 arguments")
				}
				key, ok := a.Items[1].(mal.Symbol)
				if !ok {
					mal.Throw("def!: first argument must be a symbol")
				}
				return env.Set(key, EVAL(a.Items[2], env))
			case "let*":
				if len(a.Items) != 3 {
					mal.Throw("let*: expected bindings and a body")
				}
				binds, ok := mal.Seq(a.Items[1])
				if !ok {
					mal.Throw("let*: bindings must be a list or vector")
				}
				if len(binds)%2 != 0 {
					mal.Throw("let*: odd number of binding forms")
				}
				inner := mal.NewEnv(env, nil, nil)
				for i := 0; i < len(binds); i += 2 {
					k, ok := binds[i].(mal.Symbol)
					if !ok {
						mal.Throw("let*: binding name must be a symbol")
					}
					inner.Set(k, EVAL(binds[i+1], inner))
				}
				return EVAL(a.Items[2], inner)
			}
		}
		f := EVAL(a.Items[0], env)
		args := evalAll(a.Items[1:], env)
		fn, ok := f.(*mal.Func)
		if !ok {
			mal.Throw("attempt to call non-function: %s", mal.PrStr(f, true))
		}
		return fn.Fn(args)
	}
	return ast
}

func PRINT(v mal.Value) string { return mal.PrStr(v, true) }

var replEnv = mal.NewEnv(nil, nil, nil)

func rep(s string) string { return PRINT(EVAL(READ(s), replEnv)) }

func main() {
	for k, f := range mal.Arith() {
		replEnv.Set(mal.Symbol(k), f)
	}
	mal.Repl(rep)
}
