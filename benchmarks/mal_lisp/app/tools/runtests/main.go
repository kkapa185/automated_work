// runtests executes mal test files (the ";=>" format) against a REPL.
//
// Test file format: a line starting with ";;" is a comment; any other
// non-blank line is an input line fed to the REPL. The lines that follow it
// describe the expected output: plain lines are expected stdout lines,
// ";text" is an expected stdout line (so empty output lines are expressible),
// ";=>text" is the expected final result line, ";/regex" is a regex that must
// match the whole output of that input. ";>>>" lines are directives (ignored).
package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var stepOrder = []string{"step0_repl", "step1_read_print", "step2_eval", "step3_env", "step4_if_fn_do",
	"step5_tco", "step6_file", "step7_quote", "step8_macros", "step9_try", "stepA_mal"}

type testCase struct {
	file   string
	line   int
	input  string
	exact  []string // expected output lines (plain lines and the ;=> line)
	regex  []string
	hasEx  bool
	closed bool
}

func parse(path string) []*testCase {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	defer f.Close()
	var cases []*testCase
	var cur *testCase
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	n := 0
	for sc.Scan() {
		n++
		l := sc.Text()
		switch {
		case strings.HasPrefix(l, ";;"), strings.HasPrefix(l, ";>>>"):
		case strings.HasPrefix(l, ";=>"):
			if cur != nil {
				cur.exact = append(cur.exact, l[3:])
				cur.hasEx = true
				cur.closed = true
			}
		case strings.HasPrefix(l, ";/"):
			if cur != nil {
				cur.regex = append(cur.regex, l[2:])
				cur.closed = true
			}
		case strings.HasPrefix(l, ";"):
			// ";text" is an expected output line (text may be empty).
			if cur != nil && !cur.closed {
				cur.exact = append(cur.exact, l[1:])
			}
		case strings.TrimSpace(l) == "":
			cur = nil
		default:
			// Before the ";=>" / ";/" line a plain line is expected output;
			// afterwards (or with no open case) it is a new input line.
			if cur != nil && !cur.closed {
				cur.exact = append(cur.exact, l)
			} else {
				cases = append(cases, &testCase{file: path, line: n, input: l})
				cur = cases[len(cases)-1]
			}
		}
	}
	return cases
}

func main() {
	step := flag.String("step", "", "step name (selects the test files and sets $STEP)")
	impl := flag.String("impl", "./run", "command (space separated) used to start the REPL")
	timeout := flag.Duration("timeout", 30*time.Second, "per-input timeout")
	flag.Parse()
	files := flag.Args()
	if len(files) == 0 {
		files = selectFiles(*step)
	}
	if *step == "" {
		*step = "stepA_mal"
	}
	failed, total := 0, 0
	for _, f := range files {
		cases := parse(f)
		fl, tot := runFile(f, cases, *step, strings.Fields(*impl), *timeout)
		failed += fl
		total += tot
	}
	fmt.Printf("%s: %d tests, %d failed\n", *step, total, failed)
	if failed > 0 {
		os.Exit(1)
	}
}

func selectFiles(step string) []string {
	idx := -1
	for i, s := range stepOrder {
		if s == step {
			idx = i
		}
	}
	if idx < 0 {
		fmt.Fprintln(os.Stderr, "unknown step:", step)
		os.Exit(2)
	}
	lo := idx
	if idx >= 2 {
		lo = 2
	}
	var files []string
	for _, s := range stepOrder[lo : idx+1] {
		m, _ := filepath.Glob("tests/" + s + "*.mal")
		files = append(files, m...)
	}
	return files
}

func runFile(path string, cases []*testCase, step string, impl []string, timeout time.Duration) (failed, total int) {
	cmd := exec.Command(impl[0], append(impl[1:], []string{}...)...)
	cmd.Env = append(os.Environ(), "STEP="+step)
	in, _ := cmd.StdinPipe()
	out, _ := cmd.StdoutPipe()
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		fmt.Printf("FAIL %s: cannot start %v: %v\n", path, impl, err)
		return 1, 1
	}
	chunks := make(chan string, 64)
	go func() {
		buf := make([]byte, 4096)
		for {
			n, err := out.Read(buf)
			if n > 0 {
				chunks <- string(buf[:n])
			}
			if err != nil {
				close(chunks)
				return
			}
		}
	}()
	// readUntilPrompt gathers output until it ends with "user> ".
	readUntilPrompt := func() (string, bool) {
		var sb strings.Builder
		deadline := time.After(timeout)
		for {
			select {
			case c, ok := <-chunks:
				if !ok {
					return sb.String(), false
				}
				sb.WriteString(c)
				if strings.HasSuffix(sb.String(), "user> ") {
					return strings.TrimSuffix(sb.String(), "user> "), true
				}
			case <-deadline:
				return sb.String(), false
			}
		}
	}
	defer func() { in.Close(); cmd.Process.Kill(); cmd.Wait() }()
	if _, ok := readUntilPrompt(); !ok {
		fmt.Printf("FAIL %s: REPL never showed its prompt\n", path)
		return 1, 1
	}
	for _, tc := range cases {
		if !tc.hasEx && len(tc.regex) == 0 && len(tc.exact) == 0 {
			// No expectation: still feed the line to keep state in sync.
			if _, err := fmt.Fprintln(in, tc.input); err != nil {
				break
			}
			readUntilPrompt()
			continue
		}
		total++
		if _, err := fmt.Fprintln(in, tc.input); err != nil {
			fmt.Printf("FAIL %s:%d: REPL died\n", path, tc.line)
			failed++
			break
		}
		got, ok := readUntilPrompt()
		got = strings.ReplaceAll(got, "\r", "")
		got = strings.TrimSuffix(got, "\n")
		bad := !ok
		var want string
		if len(tc.regex) > 0 {
			want = strings.Join(tc.regex, "\n")
			re, err := regexp.Compile("(?s)^(?:" + want + ")$")
			if err != nil || !re.MatchString(got) {
				bad = true
			}
		} else {
			want = strings.Join(tc.exact, "\n")
			if got != want {
				bad = true
			}
		}
		if bad {
			failed++
			fmt.Printf("FAIL %s:%d\n  input:    %s\n  expected: %q\n  got:      %q\n", path, tc.line, tc.input, want, got)
			if !ok {
				break
			}
		}
	}
	return failed, total
}
