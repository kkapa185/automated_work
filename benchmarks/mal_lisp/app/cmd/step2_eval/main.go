package main

import "mal/internal/mal"

type environ map[mal.Symbol]mal.Value

func READ(s string) mal.Value { return mal.ReadStr(s) }

func evalAst(ast mal.Value, env environ) mal.Value {
	switch a := ast.(type) {
	case mal.Symbol:
		if v, ok := env[a]; ok {
			return v
		}
		mal.Throw("'%s' not found", string(a))
	case *mal.Vector:
		return &mal.Vector{Items: evalAll(a.Items, env), Meta: mal.Nil}
	case *mal.HashMap:
		h := mal.NewHashMap()
		for i, k := range a.Keys {
			h.Set(k, EVAL(a.Vals[i], env))
		}
		return h
	}
	return ast
}

func evalAll(items []mal.Value, env environ) []mal.Value {
	out := make([]mal.Value, len(items))
	for i, it := range items {
		out[i] = EVAL(it, env)
	}
	return out
}

func EVAL(ast mal.Value, env environ) mal.Value {
	l, ok := ast.(*mal.List)
	if !ok || len(l.Items) == 0 {
		return evalAst(ast, env)
	}
	f := EVAL(l.Items[0], env)
	args := evalAll(l.Items[1:], env)
	fn, ok := f.(*mal.Func)
	if !ok {
		mal.Throw("attempt to call non-function: %s", mal.PrStr(f, true))
	}
	return fn.Fn(args)
}

func PRINT(v mal.Value) string { return mal.PrStr(v, true) }

var replEnv = environ{}

func rep(s string) string { return PRINT(EVAL(READ(s), replEnv)) }

func main() {
	for k, f := range mal.Arith() {
		replEnv[mal.Symbol(k)] = f
	}
	mal.Repl(rep)
}
