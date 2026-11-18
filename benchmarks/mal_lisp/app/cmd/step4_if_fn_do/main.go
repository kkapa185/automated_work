package main

import "mal/internal/mal"

func READ(s string) mal.Value { return mal.ReadStr(s) }

func EVAL(ast mal.Value, env *mal.Env) mal.Value { return mal.Guard(eval, ast, env) }

func eval(ast mal.Value, env *mal.Env) mal.Value {
	mal.DebugEval(ast, env)
	l, ok := ast.(*mal.List)
	if !ok || len(l.Items) == 0 {
		return mal.EvalLiteral(EVAL, ast, env)
	}
	it := l.Items
	if sym, ok := it[0].(mal.Symbol); ok {
		switch sym {
		case "def!":
			mal.CheckForm("def!", it, 2, 2)
			key, ok := it[1].(mal.Symbol)
			if !ok {
				mal.Throw("def!: first argument must be a symbol")
			}
			return env.Set(key, EVAL(it[2], env))
		case "let*":
			mal.CheckForm("let*", it, 2, 2)
			return EVAL(it[2], mal.LetEnv(EVAL, env, it[1]))
		case "do":
			var res mal.Value = mal.Nil
			for _, f := range it[1:] {
				res = EVAL(f, env)
			}
			return res
		case "if":
			mal.CheckForm("if", it, 2, 3)
			if mal.Truthy(EVAL(it[1], env)) {
				return EVAL(it[2], env)
			}
			if len(it) > 3 {
				return EVAL(it[3], env)
			}
			return mal.Nil
		case "fn*":
			mal.CheckForm("fn*", it, 2, 2)
			return mal.NewClosure(EVAL, env, it[1], it[2])
		}
	}
	f := EVAL(it[0], env)
	return mal.Call(f, mal.EvalAll(EVAL, it[1:], env))
}

func PRINT(v mal.Value) string { return mal.PrStr(v, true) }

var replEnv = mal.NewEnv(nil, nil, nil)

func rep(s string) string { return PRINT(EVAL(READ(s), replEnv)) }

func main() {
	mal.Init()
	for k, f := range mal.Ns() {
		replEnv.Set(mal.Symbol(k), f)
	}
	rep("(def! not (fn* (a) (if a false true)))")
	mal.Repl(rep)
}
