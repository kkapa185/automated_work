package mal

import (
	"strings"
	"testing"
)

func rt(s string) string { return PrStr(ReadStr(s), true) }

func TestReadPrintRoundTrip(t *testing.T) {
	// Expected strings are written by hand from the guide's definition.
	cases := map[string]string{
		"123":              "123",
		"  -45  ":          "-45",
		"(+ 2   (* 3 4))":  "(+ 2 (* 3 4))",
		"[1 , 2]":          "[1 2]",
		"{\"a\" 1 :b [2]}": "{\"a\" 1 :b [2]}",
		"nil":              "nil",
		"true":             "true",
		"\"a\\nb\"":        "\"a\\nb\"",
		"\"q\\\"q\"":       "\"q\\\"q\"",
		"'a":               "(quote a)",
		"`(a ~b ~@c)":      "(quasiquote (a (unquote b) (splice-unquote c)))",
		"@x":               "(deref x)",
		"^{\"a\" 1} [1]":   "(with-meta [1] {\"a\" 1})",
		":kw":              ":kw",
		"()":               "()",
		"(1 ;comment\n 2)": "(1 2)",
	}
	for in, want := range cases {
		if got := rt(in); got != want {
			t.Errorf("%q: got %q want %q", in, got, want)
		}
	}
}

func TestNonReadablePrint(t *testing.T) {
	if got := PrStr(ReadStr(`"a\nb\"c"`), false); got != "a\nb\"c" {
		t.Errorf("got %q", got)
	}
}

func catch(f func()) (msg string) {
	defer func() {
		if r := recover(); r != nil {
			msg = ErrorText(r)
		}
	}()
	f()
	return ""
}

func TestReaderErrors(t *testing.T) {
	for _, in := range []string{"(1 2", "[1", "{\"a\"", "\"abc", "\"abc\\\"", ")", "{1}"} {
		msg := catch(func() { ReadStr(in) })
		if msg == "" {
			t.Errorf("%q: expected error", in)
		}
	}
	if m := catch(func() { ReadStr("(1") }); !strings.Contains(m, "EOF") {
		t.Errorf("message %q", m)
	}
}

func TestBlank(t *testing.T) {
	for _, in := range []string{"", "   ", "; hi", " , "} {
		func() {
			defer func() {
				if !IsBlank(recover()) {
					t.Errorf("%q: not blank", in)
				}
			}()
			ReadStr(in)
		}()
	}
}

func TestEnv(t *testing.T) {
	outer := NewEnv(nil, nil, nil)
	outer.Set("a", 1)
	inner := NewEnv(outer, []Value{Symbol("x"), Symbol("&"), Symbol("r")}, []Value{10, 20, 30})
	if inner.Get("a") != 1 || inner.Get("x") != 10 {
		t.Fatal("lookup")
	}
	if got := PrStr(inner.Get("r"), true); got != "(20 30)" {
		t.Errorf("rest: %s", got)
	}
	if m := catch(func() { inner.Get("zz") }); m != "'zz' not found" {
		t.Errorf("msg %q", m)
	}
}

func TestEqualAndHashMap(t *testing.T) {
	if !Equal(ReadStr("(1 [2])"), ReadStr("[1 (2)]")) {
		t.Error("list/vector equality")
	}
	if Equal(ReadStr(`"a"`), ReadStr(":a")) {
		t.Error("string vs keyword")
	}
	if !Equal(ReadStr(`{"a" 1 "b" 2}`), ReadStr(`{"b" 2 "a" 1}`)) {
		t.Error("map equality")
	}
}
