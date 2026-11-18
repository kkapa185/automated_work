package server

import (
	"bufio"
	"math"
	"strings"
	"testing"
)

func TestGlobMatch(t *testing.T) {
	cases := []struct {
		p, s string
		want bool
	}{
		{"*", "", true}, {"*", "anything", true}, {"h?llo", "hello", true}, {"h?llo", "hllo", false},
		{"h*llo", "hllo", true}, {"h*llo", "heeeello", true}, {"h*llo", "hellp", false},
		{"h[ae]llo", "hallo", true}, {"h[ae]llo", "hillo", false}, {"h[^e]llo", "hallo", true},
		{"h[^e]llo", "hello", false}, {"h[a-c]llo", "hbllo", true}, {"h[c-a]llo", "hbllo", true},
		{`a\*`, "a*", true}, {`a\*`, "ab", false}, {"**a", "ba", true}, {"a*b*c", "aXXbYYc", true},
		{"a*b*c", "aXXbYY", false}, {"", "", true}, {"", "a", false}, {"[", "a", false},
		{`[\]]`, "]", true}, {"*a*a*a*a*a*b", strings.Repeat("a", 30), false},
	}
	for _, c := range cases {
		if got := globMatch([]byte(c.p), []byte(c.s)); got != c.want {
			t.Errorf("globMatch(%q,%q)=%v want %v", c.p, c.s, got, c.want)
		}
	}
}

func TestParseInt64(t *testing.T) {
	ok := map[string]int64{"0": 0, "1": 1, "-1": -1, "9223372036854775807": math.MaxInt64, "-9223372036854775808": math.MinInt64, "123": 123}
	for s, want := range ok {
		if got, g := parseInt64([]byte(s)); !g || got != want {
			t.Errorf("%q => %d,%v", s, got, g)
		}
	}
	for _, s := range []string{"", "-", "+1", "01", "-0", "1.5", " 1", "1 ", "9223372036854775808", "-9223372036854775809", "abc", "0x10", "1e3"} {
		if _, g := parseInt64([]byte(s)); g {
			t.Errorf("%q should be rejected", s)
		}
	}
}

func TestFormatDouble(t *testing.T) {
	cases := map[float64]string{
		1.5: "1.5", 3: "3", 0: "0", -2.25: "-2.25", 100: "100", 1e6: "1000000", 0.1: "0.1",
		math.Inf(1): "inf", math.Inf(-1): "-inf", 1e-7: "1e-07", 123456789012: "123456789012", 1e21: "1e+21",
	}
	for f, want := range cases {
		if got := formatDouble(f); got != want {
			t.Errorf("formatDouble(%v)=%q want %q", f, got, want)
		}
	}
}

func TestParseFloat(t *testing.T) {
	for s, want := range map[string]float64{"1.5": 1.5, "-3": -3, "inf": math.Inf(1), "+inf": math.Inf(1), "-inf": math.Inf(-1), "1e3": 1000, ".5": 0.5} {
		if got, ok := parseFloat([]byte(s)); !ok || got != want {
			t.Errorf("%q => %v,%v", s, got, ok)
		}
	}
	for _, s := range []string{"", "abc", "nan", " 1", "1 ", "1e999", "1.5x"} {
		if _, ok := parseFloat([]byte(s)); ok {
			t.Errorf("%q should be rejected", s)
		}
	}
}

func TestLongDouble(t *testing.T) {
	a, _ := parseLongDouble([]byte("0.1"))
	b, _ := parseLongDouble([]byte("0.2"))
	sum, ok := addLongDouble(a, b)
	if !ok || formatLongDouble(sum) != "0.3" {
		t.Fatalf("0.1+0.2 = %v", formatLongDouble(sum))
	}
	x, _ := parseLongDouble([]byte("5.0e3"))
	if got := formatLongDouble(x); got != "5000" {
		t.Fatal(got)
	}
}

func TestReadCommand(t *testing.T) {
	r := bufio.NewReader(strings.NewReader("*3\r\n$3\r\nSET\r\n$1\r\nk\r\n$4\r\na\r\nb\r\nPING\r\n\r\nGET   x\n"))
	args, err := readCommand(r)
	if err != nil || len(args) != 3 || string(args[2]) != "a\r\nb" {
		t.Fatalf("%q %v", args, err)
	}
	args, _ = readCommand(r)
	if len(args) != 1 || string(args[0]) != "PING" {
		t.Fatalf("%q", args)
	}
	if args, err = readCommand(r); args != nil || err != nil {
		t.Fatalf("blank line: %q %v", args, err)
	}
	args, _ = readCommand(r)
	if len(args) != 2 || string(args[1]) != "x" {
		t.Fatalf("%q", args)
	}
}

func TestSplitArgs(t *testing.T) {
	got, ok := splitArgs([]byte(`set "a\x41 b" 'it\'s' plain ""`))
	want := []string{"set", "aA b", "it's", "plain", ""}
	if !ok || len(got) != len(want) {
		t.Fatalf("%q %v", got, ok)
	}
	for i := range want {
		if string(got[i]) != want[i] {
			t.Errorf("arg %d = %q want %q", i, got[i], want[i])
		}
	}
	for _, bad := range []string{`"abc`, `'abc`, `"a"b`, `'a'b`} {
		if _, ok := splitArgs([]byte(bad)); ok {
			t.Errorf("%q should fail", bad)
		}
	}
}

// The classic exponential-backtracking shapes must finish instantly.
func TestGlobNoBacktrackingBlowup(t *testing.T) {
	long := []byte(strings.Repeat("a", 5000))
	pats := []string{
		strings.Repeat("a*", 40) + "b",
		strings.Repeat("*a", 40) + "b",
		strings.Repeat("*", 2000) + "b",
		strings.Repeat("a?*", 30) + "b",
		strings.Repeat("[ab]*", 30) + "c",
	}
	for _, p := range pats {
		if globMatch([]byte(p), long) {
			t.Errorf("%.20s... should not match", p)
		}
	}
	if !globMatch([]byte(strings.Repeat("a*", 40)), long) {
		t.Error("should match")
	}
	if !globMatch([]byte("*a*b*c*"), []byte("xxaxxbxxcxx")) || globMatch([]byte("*a*b*c*"), []byte("xxcxxbxxaxx")) {
		t.Error("ordering of star segments")
	}
}
