package main

import (
	"encoding/binary"
	"math"
	"strings"
)

func openString(th *Thread) {
	s := newTable(0, 20)
	G.setStr("string", s)
	loadedTable.setStr("string", s)
	stringMeta = newTable(0, 1)
	stringMeta.setStr("__index", s)

	reg(s, "len", func(th *Thread, args []Value) []Value {
		return []Value{int64(len(checkStr(th, args, 0, "len")))}
	})
	reg(s, "sub", func(th *Thread, args []Value) []Value {
		str := checkStr(th, args, 0, "sub")
		l := int64(len(str))
		i := posRelatI(checkInt(th, args, 1, "sub"), l)
		j := getEndPos(optInt(th, args, 2, "sub", -1), l)
		if i > j {
			return []Value{""}
		}
		return []Value{str[i-1 : j]}
	})
	reg(s, "upper", func(th *Thread, args []Value) []Value {
		b := []byte(checkStr(th, args, 0, "upper"))
		for i, c := range b {
			if isLowerC(c) {
				b[i] = c - 32
			}
		}
		return []Value{string(b)}
	})
	reg(s, "lower", func(th *Thread, args []Value) []Value {
		b := []byte(checkStr(th, args, 0, "lower"))
		for i, c := range b {
			if isUpperC(c) {
				b[i] = c + 32
			}
		}
		return []Value{string(b)}
	})
	reg(s, "reverse", func(th *Thread, args []Value) []Value {
		b := []byte(checkStr(th, args, 0, "reverse"))
		for i, j := 0, len(b)-1; i < j; i, j = i+1, j-1 {
			b[i], b[j] = b[j], b[i]
		}
		return []Value{string(b)}
	})
	reg(s, "rep", func(th *Thread, args []Value) []Value {
		str := checkStr(th, args, 0, "rep")
		n := checkInt(th, args, 1, "rep")
		sep := optStr(th, args, 2, "rep", "")
		if n <= 0 {
			return []Value{""}
		}
		if (int64(len(str))+int64(len(sep)))*n > 1<<31 {
			th.rtError("resulting string too large")
		}
		if sep == "" {
			return []Value{strings.Repeat(str, int(n))}
		}
		var b strings.Builder
		for i := int64(0); i < n; i++ {
			if i > 0 {
				b.WriteString(sep)
			}
			b.WriteString(str)
		}
		return []Value{b.String()}
	})
	reg(s, "byte", func(th *Thread, args []Value) []Value {
		str := checkStr(th, args, 0, "byte")
		l := int64(len(str))
		pi := optInt(th, args, 1, "byte", 1)
		i := posRelatI(pi, l)
		j := getEndPos(optInt(th, args, 2, "byte", i), l)
		if i > j {
			return nil
		}
		out := make([]Value, 0, j-i+1)
		for k := i; k <= j; k++ {
			out = append(out, int64(str[k-1]))
		}
		return out
	})
	reg(s, "char", func(th *Thread, args []Value) []Value {
		b := make([]byte, len(args))
		for i := range args {
			c := checkInt(th, args, i, "char")
			if c < 0 || c > 255 {
				argErr(th, i+1, "char", "value out of range")
			}
			b[i] = byte(c)
		}
		return []Value{string(b)}
	})
	reg(s, "format", strFormat)
	reg(s, "find", func(th *Thread, args []Value) []Value { return strFindAux(th, args, true) })
	reg(s, "match", func(th *Thread, args []Value) []Value { return strFindAux(th, args, false) })
	reg(s, "gmatch", strGmatch)
	reg(s, "gsub", strGsub)
	reg(s, "pack", strPack)
	reg(s, "unpack", strUnpack)
	reg(s, "packsize", strPacksize)
}

// ---------- pack / unpack ----------

type packState struct {
	th       *Thread
	fmt      string
	pos      int
	little   bool
	maxAlign int
}

const (
	kInt = iota
	kUint
	kFloat
	kDouble
	kChar
	kString
	kZstr
	kPadding
	kPaddAlign
	kNop
)

func (ps *packState) digit() bool { return ps.pos < len(ps.fmt) && isDigitC(ps.fmt[ps.pos]) }

func (ps *packState) getNum(df int) int {
	if !ps.digit() {
		return df
	}
	a := 0
	for ps.digit() && a <= (math.MaxInt32-9)/10 {
		a = a*10 + int(ps.fmt[ps.pos]-'0')
		ps.pos++
	}
	return a
}

func (ps *packState) getNumLimit(df int) int {
	sz := ps.getNum(df)
	if sz > 16 || sz <= 0 {
		ps.th.rtError("integral size (%d) out of limits [1,16]", sz)
	}
	return sz
}

func (ps *packState) getOption() (opt int, size int) {
	c := ps.fmt[ps.pos]
	ps.pos++
	switch c {
	case 'b':
		return kInt, 1
	case 'B':
		return kUint, 1
	case 'h':
		return kInt, 2
	case 'H':
		return kUint, 2
	case 'l', 'j':
		return kInt, 8
	case 'L', 'J', 'T':
		return kUint, 8
	case 'f':
		return kFloat, 4
	case 'n', 'd':
		return kDouble, 8
	case 'i':
		return kInt, ps.getNumLimit(4)
	case 'I':
		return kUint, ps.getNumLimit(4)
	case 's':
		return kString, ps.getNumLimit(8)
	case 'c':
		sz := ps.getNum(-1)
		if sz == -1 {
			ps.th.rtError("missing size for format option 'c'")
		}
		return kChar, sz
	case 'z':
		return kZstr, 0
	case 'x':
		return kPadding, 1
	case 'X':
		return kPaddAlign, 0
	case ' ':
	case '<':
		ps.little = true
	case '>':
		ps.little = false
	case '=':
		ps.little = true
	case '!':
		ps.maxAlign = ps.getNumLimit(8)
	default:
		ps.th.rtError("invalid format option '%c'", c)
	}
	return kNop, 0
}

// getDetails returns option, size and the padding needed before it at offset total.
func (ps *packState) getDetails(total int) (opt, size, ntoalign int) {
	opt, size = ps.getOption()
	align := size
	if opt == kPaddAlign {
		if ps.pos >= len(ps.fmt) {
			ps.th.argErrPack("invalid next option for option 'X'")
		}
		o2, s2 := ps.getOption()
		align = s2
		if o2 == kChar || align == 0 {
			ps.th.argErrPack("invalid next option for option 'X'")
		}
	}
	if align <= 1 || opt == kChar {
		return opt, size, 0
	}
	if align > ps.maxAlign {
		align = ps.maxAlign
	}
	if align&(align-1) != 0 {
		ps.th.argErrPack("format asks for alignment not power of 2")
	}
	ntoalign = (align - (total & (align - 1))) & (align - 1)
	return
}

func (th *Thread) argErrPack(msg string) {
	th.rtError("bad argument #1 to 'pack' (%s)", msg)
}

func packInt(b []byte, v uint64, size int, little bool, neg bool) []byte {
	buf := make([]byte, size)
	for i := 0; i < size; i++ {
		var by byte
		if i < 8 {
			by = byte(v >> (8 * uint(i)))
		} else if neg {
			by = 0xff
		}
		if little {
			buf[i] = by
		} else {
			buf[size-1-i] = by
		}
	}
	return append(b, buf...)
}

func strPack(th *Thread, args []Value) []Value {
	ps := &packState{th: th, fmt: checkStr(th, args, 0, "pack"), little: true, maxAlign: 1}
	var out []byte
	argi := 0
	for ps.pos < len(ps.fmt) {
		opt, size, nal := ps.getDetails(len(out))
		for i := 0; i < nal; i++ {
			out = append(out, 0)
		}
		switch opt {
		case kInt:
			argi++
			n := checkInt(th, args, argi, "pack")
			if size < 8 {
				lim := int64(1) << uint(size*8-1)
				if !(-lim <= n && n < lim) {
					argErr(th, argi+1, "pack", "integer overflow")
				}
			}
			out = packInt(out, uint64(n), size, ps.little, n < 0)
		case kUint:
			argi++
			n := checkInt(th, args, argi, "pack")
			if size < 8 && uint64(n) >= uint64(1)<<uint(size*8) {
				argErr(th, argi+1, "pack", "unsigned overflow")
			}
			out = packInt(out, uint64(n), size, ps.little, false)
		case kFloat:
			argi++
			f := checkNum(th, args, argi, "pack")
			var buf [4]byte
			if ps.little {
				binary.LittleEndian.PutUint32(buf[:], math.Float32bits(float32(f)))
			} else {
				binary.BigEndian.PutUint32(buf[:], math.Float32bits(float32(f)))
			}
			out = append(out, buf[:]...)
		case kDouble:
			argi++
			f := checkNum(th, args, argi, "pack")
			var buf [8]byte
			if ps.little {
				binary.LittleEndian.PutUint64(buf[:], math.Float64bits(f))
			} else {
				binary.BigEndian.PutUint64(buf[:], math.Float64bits(f))
			}
			out = append(out, buf[:]...)
		case kChar:
			argi++
			str := checkStr(th, args, argi, "pack")
			if len(str) > size {
				argErr(th, argi+1, "pack", "string longer than given size")
			}
			out = append(out, str...)
			for i := len(str); i < size; i++ {
				out = append(out, 0)
			}
		case kString:
			argi++
			str := checkStr(th, args, argi, "pack")
			if size < 8 && uint64(len(str)) >= uint64(1)<<uint(size*8) {
				argErr(th, argi+1, "pack", "string length does not fit in given size")
			}
			out = packInt(out, uint64(len(str)), size, ps.little, false)
			out = append(out, str...)
		case kZstr:
			argi++
			str := checkStr(th, args, argi, "pack")
			if strings.IndexByte(str, 0) >= 0 {
				argErr(th, argi+1, "pack", "string contains zeros")
			}
			out = append(out, str...)
			out = append(out, 0)
		case kPadding:
			out = append(out, 0)
		}
	}
	return []Value{string(out)}
}

func strPacksize(th *Thread, args []Value) []Value {
	ps := &packState{th: th, fmt: checkStr(th, args, 0, "packsize"), little: true, maxAlign: 1}
	total := 0
	for ps.pos < len(ps.fmt) {
		opt, size, nal := ps.getDetails(total)
		if opt == kString || opt == kZstr {
			argErr(th, 1, "packsize", "variable-length format")
		}
		total += nal + size
		if total > math.MaxInt32 {
			argErr(th, 1, "packsize", "format result too large")
		}
	}
	return []Value{int64(total)}
}

func unpackInt(th *Thread, data string, size int, little, signed bool) int64 {
	var res uint64
	limit := size
	if limit > 8 {
		limit = 8
	}
	for i := limit - 1; i >= 0; i-- {
		res <<= 8
		if little {
			res |= uint64(data[i])
		} else {
			res |= uint64(data[size-1-i])
		}
	}
	if size < 8 {
		if signed {
			mask := uint64(1) << uint(size*8-1)
			res = (res ^ mask) - mask
		}
	} else if size > 8 {
		var ext byte
		if signed && int64(res) < 0 {
			ext = 0xff
		}
		for i := limit; i < size; i++ {
			var by byte
			if little {
				by = data[i]
			} else {
				by = data[size-1-i]
			}
			if by != ext {
				th.rtError("%d-byte integer does not fit into Lua Integer", size)
			}
		}
	}
	return int64(res)
}

func strUnpack(th *Thread, args []Value) []Value {
	ps := &packState{th: th, fmt: checkStr(th, args, 0, "unpack"), little: true, maxAlign: 1}
	data := checkStr(th, args, 1, "unpack")
	ld := int64(len(data))
	pos := posRelatI(optInt(th, args, 2, "unpack", 1), ld) - 1
	if pos > ld || pos < 0 {
		argErr(th, 3, "unpack", "initial position out of string")
	}
	p := int(pos)
	var out []Value
	for ps.pos < len(ps.fmt) {
		opt, size, nal := ps.getDetails(p)
		if nal+size > len(data)-p {
			argErr(th, 2, "unpack", "data string too short")
		}
		p += nal
		switch opt {
		case kInt, kUint:
			out = append(out, unpackInt(th, data[p:p+size], size, ps.little, opt == kInt))
		case kFloat:
			var u uint32
			if ps.little {
				u = binary.LittleEndian.Uint32([]byte(data[p : p+4]))
			} else {
				u = binary.BigEndian.Uint32([]byte(data[p : p+4]))
			}
			out = append(out, float64(math.Float32frombits(u)))
		case kDouble:
			var u uint64
			if ps.little {
				u = binary.LittleEndian.Uint64([]byte(data[p : p+8]))
			} else {
				u = binary.BigEndian.Uint64([]byte(data[p : p+8]))
			}
			out = append(out, math.Float64frombits(u))
		case kChar:
			out = append(out, data[p:p+size])
		case kString:
			l := unpackInt(th, data[p:p+size], size, ps.little, false)
			if l < 0 || int64(len(data)-p-size) < l {
				argErr(th, 2, "unpack", "data string too short")
			}
			out = append(out, data[p+size:p+size+int(l)])
			p += int(l)
		case kZstr:
			e := strings.IndexByte(data[p:], 0)
			if e < 0 {
				argErr(th, 2, "unpack", "unfinished string for format 'z'")
			}
			out = append(out, data[p:p+e])
			p += e + 1
		}
		p += size
	}
	return append(out, int64(p+1))
}
