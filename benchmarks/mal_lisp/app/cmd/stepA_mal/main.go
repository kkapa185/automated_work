package main

import (
	"fmt"
	"os"
	"strings"

	"mal/internal/mal"
)

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
			case "quote":
				mal.CheckForm("quote", it, 1, 1)
				return it[1]
			case "quasiquote":
				mal.CheckForm("quasiquote", it, 1, 1)
				ast = mal.Quasiquote(it[1])
				continue
			case "quasiquoteexpand":
				mal.CheckForm("quasiquoteexpand", it, 1, 1)
				return mal.Quasiquote(it[1])
			case "defmacro!":
				mal.CheckForm("defmacro!", it, 2, 2)
				key, ok := it[1].(mal.Symbol)
				if !ok {
					mal.Throw("defmacro!: first argument must be a symbol")
				}
				return env.Set(key, mal.AsMacro(EVAL(it[2], env)))
			case "macroexpand":
				mal.CheckForm("macroexpand", it, 1, 1)
				return mal.MacroExpand(it[1], env)
			case "try*":
				mal.CheckForm("try*", it, 1, 2)
				if len(it) == 2 {
					ast = it[1]
					continue
				}
				name, handler := mal.CatchClause(it[2])
				res, exc, caught := mal.Try(func() mal.Value { return EVAL(it[1], env) })
				if !caught {
					return res
				}
				env = mal.NewEnv(env, []mal.Value{name}, []mal.Value{exc})
				ast = handler
				continue
			}
		}
		f := EVAL(it[0], env)
		if fn, ok := f.(*mal.Func); ok && fn.IsMacro {
			ast = fn.Fn(it[1:])
			continue
		}
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
	replEnv.Set("eval", &mal.Func{Meta: mal.Nil, Fn: func(a []mal.Value) mal.Value {
		if len(a) != 1 {
			mal.Throw("eval: expected 1 argument, got %d", len(a))
		}
		return EVAL(a[0], replEnv)
	}})
	args := []mal.Value{}
	if len(os.Args) > 2 {
		for _, a := range os.Args[2:] {
			args = append(args, a)
		}
	}
	replEnv.Set("*ARGV*", mal.NewList(args...))
	rep(`(def! *host-language* "Go")`)
	rep("(def! not (fn* (a) (if a false true)))")
	rep(`(def! load-file (fn* (f) (eval (read-string (str "(do " (slurp f) "\nnil)")))))`)
	rep(`(defmacro! cond (fn* (& xs) (if (> (count xs) 0) (list 'if (first xs) (if (> (count xs) 1) (nth xs 1) (throw "odd number of forms to cond")) (cons 'cond (rest (rest xs)))))))`)
	if len(os.Args) > 1 {
		out, _ := mal.SafeRep(rep, "(load-file "+mal.PrStr(os.Args[1], true)+")")
		if strings.HasPrefix(out, "Error: ") {
			fmt.Fprintln(os.Stderr, out)
			os.Exit(1)
		}
		return
	}
	rep(`(println (str "Mal [" *host-language* "]"))`)
	mal.Repl(rep)
}
