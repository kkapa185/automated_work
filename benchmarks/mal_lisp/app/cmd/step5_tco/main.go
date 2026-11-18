package main

import "mal/internal/mal"

func READ(s string) mal.Value { return mal.ReadStr(s) }

func EVAL(ast mal.Value, env *mal.Env) mal.Value { return mal.Guard(eval, ast, env) }

func eval(ast mal.Value, env *mal.Env) mal.Value {
	for {
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
				env = mal.LetEnv(EVAL, env, it[1])
				ast = it[2]
				continue
			case "do":
				if len(it) == 1 {
					return mal.Nil
				}
				for _, f := range it[1 : len(it)-1] {
					EVAL(f, env)
				}
				ast = it[len(it)-1]
				continue
			case "if":
				mal.CheckForm("if", it, 2, 3)
				if mal.Truthy(EVAL(it[1], env)) {
					ast = it[2]
				} else if len(it) > 3 {
					ast = it[3]
				} else {
					return mal.Nil
				}
				continue
			case "fn*":
				mal.CheckForm("fn*", it, 2, 2)
				return mal.NewClosure(EVAL, env, it[1], it[2])
			}
		}
		f := EVAL(it[0], env)
		args := mal.EvalAll(EVAL, it[1:], env)
		if fn, ok := f.(*mal.Func); ok && fn.Env != nil {
			env = mal.NewEnv(fn.Env, fn.Params, args)
			ast = fn.Body
			continue
		}
		return mal.Call(f, args)
	}
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
