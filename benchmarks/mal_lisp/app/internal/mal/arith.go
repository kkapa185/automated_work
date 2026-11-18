package mal

// Arith returns the four numeric functions + - * / used by steps 2-3
// (core.go reuses them from step 4 on).
func Arith() map[string]*Func {
	num := func(name string, args []Value) (int, int) {
		if len(args) != 2 {
			Throw("%s: expected 2 arguments, got %d", name, len(args))
		}
		a, ok1 := args[0].(int)
		b, ok2 := args[1].(int)
		if !ok1 || !ok2 {
			Throw("%s: arguments must be numbers", name)
		}
		return a, b
	}
	return map[string]*Func{
		"+": {Fn: func(a []Value) Value { x, y := num("+", a); return x + y }, Meta: Nil},
		"-": {Fn: func(a []Value) Value { x, y := num("-", a); return x - y }, Meta: Nil},
		"*": {Fn: func(a []Value) Value { x, y := num("*", a); return x * y }, Meta: Nil},
		"/": {Fn: func(a []Value) Value {
			x, y := num("/", a)
			if y == 0 {
				Throw("/: division by zero")
			}
			return x / y
		}, Meta: Nil},
	}
}
