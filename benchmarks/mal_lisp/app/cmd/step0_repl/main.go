package main

import "mal/internal/mal"

func READ(s string) string  { return s }
func EVAL(s string) string  { return s }
func PRINT(s string) string { return s }
func rep(s string) string   { return PRINT(EVAL(READ(s))) }

func main() { mal.Repl(rep) }
