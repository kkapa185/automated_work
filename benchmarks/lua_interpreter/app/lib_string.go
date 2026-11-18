package main

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

func posRelatI(pos, l int64) int64 {
	if pos > 0 {
		return pos
	} else if pos == 0 {
		return 1
	} else if pos < -l {
		return 1
	}
	return l + pos + 1
}

func getEndPos(pos, l int64) int64 {
	if pos > l {
		return l
	} else if pos >= 0 {
		return pos
	} else if pos < -l {
		return 0
	}
	return l + pos + 1
}

// ---------- pattern matching ----------

const (
	capUnfinished = -1
	capPosition   = -2
	maxCaptures   = 32
	maxMatchDepth = 200
)

type matchState struct {
	th    *Thread
	src   string
	pat   string
	level int
	depth int
	cap   [maxCaptures]struct{ init, len int }
}

func (ms *matchState) classEnd(p int) int {
	pat := ms.pat
	if p >= len(pat) {
		ms.th.rtError("malformed pattern (ends with '%%')")
	}
	c := pat[p]
	p++
	if c == '%' {
		if p >= len(pat) {
			ms.th.rtError("malformed pattern (ends with '%%')")
		}
		return p + 1
	}
	if c == '[' {
		if p < len(pat) && pat[p] == '^' {
			p++
		}
		for {
			if p >= len(pat) {
				ms.th.rtError("malformed pattern (missing ']')")
			}
			cc := pat[p]
			p++
			if cc == '%' {
				if p >= len(pat) {
					ms.th.rtError("malformed pattern (missing ']')")
				}
				p++
			}
			if p >= len(pat) {
				ms.th.rtError("malformed pattern (missing ']')")
			}
			if pat[p] == ']' {
				break
			}
		}
		return p + 1
	}
	return p
}

func isAlphaC(c byte) bool { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') }
func isDigitC(c byte) bool { return c >= '0' && c <= '9' }
func isLowerC(c byte) bool { return c >= 'a' && c <= 'z' }
func isUpperC(c byte) bool { return c >= 'A' && c <= 'Z' }
func isCntrlC(c byte) bool { return c < 32 || c == 127 }
func isPunctC(c byte) bool {
	return c > 32 && c < 127 && !isAlphaC(c) && !isDigitC(c)
}

func matchClass(c, cl byte) bool {
	var res bool
	lower := cl | 0x20
	switch lower {
	case 'a':
		res = isAlphaC(c)
	case 'c':
		res = isCntrlC(c)
	case 'd':
		res = isDigitC(c)
	case 'g':
		res = c > 32 && c < 127
	case 'l':
		res = isLowerC(c)
	case 'p':
		res = isPunctC(c)
	case 's':
		res = isSpaceC(c)
	case 'u':
		res = isUpperC(c)
	case 'w':
		res = isAlphaC(c) || isDigitC(c)
	case 'x':
		res = hexVal(c) >= 0
	default:
		return cl == c
	}
	if isUpperC(cl) {
		return !res
	}
	return res
}

func (ms *matchState) matchBracketClass(c byte, p, ec int) bool {
	pat := ms.pat
	sig := true
	if pat[p+1] == '^' {
		sig = false
		p++
	}
	for p++; p < ec; p++ {
		if pat[p] == '%' {
			p++
			if matchClass(c, pat[p]) {
				return sig
			}
		} else if p+2 < ec && pat[p+1] == '-' {
			p += 2
			if pat[p-2] <= c && c <= pat[p] {
				return sig
			}
		} else if pat[p] == c {
			return sig
		}
	}
	return !sig
}

func (ms *matchState) singleMatch(s, p, ep int) bool {
	if s >= len(ms.src) {
		return false
	}
	c := ms.src[s]
	switch ms.pat[p] {
	case '.':
		return true
	case '%':
		return matchClass(c, ms.pat[p+1])
	case '[':
		return ms.matchBracketClass(c, p, ep-1)
	}
	return ms.pat[p] == c
}

func (ms *matchState) matchBalance(s, p int) int {
	if p+1 >= len(ms.pat) {
		ms.th.rtError("malformed pattern (missing arguments to '%%b')")
	}
	if s >= len(ms.src) || ms.src[s] != ms.pat[p] {
		return -1
	}
	b, e := ms.pat[p], ms.pat[p+1]
	cont := 1
	for s++; s < len(ms.src); s++ {
		c := ms.src[s]
		if c == e {
			cont--
			if cont == 0 {
				return s + 1
			}
		} else if c == b {
			cont++
		}
	}
	return -1
}

func (ms *matchState) maxExpand(s, p, ep int) int {
	i := 0
	for ms.singleMatch(s+i, p, ep) {
		i++
	}
	for i >= 0 {
		if res := ms.match(s+i, ep+1); res != -1 {
			return res
		}
		i--
	}
	return -1
}

func (ms *matchState) minExpand(s, p, ep int) int {
	for {
		if res := ms.match(s, ep+1); res != -1 {
			return res
		}
		if ms.singleMatch(s, p, ep) {
			s++
		} else {
			return -1
		}
	}
}

func (ms *matchState) startCapture(s, p, what int) int {
	if ms.level >= maxCaptures {
		ms.th.rtError("too many captures")
	}
	ms.cap[ms.level].init = s
	ms.cap[ms.level].len = what
	ms.level++
	res := ms.match(s, p)
	if res == -1 {
		ms.level--
	}
	return res
}

func (ms *matchState) endCapture(s, p int) int {
	l := -1
	for i := ms.level - 1; i >= 0; i-- {
		if ms.cap[i].len == capUnfinished {
			l = i
			break
		}
	}
	if l < 0 {
		ms.th.rtError("invalid pattern capture")
	}
	ms.cap[l].len = s - ms.cap[l].init
	res := ms.match(s, p)
	if res == -1 {
		ms.cap[l].len = capUnfinished
	}
	return res
}

func (ms *matchState) matchCapture(s int, l byte) int {
	i := int(l) - '1'
	if i < 0 || i >= ms.level || ms.cap[i].len == capUnfinished {
		ms.th.rtError("invalid capture index %%%d", i+1)
	}
	n := ms.cap[i].len
	if len(ms.src)-s >= n && ms.src[ms.cap[i].init:ms.cap[i].init+n] == ms.src[s:s+n] {
		return s + n
	}
	return -1
}

func (ms *matchState) match(s, p int) int {
	ms.depth++
	if ms.depth > maxMatchDepth*5 {
		ms.th.rtError("pattern too complex")
	}
	defer func() { ms.depth-- }()
	pat := ms.pat
	for {
		if p >= len(pat) {
			return s
		}
		switch pat[p] {
		case '(':
			if p+1 < len(pat) && pat[p+1] == ')' {
				return ms.startCapture(s, p+2, capPosition)
			}
			return ms.startCapture(s, p+1, capUnfinished)
		case ')':
			return ms.endCapture(s, p+1)
		case '$':
			if p+1 == len(pat) {
				if s == len(ms.src) {
					return s
				}
				return -1
			}
		case '%':
			if p+1 < len(pat) {
				switch pat[p+1] {
				case 'b':
					s = ms.matchBalance(s, p+2)
					if s != -1 {
						p += 4
						continue
					}
					return -1
				case 'f':
					p += 2
					if p >= len(pat) || pat[p] != '[' {
						ms.th.rtError("missing '[' after '%%f' in pattern")
					}
					ep := ms.classEnd(p)
					var prev, cur byte
					if s > 0 {
						prev = ms.src[s-1]
					}
					if s < len(ms.src) {
						cur = ms.src[s]
					}
					if !ms.matchBracketClass(prev, p, ep-1) && ms.matchBracketClass(cur, p, ep-1) {
						p = ep
						continue
					}
					return -1
				case '0', '1', '2', '3', '4', '5', '6', '7', '8', '9':
					s = ms.matchCapture(s, pat[p+1])
					if s != -1 {
						p += 2
						continue
					}
					return -1
				}
			}
		}
		ep := ms.classEnd(p)
		var epc byte
		if ep < len(pat) {
			epc = pat[ep]
		}
		switch epc {
		case '?':
			if ms.singleMatch(s, p, ep) {
				if res := ms.match(s+1, ep+1); res != -1 {
					return res
				}
			}
			p = ep + 1
			continue
		case '+':
			if ms.singleMatch(s, p, ep) {
				return ms.maxExpand(s+1, p, ep)
			}
			return -1
		case '*':
			return ms.maxExpand(s, p, ep)
		case '-':
			return ms.minExpand(s, p, ep)
		}
		if !ms.singleMatch(s, p, ep) {
			return -1
		}
		s++
		p = ep
	}
}

func (ms *matchState) getCapture(i, s, e int) Value {
	if i >= ms.level {
		if i == 0 {
			return ms.src[s:e]
		}
		ms.th.rtError("invalid capture index %%%d", i+1)
	}
	l := ms.cap[i].len
	if l == capUnfinished {
		ms.th.rtError("unfinished capture")
	}
	if l == capPosition {
		return int64(ms.cap[i].init + 1)
	}
	return ms.src[ms.cap[i].init : ms.cap[i].init+l]
}

func (ms *matchState) captures(s, e int, wholeIfNone bool) []Value {
	n := ms.level
	if n == 0 && wholeIfNone {
		n = 1
	}
	out := make([]Value, n)
	for i := 0; i < n; i++ {
		out[i] = ms.getCapture(i, s, e)
	}
	return out
}

func hasSpecials(p string) bool {
	return strings.ContainsAny(p, "^$*+?.([%-")
}

func strFindAux(th *Thread, args []Value, find bool) []Value {
	fname := "match"
	if find {
		fname = "find"
	}
	s := checkStr(th, args, 0, fname)
	p := checkStr(th, args, 1, fname)
	init := posRelatI(optInt(th, args, 2, fname, 1), int64(len(s)))
	if init > int64(len(s))+1 {
		return []Value{nil}
	}
	if find && (truthy(argOr(args, 3)) || !hasSpecials(p)) {
		idx := strings.Index(s[init-1:], p)
		if idx < 0 {
			return []Value{nil}
		}
		st := int(init-1) + idx
		return []Value{int64(st + 1), int64(st + len(p))}
	}
	anchor := len(p) > 0 && p[0] == '^'
	pi := 0
	if anchor {
		pi = 1
	}
	ms := &matchState{th: th, src: s, pat: p}
	s1 := int(init - 1)
	for {
		ms.level = 0
		ms.depth = 0
		if e := ms.match(s1, pi); e != -1 {
			if find {
				out := []Value{int64(s1 + 1), int64(e)}
				return append(out, ms.captures(s1, e, false)...)
			}
			return ms.captures(s1, e, true)
		}
		s1++
		if anchor || s1 > len(s) {
			break
		}
	}
	return []Value{nil}
}

func strGmatch(th *Thread, args []Value) []Value {
	s := checkStr(th, args, 0, "gmatch")
	p := checkStr(th, args, 1, "gmatch")
	init := posRelatI(optInt(th, args, 2, "gmatch", 1), int64(len(s)))
	pos := int(init - 1)
	if init > int64(len(s))+1 {
		pos = len(s) + 1
	}
	lastMatch := -1
	ms := &matchState{th: th, src: s, pat: p}
	return []Value{&GoFunction{name: "gmatch_iter", fn: func(th *Thread, _ []Value) []Value {
		ms.th = th
		for src := pos; src <= len(s); src++ {
			ms.level = 0
			ms.depth = 0
			if e := ms.match(src, 0); e != -1 && e != lastMatch {
				pos = e
				lastMatch = e
				return ms.captures(src, e, true)
			}
		}
		pos = len(s) + 1
		return []Value{nil}
	}}}
}

func strGsub(th *Thread, args []Value) []Value {
	src := checkStr(th, args, 0, "gsub")
	p := checkStr(th, args, 1, "gsub")
	repl := argOr(args, 2)
	switch repl.(type) {
	case string, int64, float64, *Table, *Closure, *GoFunction:
	default:
		typeErr(th, args, 2, "gsub", "string/function/table")
	}
	maxN := optInt(th, args, 3, "gsub", int64(len(src))+1)
	anchor := len(p) > 0 && p[0] == '^'
	pi := 0
	if anchor {
		pi = 1
	}
	var replStr string
	isStr := false
	switch r := repl.(type) {
	case string:
		replStr, isStr = r, true
	case int64, float64:
		replStr, isStr = numToString(r), true
	}
	ms := &matchState{th: th, src: src, pat: p}
	var b strings.Builder
	s := 0
	lastMatch := -1
	var n int64
	for n < maxN {
		ms.level = 0
		ms.depth = 0
		e := ms.match(s, pi)
		if e != -1 && e != lastMatch {
			n++
			// add value
			if isStr {
				for i := 0; i < len(replStr); i++ {
					c := replStr[i]
					if c != '%' {
						b.WriteByte(c)
						continue
					}
					i++
					if i >= len(replStr) {
						th.rtError("invalid use of '%%' in replacement string")
					}
					d := replStr[i]
					if d == '%' {
						b.WriteByte('%')
					} else if d >= '0' && d <= '9' {
						if d == '0' {
							b.WriteString(src[s:e])
						} else {
							ci := int(d - '1')
							if ci >= ms.level && !(ci == 0 && ms.level == 0) {
								th.rtError("invalid capture index %%%d in replacement string", ci+1)
							}
							v := ms.getCapture(ci, s, e)
							if str, ok := v.(string); ok {
								b.WriteString(str)
							} else {
								b.WriteString(numToString(v))
							}
						}
					} else {
						th.rtError("invalid use of '%%' in replacement string")
					}
				}
			} else {
				var v Value
				if t, ok := repl.(*Table); ok {
					key := ms.getCapture(0, s, e)
					v = th.index(t, key, "")
				} else {
					v = first(th.call(repl, ms.captures(s, e, true)))
				}
				if !truthy(v) {
					b.WriteString(src[s:e])
				} else if str, ok := v.(string); ok {
					b.WriteString(str)
				} else if isStrNum(v) {
					b.WriteString(numToString(v))
				} else {
					th.rtError("invalid replacement value (a %s)", typeName(v))
				}
			}
			s = e
			lastMatch = e
		} else if s < len(src) {
			b.WriteByte(src[s])
			s++
		} else {
			break
		}
		if anchor {
			break
		}
	}
	if s < len(src) {
		b.WriteString(src[s:])
	}
	return []Value{b.String(), n}
}

// ---------- format ----------

type fmtSpec struct {
	left, plus, space, alt, zero bool
	width                        int
	prec                         int // -1 if absent
}

func (sp *fmtSpec) pad(sign, body string, allowZero bool) string {
	total := len(sign) + len(body)
	if total >= sp.width {
		return sign + body
	}
	n := sp.width - total
	if sp.left {
		return sign + body + strings.Repeat(" ", n)
	}
	if sp.zero && allowZero {
		return sign + strings.Repeat("0", n) + body
	}
	return strings.Repeat(" ", n) + sign + body
}

func (sp *fmtSpec) signStr(neg bool) string {
	if neg {
		return "-"
	}
	if sp.plus {
		return "+"
	}
	if sp.space {
		return " "
	}
	return ""
}

func (sp *fmtSpec) fmtInt(v int64, conv byte) string {
	switch conv {
	case 'd', 'i':
		neg := v < 0
		u := uint64(v)
		if neg {
			u = -u
		}
		body := strconv.FormatUint(u, 10)
		if sp.prec >= 0 {
			for len(body) < sp.prec {
				body = "0" + body
			}
			if sp.prec == 0 && u == 0 {
				body = ""
			}
		}
		return sp.pad(sp.signStr(neg), body, sp.prec < 0)
	}
	u := uint64(v)
	var body, prefix string
	switch conv {
	case 'u':
		body = strconv.FormatUint(u, 10)
	case 'x':
		body = strconv.FormatUint(u, 16)
		if sp.alt && u != 0 {
			prefix = "0x"
		}
	case 'X':
		body = strings.ToUpper(strconv.FormatUint(u, 16))
		if sp.alt && u != 0 {
			prefix = "0X"
		}
	case 'o':
		body = strconv.FormatUint(u, 8)
		if sp.alt && u != 0 {
			prefix = "0"
		}
	}
	if sp.prec >= 0 {
		for len(body) < sp.prec {
			body = "0" + body
		}
		if sp.prec == 0 && u == 0 {
			body = ""
		}
	}
	return sp.pad(prefix, body, sp.prec < 0)
}

func cHexFloat(f float64, prec int, upper bool) string {
	s := strconv.FormatFloat(f, 'x', prec, 64)
	// Go: 0x1.8p+01 ; C: 0x1.8p+1
	if i := strings.IndexByte(s, 'p'); i >= 0 {
		exp := s[i+2:]
		exp = strings.TrimLeft(exp, "0")
		if exp == "" {
			exp = "0"
		}
		s = s[:i+2] + exp
	}
	if upper {
		s = strings.ToUpper(s)
	}
	return s
}

func (sp *fmtSpec) fmtFloat(f float64, conv byte) string {
	neg := math.Signbit(f)
	upper := conv == 'E' || conv == 'G' || conv == 'A' || conv == 'F'
	if math.IsInf(f, 0) || math.IsNaN(f) {
		body := "inf"
		if math.IsNaN(f) {
			body = "nan"
		}
		if upper {
			body = strings.ToUpper(body)
		}
		return sp.pad(sp.signStr(neg), body, false)
	}
	a := math.Abs(f)
	prec := sp.prec
	var body string
	switch conv {
	case 'f', 'F':
		if prec < 0 {
			prec = 6
		}
		body = strconv.FormatFloat(a, 'f', prec, 64)
		if sp.alt && prec == 0 {
			body += "."
		}
	case 'e', 'E':
		if prec < 0 {
			prec = 6
		}
		body = strconv.FormatFloat(a, 'e', prec, 64)
		if sp.alt && prec == 0 {
			i := strings.IndexByte(body, 'e')
			body = body[:i] + "." + body[i:]
		}
		if upper {
			body = strings.ToUpper(body)
		}
	case 'g', 'G':
		if prec < 0 {
			prec = 6
		}
		body = fmtG(a, prec, sp.alt)
		if upper {
			body = strings.ToUpper(body)
		}
	case 'a', 'A':
		body = cHexFloat(a, prec, upper)
	}
	sign := sp.signStr(neg)
	if conv == 'a' || conv == 'A' {
		// zero padding goes after the 0x prefix
		if sp.zero && !sp.left && len(sign)+len(body) < sp.width {
			n := sp.width - len(sign) - len(body)
			return sign + body[:2] + strings.Repeat("0", n) + body[2:]
		}
	}
	return sp.pad(sign, body, true)
}

func quoteString(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '"':
			b.WriteString("\\\"")
		case c == '\\':
			b.WriteString("\\\\")
		case c == '\n':
			b.WriteString("\\\n")
		case c == '\r':
			b.WriteString("\\r")
		case c == 0:
			if i+1 < len(s) && isDigitC(s[i+1]) {
				b.WriteString("\\000")
			} else {
				b.WriteString("\\0")
			}
		case isCntrlC(c):
			if i+1 < len(s) && isDigitC(s[i+1]) {
				fmt.Fprintf(&b, "\\%03d", c)
			} else {
				fmt.Fprintf(&b, "\\%d", c)
			}
		default:
			b.WriteByte(c)
		}
	}
	b.WriteByte('"')
	return b.String()
}

func strFormat(th *Thread, args []Value) []Value {
	f := checkStr(th, args, 0, "format")
	var b strings.Builder
	argi := 0
	for i := 0; i < len(f); i++ {
		c := f[i]
		if c != '%' {
			b.WriteByte(c)
			continue
		}
		i++
		if i >= len(f) {
			th.rtError("invalid conversion '%%' to 'format'")
		}
		if f[i] == '%' {
			b.WriteByte('%')
			continue
		}
		start := i
		sp := fmtSpec{prec: -1}
		for i < len(f) && strings.IndexByte("-+ #0", f[i]) >= 0 {
			switch f[i] {
			case '-':
				sp.left = true
			case '+':
				sp.plus = true
			case ' ':
				sp.space = true
			case '#':
				sp.alt = true
			case '0':
				sp.zero = true
			}
			i++
		}
		nd := 0
		for i < len(f) && isDigitC(f[i]) {
			sp.width = sp.width*10 + int(f[i]-'0')
			i++
			nd++
		}
		bad := nd > 2
		if i < len(f) && f[i] == '.' {
			i++
			sp.prec = 0
			nd = 0
			for i < len(f) && isDigitC(f[i]) {
				sp.prec = sp.prec*10 + int(f[i]-'0')
				i++
				nd++
			}
			if nd > 2 {
				bad = true
			}
		}
		if i >= len(f) || bad {
			end := i
			if end >= len(f) {
				end = len(f) - 1
			}
			th.rtError("invalid conversion '%%%s' to 'format'", f[start:end+1])
		}
		conv := f[i]
		argi++
		switch conv {
		case 'd', 'i', 'u', 'x', 'X', 'o':
			if argi >= len(args) {
				argErr(th, argi+1, "format", "number expected, got no value")
			}
			n := checkInt(th, args, argi, "format")
			b.WriteString(sp.fmtInt(n, conv))
		case 'c':
			n := checkInt(th, args, argi, "format")
			b.WriteString(sp.pad("", string([]byte{byte(n)}), false))
		case 'e', 'E', 'f', 'F', 'g', 'G', 'a', 'A':
			if argi >= len(args) {
				argErr(th, argi+1, "format", "number expected, got no value")
			}
			b.WriteString(sp.fmtFloat(checkNum(th, args, argi, "format"), conv))
		case 's':
			if argi >= len(args) {
				argErr(th, argi+1, "format", "no value")
			}
			s := th.tostr(args[argi])
			if sp.prec >= 0 && sp.prec < len(s) {
				s = s[:sp.prec]
			}
			b.WriteString(sp.pad("", s, false))
		case 'p':
			if argi >= len(args) {
				argErr(th, argi+1, "format", "no value")
			}
			s := "(null)"
			switch args[argi].(type) {
			case *Table, *Closure, *GoFunction, *Coroutine, *Userdata:
				s = fmt.Sprintf("%p", args[argi])
			}
			b.WriteString(sp.pad("", s, false))
		case 'q':
			if i != start {
				th.rtError("specifier '%%q' cannot have modifiers")
			}
			if argi >= len(args) {
				argErr(th, argi+1, "format", "no value")
			}
			switch v := args[argi].(type) {
			case string:
				b.WriteString(quoteString(v))
			case int64:
				if v == math.MinInt64 {
					b.WriteString("0x8000000000000000")
				} else {
					b.WriteString(strconv.FormatInt(v, 10))
				}
			case float64:
				switch {
				case math.IsInf(v, 1):
					b.WriteString("1e9999")
				case math.IsInf(v, -1):
					b.WriteString("-1e9999")
				case math.IsNaN(v):
					b.WriteString("(0/0)")
				default:
					sq := fmtSpec{prec: -1}
					b.WriteString(sq.fmtFloat(v, 'a'))
				}
			case nil, bool:
				b.WriteString(th.tostr(v))
			default:
				argErr(th, argi+1, "format", "value has no literal form")
			}
		default:
			th.rtError("invalid conversion '%%%s' to 'format'", f[start:i+1])
		}
	}
	return []Value{b.String()}
}
