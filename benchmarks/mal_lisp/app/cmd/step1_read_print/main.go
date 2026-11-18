package main

import "mal/internal/mal"

func READ(s string) mal.Value      { return mal.ReadStr(s) }
func EVAL(ast mal.Value) mal.Value { return ast }
func PRINT(v mal.Value) string     { return mal.PrStr(v, true) }
func rep(s string) string          { return PRINT(EVAL(READ(s))) }

func main() { mal.Repl(rep) }
