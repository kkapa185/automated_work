// Package tests holds black-box tests: they build the real server binary,
// start it on a random port and talk RESP over TCP.
package tests

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

var binPath string

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "kvbin")
	if err != nil {
		panic(err)
	}
	binPath = filepath.Join(dir, "kvserver")
	// KV_RACE=1 builds the server with the race detector so the integration
	// tests also exercise the server's concurrency under -race.
	args := []string{"build", "-o", binPath}
	if os.Getenv("KV_RACE") != "" {
		args = append(args, "-race")
	}
	out, err := exec.Command("go", append(args, "../cmd/kvserver")...).CombinedOutput()
	if err != nil {
		fmt.Fprintf(os.Stderr, "build failed: %v\n%s", err, out)
		os.Exit(2)
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// Reply types.
type Simple string
type Err string

type Srv struct {
	t    *testing.T
	cmd  *exec.Cmd
	Addr string
	Port int
	Dir  string
}

func freePort(t testing.TB) int {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

// startServer launches the binary; dir "" means a fresh temp dir.
func startServer(t testing.TB, dir string) *Srv {
	if dir == "" {
		dir = t.TempDir()
	}
	port := freePort(t)
	cmd := exec.Command(binPath, "--port", strconv.Itoa(port), "--dir", dir)
	cmd.Stderr = os.Stderr // surfaces race-detector reports
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	s := &Srv{cmd: cmd, Port: port, Addr: fmt.Sprintf("127.0.0.1:%d", port), Dir: dir}
	for i := 0; i < 200; i++ {
		conn, err := net.Dial("tcp", s.Addr)
		if err == nil {
			conn.Close()
			t.Cleanup(s.Kill)
			return s
		}
		time.Sleep(25 * time.Millisecond)
	}
	cmd.Process.Kill()
	t.Fatal("server did not start")
	return nil
}

// startServerCwd starts the binary WITHOUT --dir, with the given working dir.
func startServerCwd(t testing.TB, cwd string) *Srv {
	port := freePort(t)
	cmd := exec.Command(binPath, "--port", strconv.Itoa(port))
	cmd.Dir = cwd
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	s := &Srv{cmd: cmd, Port: port, Addr: fmt.Sprintf("127.0.0.1:%d", port), Dir: cwd}
	for i := 0; i < 200; i++ {
		if conn, err := net.Dial("tcp", s.Addr); err == nil {
			conn.Close()
			t.Cleanup(s.Kill)
			return s
		}
		time.Sleep(25 * time.Millisecond)
	}
	cmd.Process.Kill()
	t.Fatal("server did not start")
	return nil
}

func (s *Srv) Kill() {
	if s.cmd.ProcessState == nil {
		s.cmd.Process.Kill()
		s.cmd.Wait()
	}
}

// Term sends SIGTERM and waits for exit.
func (s *Srv) Term() {
	s.cmd.Process.Signal(syscall.SIGTERM)
	s.cmd.Wait()
}

func (s *Srv) Client(t testing.TB) *C {
	conn, err := net.Dial("tcp", s.Addr)
	if err != nil {
		t.Fatal(err)
	}
	c := &C{t: t, conn: conn, r: bufio.NewReaderSize(conn, 1<<16)}
	t.Cleanup(func() { conn.Close() })
	return c
}

// C is a minimal RESP2 client.
type C struct {
	t    testing.TB
	conn net.Conn
	r    *bufio.Reader
}

func enc(args []any) []byte {
	b := []byte("*" + strconv.Itoa(len(args)) + "\r\n")
	for _, a := range args {
		var s string
		switch v := a.(type) {
		case string:
			s = v
		case []byte:
			s = string(v)
		default:
			s = fmt.Sprint(v)
		}
		b = append(b, fmt.Sprintf("$%d\r\n%s\r\n", len(s), s)...)
	}
	return b
}

func (c *C) Send(args ...any) {
	c.conn.Write(enc(args))
}

func (c *C) Raw(s string) { c.conn.Write([]byte(s)) }

// Read reads one reply with a timeout; it fails the test on I/O errors.
func (c *C) Read() any {
	v, err := c.TryRead(5 * time.Second)
	if err != nil {
		c.t.Helper()
		c.t.Fatalf("read: %v", err)
	}
	return v
}

func (c *C) TryRead(d time.Duration) (any, error) {
	c.conn.SetReadDeadline(time.Now().Add(d))
	return readReply(c.r)
}

func (c *C) Do(args ...any) any {
	c.t.Helper()
	c.Send(args...)
	return c.Read()
}

func readReply(r *bufio.Reader) (any, error) {
	line, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	if len(line) < 3 {
		return nil, fmt.Errorf("short line %q", line)
	}
	body := line[1 : len(line)-2]
	switch line[0] {
	case '+':
		return Simple(body), nil
	case '-':
		return Err(body), nil
	case ':':
		n, _ := strconv.ParseInt(body, 10, 64)
		return n, nil
	case '$':
		n, _ := strconv.Atoi(body)
		if n < 0 {
			return nil, nil
		}
		buf := make([]byte, n+2)
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, err
		}
		return string(buf[:n]), nil
	case '*':
		n, _ := strconv.Atoi(body)
		if n < 0 {
			return nil, nil
		}
		out := make([]any, n)
		for i := range out {
			if out[i], err = readReply(r); err != nil {
				return nil, err
			}
		}
		return out, nil
	}
	return nil, fmt.Errorf("bad reply %q", line)
}

func norm(v any) any {
	switch x := v.(type) {
	case int:
		return int64(x)
	case []any:
		out := make([]any, len(x))
		for i := range x {
			out[i] = norm(x[i])
		}
		return out
	}
	return v
}

var (
	OK  = Simple("OK")
	Nil any
)

// expect runs a command and asserts the exact reply.
func expect(t testing.TB, c *C, want any, args ...any) {
	t.Helper()
	got := c.Do(args...)
	if !reflect.DeepEqual(got, norm(want)) {
		t.Fatalf("%v\n got:  %#v\n want: %#v", args, got, norm(want))
	}
}

// arr is a shorthand for []any.
func arr(v ...any) []any { return v }

// sortedStrings extracts a reply array of bulk strings.
func strs(t testing.TB, v any) []string {
	t.Helper()
	a, ok := v.([]any)
	if !ok {
		t.Fatalf("not an array: %#v", v)
	}
	out := make([]string, len(a))
	for i, x := range a {
		s, ok := x.(string)
		if !ok {
			t.Fatalf("element %d not bulk: %#v", i, x)
		}
		out[i] = s
	}
	return out
}

func newSrv(t *testing.T) (*Srv, *C) {
	s := startServer(t, "")
	return s, s.Client(t)
}

func equal(a, b any) bool { return reflect.DeepEqual(norm(a), norm(b)) }

func contains(s, sub string) bool { return strings.Contains(s, sub) }
