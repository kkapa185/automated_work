package main

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// Value is any Lua value: nil, bool, int64, float64, string, *Table,
// *Closure, *GoFunction, *Coroutine, *Userdata.
type Value = interface{}

type Cell struct{ v Value }

type GoFunction struct {
	name string
	fn   func(th *Thread, args []Value) []Value
}

type Closure struct {
	proto  *Proto
	upvals []*Cell
}

type Userdata struct {
	meta *Table
	data interface{}
}

func typeName(v Value) string {
	switch v.(type) {
	case nil:
		return "nil"
	case bool:
		return "boolean"
	case int64, float64:
		return "number"
	case string:
		return "string"
	case *Table:
		return "table"
	case *Closure, *GoFunction:
		return "function"
	case *Coroutine:
		return "thread"
	case *Userdata:
		return "userdata"
	}
	return "?"
}

func truthy(v Value) bool {
	if b, ok := v.(bool); ok {
		return b
	}
	return v != nil
}

// fmtG formats like C's %.<prec>g.
func fmtG(f float64, prec int, alt bool) string {
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return fmtSpecial(f)
	}
	if prec == 0 {
		prec = 1
	}
	es := strconv.FormatFloat(f, 'e', prec-1, 64)
	idx := strings.IndexByte(es, 'e')
	exp, _ := strconv.Atoi(es[idx+1:])
	if exp < -4 || exp >= prec {
		mant := es[:idx]
		if !alt && strings.IndexByte(mant, '.') >= 0 {
			mant = strings.TrimRight(mant, "0")
			mant = strings.TrimSuffix(mant, ".")
		}
		return mant + es[idx:]
	}
	s := strconv.FormatFloat(f, 'f', prec-1-exp, 64)
	if !alt && strings.IndexByte(s, '.') >= 0 {
		s = strings.TrimRight(s, "0")
		s = strings.TrimSuffix(s, ".")
	}
	return s
}

func fmtSpecial(f float64) string {
	if math.IsInf(f, 1) {
		return "inf"
	}
	if math.IsInf(f, -1) {
		return "-inf"
	}
	if math.Signbit(f) {
		return "-nan"
	}
	return "nan"
}

func fmtFloat(f float64) string {
	s := fmtG(f, 14, false)
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= '0' && c <= '9' || c == '-') {
			return s
		}
	}
	return s + ".0"
}

func numToString(v Value) string {
	switch n := v.(type) {
	case int64:
		return strconv.FormatInt(n, 10)
	case float64:
		return fmtFloat(n)
	}
	return ""
}

func isSpaceC(c byte) bool {
	return c == ' ' || (c >= '\t' && c <= '\r')
}

func hexVal(c byte) int {
	switch {
	case c >= '0' && c <= '9':
		return int(c - '0')
	case c >= 'a' && c <= 'f':
		return int(c-'a') + 10
	case c >= 'A' && c <= 'F':
		return int(c-'A') + 10
	}
	return -1
}

// str2number converts a string following the Lua lexical rules for numerals
// (with optional surrounding whitespace and sign).
func str2number(s string) (Value, bool) {
	i, j := 0, len(s)
	for i < j && isSpaceC(s[i]) {
		i++
	}
	for j > i && isSpaceC(s[j-1]) {
		j--
	}
	s = s[i:j]
	if s == "" {
		return nil, false
	}
	neg := false
	p := 0
	if s[0] == '-' {
		neg = true
		p = 1
	} else if s[0] == '+' {
		p = 1
	}
	if p >= len(s) {
		return nil, false
	}
	if p+1 < len(s) && s[p] == '0' && (s[p+1] == 'x' || s[p+1] == 'X') {
		return parseHex(s[p+2:], neg)
	}
	// decimal
	k := p
	nd := 0
	isInt := true
	for k < len(s) && s[k] >= '0' && s[k] <= '9' {
		k++
		nd++
	}
	if k < len(s) && s[k] == '.' {
		isInt = false
		k++
		for k < len(s) && s[k] >= '0' && s[k] <= '9' {
			k++
			nd++
		}
	}
	if nd == 0 {
		return nil, false
	}
	if k < len(s) && (s[k] == 'e' || s[k] == 'E') {
		isInt = false
		k++
		if k < len(s) && (s[k] == '+' || s[k] == '-') {
			k++
		}
		ed := 0
		for k < len(s) && s[k] >= '0' && s[k] <= '9' {
			k++
			ed++
		}
		if ed == 0 {
			return nil, false
		}
	}
	if k != len(s) {
		return nil, false
	}
	if isInt {
		var a uint64
		ok := true
		for q := p; q < len(s); q++ {
			d := uint64(s[q] - '0')
			if a > math.MaxInt64/10 || (a == math.MaxInt64/10 && d > 7+b2u(neg)) {
				ok = false
				break
			}
			a = a*10 + d
		}
		if ok {
			if neg {
				return int64(-a), true
			}
			return int64(a), true
		}
	}
	f, _ := strconv.ParseFloat(s[p:], 64)
	if neg {
		f = -f
	}
	return f, true
}

func b2u(b bool) uint64 {
	if b {
		return 1
	}
	return 0
}

func parseHex(s string, neg bool) (Value, bool) {
	var mant uint64
	var fm float64
	nd := 0
	exp := 0
	isFloat := false
	k := 0
	for k < len(s) && hexVal(s[k]) >= 0 {
		mant = mant*16 + uint64(hexVal(s[k]))
		fm = fm*16 + float64(hexVal(s[k]))
		k++
		nd++
	}
	if k < len(s) && s[k] == '.' {
		isFloat = true
		k++
		for k < len(s) && hexVal(s[k]) >= 0 {
			fm = fm*16 + float64(hexVal(s[k]))
			exp -= 4
			k++
			nd++
		}
	}
	if nd == 0 {
		return nil, false
	}
	if k < len(s) && (s[k] == 'p' || s[k] == 'P') {
		isFloat = true
		k++
		esign := 1
		if k < len(s) && (s[k] == '+' || s[k] == '-') {
			if s[k] == '-' {
				esign = -1
			}
			k++
		}
		ed := 0
		e := 0
		for k < len(s) && s[k] >= '0' && s[k] <= '9' {
			if e < 100000 {
				e = e*10 + int(s[k]-'0')
			}
			k++
			ed++
		}
		if ed == 0 {
			return nil, false
		}
		exp += esign * e
	}
	if k != len(s) {
		return nil, false
	}
	if !isFloat {
		if neg {
			return int64(-mant), true
		}
		return int64(mant), true
	}
	f := math.Ldexp(fm, exp)
	if neg {
		f = -f
	}
	return f, true
}

// toNumber converts numbers and numeric strings.
func toNumber(v Value) (Value, bool) {
	switch x := v.(type) {
	case int64, float64:
		return x, true
	case string:
		return str2number(x)
	}
	return nil, false
}

func floatToInt(f float64) (int64, bool) {
	if f >= -9223372036854775808.0 && f < 9223372036854775808.0 {
		i := int64(f)
		if float64(i) == f {
			return i, true
		}
	}
	return 0, false
}

// toInteger: ints, floats with exact integer value, numeric strings.
func toInteger(v Value) (int64, bool) {
	switch x := v.(type) {
	case int64:
		return x, true
	case float64:
		return floatToInt(x)
	case string:
		n, ok := str2number(x)
		if !ok {
			return 0, false
		}
		return toInteger(n)
	}
	return 0, false
}

func toFloat(v Value) (float64, bool) {
	switch x := v.(type) {
	case int64:
		return float64(x), true
	case float64:
		return x, true
	case string:
		n, ok := str2number(x)
		if !ok {
			return 0, false
		}
		return toFloat(n)
	}
	return 0, false
}

func addrOf(v Value) string {
	return fmt.Sprintf("%p", v)
}

// chunkID produces the short source used in messages.
func chunkID(source string) string {
	const idsize = 60
	if source == "" {
		return "?"
	}
	switch source[0] {
	case '=':
		s := source[1:]
		if len(s) > idsize-1 {
			s = s[:idsize-1]
		}
		return s
	case '@':
		s := source[1:]
		if len(s) > idsize-1 {
			s = "..." + s[len(s)-(idsize-4):]
		}
		return s
	}
	nl := strings.IndexByte(source, '\n')
	avail := idsize - 15
	if nl < 0 && len(source) < avail {
		return `[string "` + source + `"]`
	}
	if nl >= 0 {
		source = source[:nl]
	}
	if len(source) > avail {
		source = source[:avail]
	}
	return `[string "` + source + `..."]`
}
