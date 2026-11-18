package main

import (
	"fmt"
	"strings"
)

// Token kinds: single-byte tokens use their byte value.
const (
	tkEOF = 256 + iota
	tkName
	tkString
	tkNumber
	// keywords
	tkAnd
	tkBreak
	tkDo
	tkElse
	tkElseif
	tkEnd
	tkFalse
	tkFor
	tkFunction
	tkGoto
	tkIf
	tkIn
	tkLocal
	tkNil
	tkNot
	tkOr
	tkRepeat
	tkReturn
	tkThen
	tkTrue
	tkUntil
	tkWhile
	// multi-char symbols
	tkIdiv
	tkConcat
	tkDots
	tkEq
	tkGe
	tkLe
	tkNe
	tkShl
	tkShr
	tkDbColon
)

var keywords = map[string]int{
	"and": tkAnd, "break": tkBreak, "do": tkDo, "else": tkElse, "elseif": tkElseif,
	"end": tkEnd, "false": tkFalse, "for": tkFor, "function": tkFunction, "goto": tkGoto,
	"if": tkIf, "in": tkIn, "local": tkLocal, "nil": tkNil, "not": tkNot, "or": tkOr,
	"repeat": tkRepeat, "return": tkReturn, "then": tkThen, "true": tkTrue,
	"until": tkUntil, "while": tkWhile,
}

var symNames = map[int]string{
	tkIdiv: "//", tkConcat: "..", tkDots: "...", tkEq: "==", tkGe: ">=", tkLe: "<=",
	tkNe: "~=", tkShl: "<<", tkShr: ">>", tkDbColon: "::", tkEOF: "<eof>",
}

type Token struct {
	kind int
	s    string // name / string contents
	n    Value  // numeric value
	raw  string // raw text for error messages
	line int
}

// SyntaxError is raised (via panic) by lexer/parser and converted to a Lua error.
type SyntaxError struct{ msg string }

type Lexer struct {
	src   string
	pos   int
	line  int
	chunk string
	tokLo int
}

func newLexer(src, chunk string) *Lexer {
	return &Lexer{src: src, line: 1, chunk: chunk}
}

func (lx *Lexer) errorAt(msg string, near string, line int) {
	if near != "" {
		msg = fmt.Sprintf("%s:%d: %s near %s", lx.chunk, line, msg, near)
	} else {
		msg = fmt.Sprintf("%s:%d: %s", lx.chunk, line, msg)
	}
	panic(&SyntaxError{msg})
}

func (lx *Lexer) lexErr(msg string) {
	end := lx.pos
	if end > len(lx.src) {
		end = len(lx.src)
	}
	lx.errorAt(msg, "'"+lx.src[lx.tokLo:end]+"'", lx.line)
}

func (lx *Lexer) cur() int {
	if lx.pos < len(lx.src) {
		return int(lx.src[lx.pos])
	}
	return -1
}

func (lx *Lexer) incLine() {
	c := lx.src[lx.pos]
	lx.pos++
	if lx.pos < len(lx.src) {
		d := lx.src[lx.pos]
		if (d == '\n' || d == '\r') && d != c {
			lx.pos++
		}
	}
	lx.line++
}

func isAlpha(c int) bool { return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') }
func isDigit(c int) bool { return c >= '0' && c <= '9' }

func (lx *Lexer) next() Token {
	for {
		lx.tokLo = lx.pos
		c := lx.cur()
		switch {
		case c == -1:
			return Token{kind: tkEOF, line: lx.line}
		case c == '\n' || c == '\r':
			lx.incLine()
		case c == ' ' || c == '\t' || c == '\v' || c == '\f':
			lx.pos++
		case c == '-':
			if lx.pos+1 < len(lx.src) && lx.src[lx.pos+1] == '-' {
				lx.pos += 2
				if lx.cur() == '[' {
					if lvl := lx.longLevel(); lvl >= 0 {
						lx.readLong(lvl, true)
						continue
					}
				}
				for lx.pos < len(lx.src) && lx.src[lx.pos] != '\n' && lx.src[lx.pos] != '\r' {
					lx.pos++
				}
				continue
			}
			lx.pos++
			return Token{kind: '-', line: lx.line}
		case c == '[':
			lvl := lx.longLevel()
			if lvl >= 0 {
				line := lx.line
				s := lx.readLong(lvl, false)
				return Token{kind: tkString, s: s, line: line, raw: lx.src[lx.tokLo:lx.pos]}
			}
			if lvl == -1 {
				lx.pos++
				return Token{kind: '[', line: lx.line}
			}
			lx.pos++
			lx.lexErr("invalid long string delimiter")
		case c == '=':
			return lx.two('=', tkEq, '=')
		case c == '<':
			if lx.peek(1) == '<' {
				lx.pos += 2
				return Token{kind: tkShl, line: lx.line}
			}
			return lx.two('=', tkLe, '<')
		case c == '>':
			if lx.peek(1) == '>' {
				lx.pos += 2
				return Token{kind: tkShr, line: lx.line}
			}
			return lx.two('=', tkGe, '>')
		case c == '/':
			return lx.two('/', tkIdiv, '/')
		case c == '~':
			return lx.two('=', tkNe, '~')
		case c == ':':
			return lx.two(':', tkDbColon, ':')
		case c == '"' || c == '\'':
			return lx.readString(byte(c))
		case c == '.':
			if lx.peek(1) == '.' {
				if lx.peek(2) == '.' {
					lx.pos += 3
					return Token{kind: tkDots, line: lx.line}
				}
				lx.pos += 2
				return Token{kind: tkConcat, line: lx.line}
			}
			if isDigit(lx.peek(1)) {
				return lx.readNumber()
			}
			lx.pos++
			return Token{kind: '.', line: lx.line}
		case isDigit(c):
			return lx.readNumber()
		case isAlpha(c):
			st := lx.pos
			for lx.pos < len(lx.src) && (isAlpha(int(lx.src[lx.pos])) || isDigit(int(lx.src[lx.pos]))) {
				lx.pos++
			}
			w := lx.src[st:lx.pos]
			if k, ok := keywords[w]; ok {
				return Token{kind: k, s: w, line: lx.line}
			}
			return Token{kind: tkName, s: w, line: lx.line, raw: w}
		default:
			lx.pos++
			return Token{kind: c, line: lx.line}
		}
	}
}

func (lx *Lexer) peek(n int) int {
	if lx.pos+n < len(lx.src) {
		return int(lx.src[lx.pos+n])
	}
	return -1
}

func (lx *Lexer) two(second byte, kind int, single int) Token {
	if lx.peek(1) == int(second) {
		lx.pos += 2
		return Token{kind: kind, line: lx.line}
	}
	lx.pos++
	return Token{kind: single, line: lx.line}
}

// longLevel at '[': returns level if a long bracket opens ("[==["), -1 if just '[' ,
// -2 if "[=" without second '['. Does not consume anything.
func (lx *Lexer) longLevel() int {
	p := lx.pos + 1
	lvl := 0
	for p < len(lx.src) && lx.src[p] == '=' {
		lvl++
		p++
	}
	if p < len(lx.src) && lx.src[p] == '[' {
		return lvl
	}
	if lvl == 0 {
		return -1
	}
	return -2
}

func (lx *Lexer) readLong(lvl int, comment bool) string {
	startLine := lx.line
	lx.pos += lvl + 2
	if lx.pos < len(lx.src) && (lx.src[lx.pos] == '\n' || lx.src[lx.pos] == '\r') {
		lx.incLine()
	}
	var sb strings.Builder
	for {
		if lx.pos >= len(lx.src) {
			what := "string"
			if comment {
				what = "comment"
			}
			lx.errorAt(fmt.Sprintf("unfinished long %s (starting at line %d)", what, startLine), "<eof>", lx.line)
		}
		c := lx.src[lx.pos]
		if c == ']' {
			p := lx.pos + 1
			l := 0
			for p < len(lx.src) && lx.src[p] == '=' {
				l++
				p++
			}
			if l == lvl && p < len(lx.src) && lx.src[p] == ']' {
				lx.pos = p + 1
				return sb.String()
			}
			sb.WriteByte(c)
			lx.pos++
		} else if c == '\n' || c == '\r' {
			lx.incLine()
			sb.WriteByte('\n')
		} else {
			sb.WriteByte(c)
			lx.pos++
		}
	}
}

func (lx *Lexer) readString(q byte) Token {
	line := lx.line
	lx.pos++
	var sb strings.Builder
	for {
		if lx.pos >= len(lx.src) {
			lx.errorAt("unfinished string", "<eof>", lx.line)
		}
		c := lx.src[lx.pos]
		switch c {
		case q:
			lx.pos++
			return Token{kind: tkString, s: sb.String(), line: line, raw: lx.src[lx.tokLo:lx.pos]}
		case '\n', '\r':
			lx.lexErr("unfinished string")
		case '\\':
			lx.pos++
			if lx.pos >= len(lx.src) {
				lx.errorAt("unfinished string", "<eof>", lx.line)
			}
			e := lx.src[lx.pos]
			switch e {
			case 'n':
				sb.WriteByte('\n')
				lx.pos++
			case 't':
				sb.WriteByte('\t')
				lx.pos++
			case 'a':
				sb.WriteByte(7)
				lx.pos++
			case 'b':
				sb.WriteByte(8)
				lx.pos++
			case 'f':
				sb.WriteByte(12)
				lx.pos++
			case 'r':
				sb.WriteByte('\r')
				lx.pos++
			case 'v':
				sb.WriteByte(11)
				lx.pos++
			case '\\', '"', '\'':
				sb.WriteByte(e)
				lx.pos++
			case '\n', '\r':
				lx.incLine()
				sb.WriteByte('\n')
			case 'x':
				lx.pos++
				v := 0
				for i := 0; i < 2; i++ {
					h := -1
					if lx.pos < len(lx.src) {
						h = hexVal(lx.src[lx.pos])
					}
					if h < 0 {
						if lx.pos < len(lx.src) {
							lx.pos++
						}
						lx.lexErr("hexadecimal digit expected")
					}
					v = v*16 + h
					lx.pos++
				}
				sb.WriteByte(byte(v))
			case 'z':
				lx.pos++
				for lx.pos < len(lx.src) && isSpaceC(lx.src[lx.pos]) {
					if lx.src[lx.pos] == '\n' || lx.src[lx.pos] == '\r' {
						lx.incLine()
					} else {
						lx.pos++
					}
				}
			case 'u':
				lx.pos++
				if lx.cur() != '{' {
					lx.pos++
					lx.lexErr("missing '{' in \\u{xxxx}")
				}
				lx.pos++
				var v uint64
				nd := 0
				for lx.pos < len(lx.src) && hexVal(lx.src[lx.pos]) >= 0 {
					v = v*16 + uint64(hexVal(lx.src[lx.pos]))
					if v > 0x7FFFFFFF {
						lx.pos++
						lx.lexErr("UTF-8 value too large")
					}
					lx.pos++
					nd++
				}
				if nd == 0 {
					lx.pos++
					lx.lexErr("hexadecimal digit expected")
				}
				if lx.cur() != '}' {
					lx.pos++
					lx.lexErr("missing '}' in \\u{xxxx}")
				}
				lx.pos++
				sb.WriteString(utf8Encode(uint32(v)))
			default:
				if isDigit(int(e)) {
					v := 0
					for i := 0; i < 3 && lx.pos < len(lx.src) && isDigit(int(lx.src[lx.pos])); i++ {
						v = v*10 + int(lx.src[lx.pos]-'0')
						lx.pos++
					}
					if v > 255 {
						lx.lexErr("decimal escape too large")
					}
					sb.WriteByte(byte(v))
				} else {
					lx.pos++
					lx.lexErr("invalid escape sequence")
				}
			}
		default:
			sb.WriteByte(c)
			lx.pos++
		}
	}
}

// utf8Encode encodes up to 31-bit values (extended UTF-8, like Lua).
func utf8Encode(x uint32) string {
	if x < 0x80 {
		return string([]byte{byte(x)})
	}
	var buf [8]byte
	n := 1
	mfb := uint32(0x3f)
	for {
		buf[8-n] = byte(0x80 | (x & 0x3f))
		n++
		x >>= 6
		mfb >>= 1
		if x <= mfb {
			break
		}
	}
	buf[8-n] = byte((^mfb << 1) | x)
	return string(buf[8-n:])
}

func (lx *Lexer) readNumber() Token {
	st := lx.pos
	exp1, exp2 := byte('e'), byte('E')
	if lx.src[lx.pos] == '0' && (lx.peek(1) == 'x' || lx.peek(1) == 'X') {
		exp1, exp2 = 'p', 'P'
		lx.pos += 2
	}
	for lx.pos < len(lx.src) {
		c := lx.src[lx.pos]
		if c == exp1 || c == exp2 {
			lx.pos++
			if lx.pos < len(lx.src) && (lx.src[lx.pos] == '+' || lx.src[lx.pos] == '-') {
				lx.pos++
			}
		} else if hexVal(c) >= 0 || c == '.' || isAlpha(int(c)) {
			lx.pos++
		} else {
			break
		}
	}
	text := lx.src[st:lx.pos]
	v, ok := str2number(text)
	if !ok {
		lx.lexErr("malformed number")
	}
	return Token{kind: tkNumber, n: v, line: lx.line, raw: text}
}
