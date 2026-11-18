package mal

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
)

// ErrorText renders a recovered panic value as the text after "Error: ".
func ErrorText(r interface{}) string {
	switch e := r.(type) {
	case *MalError:
		if s, ok := e.Val.(string); ok {
			return s
		}
		return PrStr(e.Val, true)
	case error:
		return e.Error()
	}
	return fmt.Sprint(r)
}

// SafeRep calls rep(line), converting any panic into an error message.
// show is false when the input contained no form.
func SafeRep(rep func(string) string, line string) (out string, show bool) {
	depth = 0
	defer func() {
		if r := recover(); r != nil {
			depth = 0
			if IsBlank(r) {
				out, show = "", false
				return
			}
			out, show = "Error: "+ErrorText(r), true
		}
	}()
	return rep(line), true
}

var stdin = bufio.NewReader(os.Stdin)

// Readline prints prompt and reads one line from stdin (without the newline).
// ok is false at EOF with no data.
func Readline(prompt string) (string, bool) {
	fmt.Print(prompt)
	line, err := stdin.ReadString('\n')
	if err != nil && (err != io.EOF || line == "") {
		return "", false
	}
	return strings.TrimRight(line, "\r\n"), true
}

// Repl runs the standard read-eval-print loop until EOF.
func Repl(rep func(string) string) {
	Init()
	for {
		line, ok := Readline("user> ")
		if !ok {
			fmt.Println()
			return
		}
		if out, show := SafeRep(rep, line); show {
			fmt.Println(out)
		}
	}
}
