package mal

import (
	"strconv"
	"strings"
)

// PrStr renders v; readably means strings are quoted and escaped.
func PrStr(v Value, readably bool) string {
	var sb strings.Builder
	prInto(&sb, v, readably)
	return sb.String()
}

func prSeq(sb *strings.Builder, open, close string, items []Value, readably bool) {
	sb.WriteString(open)
	for i, it := range items {
		if i > 0 {
			sb.WriteByte(' ')
		}
		prInto(sb, it, readably)
	}
	sb.WriteString(close)
}

func prInto(sb *strings.Builder, v Value, readably bool) {
	switch x := v.(type) {
	case nilT:
		sb.WriteString("nil")
	case bool:
		if x {
			sb.WriteString("true")
		} else {
			sb.WriteString("false")
		}
	case int:
		sb.WriteString(strconv.Itoa(x))
	case Symbol:
		sb.WriteString(string(x))
	case Keyword:
		sb.WriteByte(':')
		sb.WriteString(string(x))
	case string:
		if readably {
			sb.WriteByte('"')
			for _, r := range x {
				switch r {
				case '"':
					sb.WriteString(`\"`)
				case '\\':
					sb.WriteString(`\\`)
				case '\n':
					sb.WriteString(`\n`)
				default:
					sb.WriteRune(r)
				}
			}
			sb.WriteByte('"')
		} else {
			sb.WriteString(x)
		}
	case *List:
		prSeq(sb, "(", ")", x.Items, readably)
	case *Vector:
		prSeq(sb, "[", "]", x.Items, readably)
	case *HashMap:
		sb.WriteByte('{')
		for i, k := range x.Keys {
			if i > 0 {
				sb.WriteByte(' ')
			}
			prInto(sb, k, readably)
			sb.WriteByte(' ')
			prInto(sb, x.Vals[i], readably)
		}
		sb.WriteByte('}')
	case *Func:
		if x.IsMacro {
			sb.WriteString("#<macro>")
		} else {
			sb.WriteString("#<function>")
		}
	case *Atom:
		sb.WriteString("(atom ")
		prInto(sb, x.Val, readably)
		sb.WriteByte(')')
	default:
		sb.WriteString("#<unknown>")
	}
}
