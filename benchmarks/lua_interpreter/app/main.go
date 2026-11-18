package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"
)

var stdout = bufio.NewWriterSize(os.Stdout, 65536)
var stdinReader = bufio.NewReaderSize(os.Stdin, 65536)

func readAllStdin() ([]byte, error) { return io.ReadAll(stdinReader) }

func exitWith(code int) {
	stdout.Flush()
	os.Exit(code)
}

func errorMessage(th *Thread, v Value) string {
	switch x := v.(type) {
	case string:
		return x
	case int64, float64:
		return numToString(x)
	}
	if th.metaOf(v, "__tostring") != nil {
		return th.tostr(v)
	}
	return fmt.Sprintf("(error object is a %s value)", typeName(v))
}

func main() {
	debug.SetMaxStack(3 << 30)
	debug.SetGCPercent(400)
	args := os.Args[1:]
	th := &Thread{}
	openBase(th)
	openLibs(th)

	script := ""
	haveScript := false
	var exprs []string
	i := 0
	for ; i < len(args); i++ {
		a := args[i]
		if a == "-e" && i+1 < len(args) {
			exprs = append(exprs, args[i+1])
			i++
			continue
		}
		if a == "-v" {
			fmt.Println("Lua 5.4")
			continue
		}
		if a == "--" {
			i++
			break
		}
		break
	}
	if i < len(args) {
		script = args[i]
		haveScript = true
		i++
	}
	var rest []string
	if i <= len(args) {
		rest = args[i:]
	}
	argT := newTable(len(rest), 2)
	if haveScript {
		argT.setInt(0, script)
	} else {
		argT.setInt(0, "lua")
	}
	argT.setInt(-1, "lua")
	for j, a := range rest {
		argT.setInt(int64(j+1), a)
	}
	G.setStr("arg", argT)

	code := 0
	func() {
		defer func() {
			if r := recover(); r != nil {
				le := toLuaError(r)
				if le == nil {
					panic(r)
				}
				msg := errorMessage(th, le.value)
				tb := th.traceback("", th.top)
				stdout.Flush()
				fmt.Fprintf(os.Stderr, "lua: %s\n%s\n", msg, tb)
				code = 1
			}
		}()
		for _, e := range exprs {
			f, err := th.loadChunk(e, "=(command line)", G)
			if err != nil {
				panic(&LuaError{value: err.Error()})
			}
			th.call(f, nil)
		}
		if !haveScript && len(exprs) > 0 {
			return
		}
		var src, cn string
		var err error
		if !haveScript || script == "-" {
			src, err = readFileChunk("")
			cn = "=stdin"
		} else {
			src, err = readFileChunk(script)
			cn = "@" + script
		}
		if err != nil {
			stdout.Flush()
			fmt.Fprintf(os.Stderr, "lua: cannot open %s\n", script)
			code = 1
			return
		}
		if haveScript && script != "-" {
			dir := filepath.Dir(script)
			if dir != "." {
				p, _ := packageTable.getStr("path").(string)
				packageTable.setStr("path", p+";"+strings.TrimRight(dir, "/")+"/?.lua;"+strings.TrimRight(dir, "/")+"/?/init.lua")
			}
		}
		f, err := th.loadChunk(src, cn, G)
		if err != nil {
			panic(&LuaError{value: err.Error()})
		}
		vargs := make([]Value, len(rest))
		for j, a := range rest {
			vargs[j] = a
		}
		th.call(f, vargs)
	}()
	exitWith(code)
}
