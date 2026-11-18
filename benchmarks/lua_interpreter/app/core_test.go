package main

import (
	"math"
	"testing"
)

func TestFloatFormatting(t *testing.T) {
	cases := []struct {
		f float64
		s string
	}{
		{1, "1.0"}, {math.Copysign(0, -1), "-0.0"}, {0.1, "0.1"}, {1e15, "1e+15"}, {1e14, "1e+14"},
		{123456.789, "123456.789"}, {1.0 / 3, "0.33333333333333"}, {2e-5, "2e-05"},
		{math.Inf(1), "inf"}, {math.Inf(-1), "-inf"}, {3.14159265358979, "3.1415926535898"},
		{1e100, "1e+100"}, {255.0, "255.0"}, {9007199254740992, "9.007199254741e+15"},
	}
	for _, c := range cases {
		if got := fmtFloat(c.f); got != c.s {
			t.Errorf("fmtFloat(%v) = %q, want %q", c.f, got, c.s)
		}
	}
	if got := fmtG(0.0001, 6, false); got != "0.0001" {
		t.Errorf("fmtG small: %q", got)
	}
	if got := fmtG(100000, 6, false); got != "100000" {
		t.Errorf("fmtG: %q", got)
	}
	if got := fmtG(1000000, 6, false); got != "1e+06" {
		t.Errorf("fmtG: %q", got)
	}
}

func TestStr2Number(t *testing.T) {
	cases := []struct {
		s  string
		v  Value
		ok bool
	}{
		{"10", int64(10), true}, {" 10 ", int64(10), true}, {"-5", int64(-5), true},
		{"0x10", int64(16), true}, {"0xffffffffffffffff", int64(-1), true},
		{"1.5", 1.5, true}, {".5", 0.5, true}, {"5.", 5.0, true}, {"1e2", 100.0, true},
		{"0x1p4", 16.0, true}, {"0x.8", 0.5, true}, {"0xA.8", 10.5, true},
		{"9223372036854775807", int64(math.MaxInt64), true},
		{"-9223372036854775808", int64(math.MinInt64), true},
		{"9223372036854775808", 9223372036854775808.0, true},
		{"", nil, false}, {"abc", nil, false}, {"1e", nil, false}, {"0x", nil, false},
		{"1 2", nil, false}, {"inf", nil, false}, {"nan", nil, false}, {"--1", nil, false},
	}
	for _, c := range cases {
		v, ok := str2number(c.s)
		if ok != c.ok || (ok && v != c.v) {
			t.Errorf("str2number(%q) = %v,%v want %v,%v", c.s, v, ok, c.v, c.ok)
		}
	}
}

func lexAll(t *testing.T, src string) []Token {
	lx := newLexer(src, "t")
	var out []Token
	for {
		tk := lx.next()
		out = append(out, tk)
		if tk.kind == tkEOF {
			return out
		}
	}
}

func TestLexerStrings(t *testing.T) {
	cases := map[string]string{
		`"a\nb"`:           "a\nb",
		`'\65\066\x41'`:    "ABA",
		`"\u{48}\u{20AC}"`: "H\xe2\x82\xac",
		"[[\nabc]]":        "abc",
		"[==[a]]b]==]":     "a]]b",
		"\"a\\z  \n  b\"":  "ab",
		`"\\\"\'"`:         "\\\"'",
		"\"x\\\ny\"":       "x\ny",
		`"\u{7FFFFFFF}"`:   "\xfd\xbf\xbf\xbf\xbf\xbf",
	}
	for src, want := range cases {
		toks := lexAll(t, src)
		if toks[0].kind != tkString || toks[0].s != want {
			t.Errorf("lex %q = %q, want %q", src, toks[0].s, want)
		}
	}
}

func TestLexerTokens(t *testing.T) {
	toks := lexAll(t, "a // b .. c ... == ~= <= >= << >> :: 3 0x10 1e2 -- comment\n--[[ long\ncomment ]] end")
	kinds := []int{tkName, tkIdiv, tkName, tkConcat, tkName, tkDots, tkEq, tkNe, tkLe, tkGe, tkShl, tkShr, tkDbColon,
		tkNumber, tkNumber, tkNumber, tkEnd, tkEOF}
	if len(toks) != len(kinds) {
		t.Fatalf("got %d tokens, want %d", len(toks), len(kinds))
	}
	for i, k := range kinds {
		if toks[i].kind != k {
			t.Errorf("token %d kind %d want %d", i, toks[i].kind, k)
		}
	}
	if toks[len(toks)-2].line != 3 {
		t.Errorf("line tracking: %d", toks[len(toks)-2].line)
	}
	if v := toks[13].n; v != int64(3) {
		t.Errorf("3 -> %v", v)
	}
	if v := toks[15].n; v != 100.0 {
		t.Errorf("1e2 -> %v", v)
	}
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		"x = ":                       "c:1: unexpected symbol near <eof>",
		"goto x":                     "c:1: no visible label 'x' for goto at line 1",
		"local x <const> = 1; x = 2": "c:1: attempt to assign to const variable 'x'",
		"for i=1 do end":             "c:1: ',' expected near 'do'",
	}
	for src, want := range cases {
		_, err := parseChunk(src, "c")
		if err == nil || err.Error() != want {
			t.Errorf("parse %q: got %v want %q", src, err, want)
		}
	}
	if _, err := parseChunk("local a <close> = nil; return a", "c"); err != nil {
		t.Errorf("unexpected: %v", err)
	}
}

func TestTable(t *testing.T) {
	tb := newTable(0, 0)
	tb.set(int64(3), "c")
	tb.set(int64(1), "a")
	tb.set(int64(2), "b")
	if tb.length() != 3 || len(tb.arr) != 3 {
		t.Fatalf("migration failed: len=%d arr=%d", tb.length(), len(tb.arr))
	}
	tb.set(2.0, "B")
	if tb.get(int64(2)) != "B" {
		t.Errorf("float key normalisation")
	}
	tb.set("x", 1)
	tb.set("y", 2)
	tb.set("x", nil)
	n := 0
	pos := 0
	for {
		k, _, np := tb.nextAt(pos)
		if k == nil {
			break
		}
		pos = np
		n++
	}
	if n != 4 {
		t.Errorf("iteration visited %d entries, want 4", n)
	}
	tb.arr[2] = nil
	if tb.length() != 2 {
		t.Errorf("border with trailing nil: %d", tb.length())
	}
}

func TestIntegerHelpers(t *testing.T) {
	if idiv(-7, 2) != -4 || imod(-7, 3) != 2 || imod(7, -3) != -2 || idiv(math.MinInt64, -1) != math.MinInt64 {
		t.Errorf("integer division helpers")
	}
	if fmod(5.5, -2) != -0.5 || fmod(-5.5, 2) != 0.5 {
		t.Errorf("fmod")
	}
	if shiftLeft(1, 64) != 0 || shiftLeft(-1, -1) != math.MaxInt64 || shiftLeft(1, 63) != math.MinInt64 {
		t.Errorf("shift")
	}
	if !ltIntFloat(1, 1.5) || ltIntFloat(2, 1.5) || !leFloatInt(1.0, 1) || ltFloatInt(math.NaN(), 1) {
		t.Errorf("mixed comparison")
	}
	if chunkID("=foo") != "foo" || chunkID("@a.lua") != "a.lua" || chunkID("x\ny") != `[string "x..."]` {
		t.Errorf("chunkID")
	}
}
