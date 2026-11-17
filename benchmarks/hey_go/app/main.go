package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"runtime"
)

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(args []string, stdout, stderr io.Writer) int {
	cfg, err := parseArgs(args)
	if err != nil {
		fmt.Fprintf(stderr, "Error: %v\n\n%s", err, usage())
		return 1
	}
	runtime.GOMAXPROCS(cfg.CPUs)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	results, total := NewRunner(cfg).Run(ctx)
	if cfg.Output == "csv" {
		WriteCSV(stdout, results)
	} else {
		WriteSummary(stdout, results, total)
	}
	return 0
}
