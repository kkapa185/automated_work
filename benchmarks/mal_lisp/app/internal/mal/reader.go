package mal

import (
	"regexp"
	"strconv"
	"strings"
)

var tokenRe = regexp.MustCompile("[\\s,]*(~@|[\\[\\]{}()'`~^@]|\"(?:\\\\.|[^\\\\\"])*\"?|;.*|[^\\s\\[\\]{}('\"`,;)]*)")
var intRe = regexp.MustCompile(`^-?[0-9]+$`)

// ErrBlank is the panic payload used when the input holds no form at all
// (empty line or only a comment); the REPL silently continues.
type blankInput struct{}

// IsBlank reports whether a recovered panic value means "no input".
func IsBlank(r interface{}) bool { _, ok := r.(blankInput); return ok }

type reader struct {
	toks []string
	pos  int
}

func (r *reader) peek() (string, bool) {
	if r.pos < len(r.toks) {
		return r.toks[r.pos], true
	}
	return "", false
}

func (r *reader) next() string {
	t := r.toks[r.pos]
	r.pos++
	return t
}

func tokenize(s string) []string {
	var out []string
	for _, m := range tokenRe.FindAllStringSubmatch(s, -1) {
		t := m[1]
		if t == "" || t[0] == ';' {
			continue
		}
		out = append(out, t)
	}
	return out
}

// ReadStr parses the first form in s. If s holds no form it panics with a
// blank-input marker (see IsBlank).
func ReadStr(s string) Value {
	r := &reader{toks: tokenize(s)}
	if len(r.toks) == 0 {
		panic(blankInput{})
	}
	return r.readForm()
}

func (r *reader) readForm() Value {
	t, ok := r.peek()
	if !ok {
		Throw("unbalanced input: unexpected end of input (EOF)")
	}
	switch t {
	case "(":
		r.next()
		return &List{Items: r.readSeq(")"), Meta: Nil}
	case "[":
		r.next()
		return &Vector{Items: r.readSeq("]"), Meta: Nil}
	case "{":
		r.next()
		items := r.readSeq("}")
		if len(items)%2 != 0 {
			Throw("hash-map literal needs an even number of forms")
		}
		h := NewHashMap()
		for i := 0; i < len(items); i += 2 {
			h.Set(items[i], items[i+1])
		}
		return h
	case ")", "]", "}":
		Throw("unbalanced input: unexpected '%s'", t)
	case "'":
		return r.wrap("quote")
	case "`":
		return r.wrap("quasiquote")
	case "~":
		return r.wrap("unquote")
	case "~@":
		return r.wrap("splice-unquote")
	case "@":
		return r.wrap("deref")
	case "^":
		r.next()
		meta := r.readForm()
		form := r.readForm()
		return NewList(Symbol("with-meta"), form, meta)
	}
	r.next()
	return readAtom(t)
}

func (r *reader) wrap(name string) Value {
	r.next()
	return NewList(Symbol(name), r.readForm())
}

func (r *reader) readSeq(end string) []Value {
	items := []Value{}
	for {
		t, ok := r.peek()
		if !ok {
			Throw("unbalanced input: expected '%s', got EOF", end)
		}
		if t == end {
			r.next()
			return items
		}
		items = append(items, r.readForm())
	}
}

func readAtom(t string) Value {
	switch {
	case t == "nil":
		return Nil
	case t == "true":
		return true
	case t == "false":
		return false
	case t[0] == '"':
		return readString(t)
	case t[0] == ':':
		return Keyword(t[1:])
	case intRe.MatchString(t):
		n, err := strconv.Atoi(t)
		if err != nil {
			Throw("integer out of range: %s", t)
		}
		return n
	}
	return Symbol(t)
}

func readString(t string) string {
	if len(t) < 2 || t[len(t)-1] != '"' {
		Throw("unbalanced string: expected '\"', got EOF")
	}
	// A trailing quote preceded by an odd number of backslashes is escaped.
	body := t[1 : len(t)-1]
	bs := 0
	for i := len(body) - 1; i >= 0 && body[i] == '\\'; i-- {
		bs++
	}
	if bs%2 == 1 {
		Throw("unbalanced string: expected '\"', got EOF")
	}
	var sb strings.Builder
	for i := 0; i < len(body); i++ {
		c := body[i]
		if c == '\\' && i+1 < len(body) {
			i++
			switch body[i] {
			case 'n':
				sb.WriteByte('\n')
			default:
				sb.WriteByte(body[i])
			}
			continue
		}
		sb.WriteByte(c)
	}
	return sb.String()
}
