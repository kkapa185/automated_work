package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
)

type LuaFile struct {
	f      *os.File
	rd     *bufio.Reader
	wr     *bufio.Writer
	closed bool
	std    int // 1 stdin, 2 stdout, 3 stderr
}

var fileMeta *Table
var defaultIn, defaultOut *Userdata
var stdinUD, stdoutUD, stderrUD *Userdata

func newFileUD(lf *LuaFile) *Userdata { return &Userdata{meta: fileMeta, data: lf} }

func (lf *LuaFile) prepRead() {
	if lf.wr != nil {
		lf.wr.Flush()
	}
}

func (lf *LuaFile) prepWrite() {
	if lf.rd != nil && lf.std == 0 && lf.rd.Buffered() > 0 {
		lf.f.Seek(-int64(lf.rd.Buffered()), io.SeekCurrent)
		lf.rd.Reset(lf.f)
	}
}

func (lf *LuaFile) write(s string) error {
	switch lf.std {
	case 3:
		stdout.Flush()
		_, err := os.Stderr.WriteString(s)
		return err
	}
	lf.prepWrite()
	if lf.wr == nil {
		_, err := lf.f.Write(nil)
		if err == nil {
			err = fmt.Errorf("bad file descriptor")
		}
		return err
	}
	_, err := lf.wr.WriteString(s)
	return err
}

func (lf *LuaFile) closeFile() error {
	lf.closed = true
	if lf.wr != nil {
		lf.wr.Flush()
	}
	if lf.std != 0 {
		return nil
	}
	return lf.f.Close()
}

func toFileUD(th *Thread, args []Value, i int, fname string) *LuaFile {
	if i < len(args) {
		if ud, ok := args[i].(*Userdata); ok {
			if lf, ok := ud.data.(*LuaFile); ok {
				return lf
			}
		}
	}
	typeErr(th, args, i, fname, "FILE*")
	return nil
}

func checkOpenFile(th *Thread, args []Value, i int, fname string) *LuaFile {
	lf := toFileUD(th, args, i, fname)
	if lf.closed {
		th.rtError("attempt to use a closed file")
	}
	return lf
}

func readNumber(rd *bufio.Reader) Value {
	var sb strings.Builder
	peek := func() int {
		b, err := rd.Peek(1)
		if err != nil {
			return -1
		}
		return int(b[0])
	}
	take := func() { b, _ := rd.ReadByte(); sb.WriteByte(b) }
	for c := peek(); c >= 0 && isSpaceC(byte(c)); c = peek() {
		rd.ReadByte()
	}
	accept := func(set string) bool {
		c := peek()
		if c >= 0 && strings.IndexByte(set, byte(c)) >= 0 && sb.Len() < 200 {
			take()
			return true
		}
		return false
	}
	digits := func(hex bool) int {
		n := 0
		for {
			c := peek()
			if c < 0 || sb.Len() >= 200 {
				return n
			}
			if (hex && hexVal(byte(c)) >= 0) || (!hex && isDigitC(byte(c))) {
				take()
				n++
			} else {
				return n
			}
		}
	}
	accept("+-")
	hex := false
	count := 0
	if accept("0") {
		if accept("xX") {
			hex = true
		} else {
			count = 1
		}
	}
	count += digits(hex)
	if accept(".") {
		count += digits(hex)
	}
	if count > 0 {
		exp := "eE"
		if hex {
			exp = "pP"
		}
		if accept(exp) {
			accept("+-")
			digits(false)
		}
	}
	v, ok := str2number(sb.String())
	if !ok {
		return nil
	}
	return v
}

func readFormats(th *Thread, lf *LuaFile, formats []Value, argBase int, fname string) []Value {
	lf.prepRead()
	rd := lf.rd
	if rd == nil {
		return []Value{nil, "Bad file descriptor", int64(9)}
	}
	if len(formats) == 0 {
		formats = []Value{"l"}
	}
	var out []Value
	for i, f := range formats {
		var v Value
		switch x := f.(type) {
		case int64, float64:
			n, ok := toInteger(x)
			if !ok {
				argErr(th, argBase+i+1, fname, "number has no integer representation")
			}
			if n == 0 {
				if _, err := rd.Peek(1); err == nil {
					v = ""
				}
			} else {
				buf := make([]byte, n)
				k, _ := io.ReadFull(rd, buf)
				if k > 0 {
					v = string(buf[:k])
				}
			}
		case string:
			p := strings.TrimPrefix(x, "*")
			if p == "" {
				argErr(th, argBase+i+1, fname, "invalid format")
			}
			switch p[0] {
			case 'n':
				v = readNumber(rd)
			case 'l', 'L':
				s, err := rd.ReadString('\n')
				if err != nil && s == "" {
					v = nil
				} else {
					if p[0] == 'l' {
						s = strings.TrimSuffix(s, "\n")
					}
					v = s
				}
			case 'a':
				b, _ := io.ReadAll(rd)
				v = string(b)
			default:
				argErr(th, argBase+i+1, fname, "invalid format")
			}
		default:
			argErr(th, argBase+i+1, fname, "invalid format")
		}
		out = append(out, v)
		if v == nil {
			break
		}
	}
	return out
}

func writeValues(th *Thread, ud *Userdata, lf *LuaFile, args []Value, base int, fname string) []Value {
	for i, a := range args {
		var s string
		switch x := a.(type) {
		case string:
			s = x
		case int64, float64:
			s = numToString(x)
		default:
			typeErr(th, args, i, fname, "string")
		}
		if err := lf.write(s); err != nil {
			return failResult(err, "")
		}
	}
	return []Value{ud}
}

func openFile(name, mode string) (*LuaFile, error) {
	flags := 0
	plus := strings.Contains(mode, "+")
	switch mode[0] {
	case 'r':
		flags = os.O_RDONLY
		if plus {
			flags = os.O_RDWR
		}
	case 'w':
		flags = os.O_WRONLY | os.O_CREATE | os.O_TRUNC
		if plus {
			flags = os.O_RDWR | os.O_CREATE | os.O_TRUNC
		}
	case 'a':
		flags = os.O_WRONLY | os.O_CREATE | os.O_APPEND
		if plus {
			flags = os.O_RDWR | os.O_CREATE | os.O_APPEND
		}
	}
	f, err := os.OpenFile(name, flags, 0666)
	if err != nil {
		return nil, err
	}
	if st, err := f.Stat(); err == nil && st.IsDir() && mode[0] != 'r' {
		f.Close()
		return nil, fmt.Errorf("is a directory")
	}
	lf := &LuaFile{f: f, rd: bufio.NewReader(f)}
	if flags&(os.O_WRONLY|os.O_RDWR) != 0 {
		lf.wr = bufio.NewWriter(f)
	}
	return lf, nil
}

func validMode(m string) bool {
	if m == "" || strings.IndexByte("rwa", m[0]) < 0 {
		return false
	}
	m = m[1:]
	m = strings.TrimPrefix(m, "+")
	return strings.Trim(m, "b") == ""
}

func openIO(th *Thread) {
	io_ := newTable(0, 16)
	G.setStr("io", io_)
	loadedTable.setStr("io", io_)

	methods := newTable(0, 12)
	fileMeta = newTable(0, 6)
	fileMeta.setStr("__index", methods)
	fileMeta.setStr("__name", "FILE*")

	stdinUD = newFileUD(&LuaFile{f: os.Stdin, rd: stdinReader, std: 1})
	stdoutUD = newFileUD(&LuaFile{f: os.Stdout, wr: stdout, std: 2})
	stderrUD = newFileUD(&LuaFile{f: os.Stderr, std: 3})
	defaultIn, defaultOut = stdinUD, stdoutUD
	io_.setStr("stdin", stdinUD)
	io_.setStr("stdout", stdoutUD)
	io_.setStr("stderr", stderrUD)

	closeFn := func(th *Thread, ud *Userdata, lf *LuaFile) []Value {
		if lf.std != 0 {
			if lf.wr != nil {
				lf.wr.Flush()
			}
			return []Value{nil, "cannot close standard file"}
		}
		if err := lf.closeFile(); err != nil {
			return failResult(err, "")
		}
		return []Value{true}
	}
	fileMeta.setStr("__tostring", &GoFunction{name: "tostring", fn: func(th *Thread, args []Value) []Value {
		lf := toFileUD(th, args, 0, "tostring")
		if lf.closed {
			return []Value{"file (closed)"}
		}
		return []Value{fmt.Sprintf("file (%p)", lf)}
	}})
	gc := &GoFunction{name: "close", fn: func(th *Thread, args []Value) []Value {
		lf := toFileUD(th, args, 0, "close")
		if !lf.closed && lf.std == 0 {
			lf.closeFile()
		}
		return nil
	}}
	fileMeta.setStr("__gc", gc)
	fileMeta.setStr("__close", gc)

	reg(methods, "close", func(th *Thread, args []Value) []Value {
		lf := checkOpenFile(th, args, 0, "close")
		return closeFn(th, args[0].(*Userdata), lf)
	})
	reg(methods, "read", func(th *Thread, args []Value) []Value {
		lf := checkOpenFile(th, args, 0, "read")
		return readFormats(th, lf, args[1:], 1, "read")
	})
	reg(methods, "write", func(th *Thread, args []Value) []Value {
		lf := checkOpenFile(th, args, 0, "write")
		return writeValues(th, args[0].(*Userdata), lf, args[1:], 1, "write")
	})
	reg(methods, "flush", func(th *Thread, args []Value) []Value {
		lf := checkOpenFile(th, args, 0, "flush")
		if lf.wr != nil {
			lf.wr.Flush()
		}
		return []Value{args[0]}
	})
	reg(methods, "setvbuf", func(th *Thread, args []Value) []Value {
		checkOpenFile(th, args, 0, "setvbuf")
		return []Value{true}
	})
	reg(methods, "seek", func(th *Thread, args []Value) []Value {
		lf := checkOpenFile(th, args, 0, "seek")
		whence := optStr(th, args, 1, "seek", "cur")
		off := optInt(th, args, 2, "seek", 0)
		var w int
		switch whence {
		case "set":
			w = io.SeekStart
		case "cur":
			w = io.SeekCurrent
		case "end":
			w = io.SeekEnd
		default:
			argErr(th, 2, "seek", "invalid option '"+whence+"'")
		}
		if lf.wr != nil {
			lf.wr.Flush()
		}
		if lf.rd != nil && w == io.SeekCurrent {
			off -= int64(lf.rd.Buffered())
		}
		pos, err := lf.f.Seek(off, w)
		if err != nil {
			return failResult(err, "")
		}
		if lf.rd != nil {
			lf.rd.Reset(lf.f)
		}
		return []Value{pos}
	})
	linesIter := func(lf *LuaFile, formats []Value, closeAtEOF bool) *GoFunction {
		fm := append([]Value(nil), formats...)
		return &GoFunction{name: "lines_iter", fn: func(th *Thread, _ []Value) []Value {
			if lf.closed {
				th.rtError("file is already closed")
			}
			r := readFormats(th, lf, fm, 1, "lines")
			if len(r) == 0 || r[0] == nil {
				if len(r) > 1 {
					if s, ok := r[1].(string); ok {
						th.rtError("%s", s)
					}
				}
				if closeAtEOF {
					lf.closeFile()
				}
				return []Value{nil}
			}
			return r
		}}
	}
	reg(methods, "lines", func(th *Thread, args []Value) []Value {
		lf := checkOpenFile(th, args, 0, "lines")
		return []Value{linesIter(lf, args[1:], false)}
	})

	reg(io_, "open", func(th *Thread, args []Value) []Value {
		name := checkStr(th, args, 0, "open")
		mode := optStr(th, args, 1, "open", "r")
		if !validMode(mode) {
			argErr(th, 2, "open", "invalid mode")
		}
		lf, err := openFile(name, mode)
		if err != nil {
			return failResult(err, name)
		}
		return []Value{newFileUD(lf)}
	})
	reg(io_, "close", func(th *Thread, args []Value) []Value {
		if len(args) == 0 {
			lf := defaultOut.data.(*LuaFile)
			return closeFn(th, defaultOut, lf)
		}
		lf := checkOpenFile(th, args, 0, "close")
		return closeFn(th, args[0].(*Userdata), lf)
	})
	reg(io_, "read", func(th *Thread, args []Value) []Value {
		lf := defaultIn.data.(*LuaFile)
		if lf.closed {
			th.rtError("default input file is closed")
		}
		if lf.std == 1 {
			stdout.Flush()
		}
		return readFormats(th, lf, args, 0, "read")
	})
	reg(io_, "write", func(th *Thread, args []Value) []Value {
		lf := defaultOut.data.(*LuaFile)
		if lf.closed {
			th.rtError("default output file is closed")
		}
		return writeValues(th, defaultOut, lf, args, 0, "write")
	})
	reg(io_, "lines", func(th *Thread, args []Value) []Value {
		if len(args) == 0 || args[0] == nil {
			lf := defaultIn.data.(*LuaFile)
			return []Value{linesIter(lf, nil, false)}
		}
		name := checkStr(th, args, 0, "lines")
		lf, err := openFile(name, "r")
		if err != nil {
			msg, _ := osErr(err, name)
			th.rtError("%s", msg)
		}
		ud := newFileUD(lf)
		return []Value{linesIter(lf, args[1:], true), nil, nil, ud}
	})
	setDefault := func(name string, mode string, cur **Userdata) {
		reg(io_, name, func(th *Thread, args []Value) []Value {
			if len(args) > 0 && args[0] != nil {
				if s, ok := args[0].(string); ok {
					lf, err := openFile(s, mode)
					if err != nil {
						msg, _ := osErr(err, s)
						th.rtError("%s", msg)
					}
					*cur = newFileUD(lf)
				} else {
					toFileUD(th, args, 0, name)
					*cur = args[0].(*Userdata)
				}
			}
			return []Value{*cur}
		})
	}
	setDefault("input", "r", &defaultIn)
	setDefault("output", "w", &defaultOut)
	reg(io_, "type", func(th *Thread, args []Value) []Value {
		checkAny(th, args, 0, "type")
		if ud, ok := args[0].(*Userdata); ok {
			if lf, ok := ud.data.(*LuaFile); ok {
				if lf.closed {
					return []Value{"closed file"}
				}
				return []Value{"file"}
			}
		}
		return []Value{nil}
	})
	reg(io_, "tmpfile", func(th *Thread, args []Value) []Value {
		f, err := os.CreateTemp("", "lua_tmp")
		if err != nil {
			return failResult(err, "")
		}
		os.Remove(f.Name())
		return []Value{newFileUD(&LuaFile{f: f, rd: bufio.NewReader(f), wr: bufio.NewWriter(f)})}
	})
	reg(io_, "popen", func(th *Thread, args []Value) []Value {
		th.rtError("'popen' not supported")
		return nil
	})
}
