package server

import (
	"bufio"
	"bytes"
	"io"
	"strconv"
)

const (
	maxBulkLen   = 512 * 1024 * 1024
	maxMultiBulk = 1024 * 1024
	maxInlineLen = 64 * 1024
)

// protoErr is a RESP protocol violation; the connection is closed after replying.
type protoErr struct{ msg string }

func (e *protoErr) Error() string { return e.msg }

// readLine returns one line without its terminator (\r\n or \n). The result is
// only valid until the next read.
func readLine(r *bufio.Reader, limit int, tooBig string) ([]byte, error) {
	var acc []byte
	for {
		chunk, err := r.ReadSlice('\n')
		if err == bufio.ErrBufferFull {
			acc = append(acc, chunk...)
			if len(acc) >= limit {
				return nil, &protoErr{tooBig}
			}
			continue
		}
		if err != nil {
			return nil, err
		}
		line := chunk
		if acc != nil {
			acc = append(acc, chunk...)
			line = acc
		}
		if len(line) > limit+2 {
			return nil, &protoErr{tooBig}
		}
		line = line[:len(line)-1]
		if n := len(line); n > 0 && line[n-1] == '\r' {
			line = line[:n-1]
		}
		return line, nil
	}
}

// readCommand reads one command. It returns (nil, nil) for an empty command
// (blank inline line or "*0"/"*-1"), which callers must skip.
func readCommand(r *bufio.Reader) ([][]byte, error) {
	b, err := r.Peek(1)
	if err != nil {
		return nil, err
	}
	if b[0] == '*' {
		return readMultiBulk(r)
	}
	line, err := readLine(r, maxInlineLen, "too big inline request")
	if err != nil {
		return nil, err
	}
	args, ok := splitArgs(line)
	if !ok {
		return nil, &protoErr{"unbalanced quotes in request"}
	}
	if len(args) == 0 {
		return nil, nil
	}
	return args, nil
}

func readMultiBulk(r *bufio.Reader) ([][]byte, error) {
	line, err := readLine(r, maxInlineLen, "too big mbulk count string")
	if err != nil {
		return nil, err
	}
	n, ok := parseInt64(line[1:])
	if !ok || n > maxMultiBulk {
		return nil, &protoErr{"invalid multibulk length"}
	}
	if n <= 0 {
		return nil, nil
	}
	args := make([][]byte, 0, min(int(n), 1024))
	for i := int64(0); i < n; i++ {
		line, err := readLine(r, maxInlineLen, "too big bulk count string")
		if err != nil {
			return nil, err
		}
		if len(line) == 0 || line[0] != '$' {
			c := byte(0)
			if len(line) > 0 {
				c = line[0]
			}
			return nil, &protoErr{"expected '$', got '" + string([]byte{c}) + "'"}
		}
		l, ok := parseInt64(line[1:])
		if !ok || l < 0 || l > maxBulkLen {
			return nil, &protoErr{"invalid bulk length"}
		}
		data, err := readN(r, int(l))
		if err != nil {
			return nil, err
		}
		var crlf [2]byte
		if _, err := io.ReadFull(r, crlf[:]); err != nil {
			return nil, err
		}
		args = append(args, data)
	}
	return args, nil
}

// readN reads exactly n bytes, growing the buffer progressively so a bogus
// huge length header cannot force a giant allocation up front.
func readN(r *bufio.Reader, n int) ([]byte, error) {
	const chunk = 1 << 20
	if n <= chunk {
		buf := make([]byte, n)
		_, err := io.ReadFull(r, buf)
		return buf, err
	}
	buf := make([]byte, 0, chunk)
	for len(buf) < n {
		step := min(n-len(buf), chunk*4)
		old := len(buf)
		buf = append(buf, make([]byte, step)...)
		if _, err := io.ReadFull(r, buf[old:]); err != nil {
			return nil, err
		}
	}
	return buf, nil
}

func isSpace(c byte) bool {
	return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\v' || c == '\f'
}

func hexVal(c byte) (byte, bool) {
	switch {
	case c >= '0' && c <= '9':
		return c - '0', true
	case c >= 'a' && c <= 'f':
		return c - 'a' + 10, true
	case c >= 'A' && c <= 'F':
		return c - 'A' + 10, true
	}
	return 0, false
}

// splitArgs tokenises an inline command with shell-like quoting.
func splitArgs(line []byte) ([][]byte, bool) {
	var args [][]byte
	i := 0
	for {
		for i < len(line) && isSpace(line[i]) {
			i++
		}
		if i >= len(line) {
			return args, true
		}
		var cur []byte
		switch line[i] {
		case '"':
			i++
			closed := false
			for i < len(line) {
				c := line[i]
				if c == '\\' && i+3 < len(line) && line[i+1] == 'x' {
					h, ok1 := hexVal(line[i+2])
					l, ok2 := hexVal(line[i+3])
					if ok1 && ok2 {
						cur = append(cur, h<<4|l)
						i += 4
						continue
					}
				}
				if c == '\\' && i+1 < len(line) {
					i++
					switch line[i] {
					case 'n':
						cur = append(cur, '\n')
					case 'r':
						cur = append(cur, '\r')
					case 't':
						cur = append(cur, '\t')
					case 'b':
						cur = append(cur, '\b')
					case 'a':
						cur = append(cur, 7)
					default:
						cur = append(cur, line[i])
					}
					i++
					continue
				}
				if c == '"' {
					i++
					if i < len(line) && !isSpace(line[i]) {
						return nil, false
					}
					closed = true
					break
				}
				cur = append(cur, c)
				i++
			}
			if !closed {
				return nil, false
			}
		case '\'':
			i++
			closed := false
			for i < len(line) {
				c := line[i]
				if c == '\\' && i+1 < len(line) && line[i+1] == '\'' {
					cur = append(cur, '\'')
					i += 2
					continue
				}
				if c == '\'' {
					i++
					if i < len(line) && !isSpace(line[i]) {
						return nil, false
					}
					closed = true
					break
				}
				cur = append(cur, c)
				i++
			}
			if !closed {
				return nil, false
			}
		default:
			for i < len(line) && !isSpace(line[i]) {
				cur = append(cur, line[i])
				i++
			}
		}
		if cur == nil {
			cur = []byte{}
		}
		args = append(args, cur)
	}
}

// ---- reply writers (append to the client's pending buffer) ----

func appendInt(b []byte, prefix byte, n int64) []byte {
	b = append(b, prefix)
	b = strconv.AppendInt(b, n, 10)
	return append(b, '\r', '\n')
}

func (c *Client) addSimple(s string) {
	c.buf = append(c.buf, '+')
	c.buf = append(c.buf, s...)
	c.buf = append(c.buf, '\r', '\n')
}

// addErr writes an error; msg includes its code prefix, e.g. "ERR syntax error".
func (c *Client) addErr(msg string) {
	c.buf = append(c.buf, '-')
	c.buf = append(c.buf, msg...)
	c.buf = append(c.buf, '\r', '\n')
}

func (c *Client) addInt(n int64) { c.buf = appendInt(c.buf, ':', n) }

func (c *Client) addBool(b bool) {
	if b {
		c.addInt(1)
	} else {
		c.addInt(0)
	}
}

func (c *Client) addBulk(b []byte) {
	c.buf = appendInt(c.buf, '$', int64(len(b)))
	c.buf = append(c.buf, b...)
	c.buf = append(c.buf, '\r', '\n')
}

func (c *Client) addBulkStr(s string) {
	c.buf = appendInt(c.buf, '$', int64(len(s)))
	c.buf = append(c.buf, s...)
	c.buf = append(c.buf, '\r', '\n')
}

func (c *Client) addNil()      { c.buf = append(c.buf, "$-1\r\n"...) }
func (c *Client) addNilArray() { c.buf = append(c.buf, "*-1\r\n"...) }
func (c *Client) addArrayLen(n int) {
	c.buf = appendInt(c.buf, '*', int64(n))
}
func (c *Client) addEmptyArray() { c.buf = append(c.buf, "*0\r\n"...) }

func (c *Client) addDouble(f float64) { c.addBulkStr(formatDouble(f)) }

func (c *Client) addBulkArray(items [][]byte) {
	c.addArrayLen(len(items))
	for _, it := range items {
		c.addBulk(it)
	}
}

var _ = bytes.Equal
