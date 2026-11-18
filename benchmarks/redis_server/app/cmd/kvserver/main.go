// Command kvserver is a Redis-compatible in-memory data-structure server.
package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"

	"kvserver/internal/server"
)

func main() {
	port := flag.Int("port", 6379, "TCP port to listen on (127.0.0.1)")
	dir := flag.String("dir", "", "data directory for snapshots (default: current directory)")
	flag.Parse()

	dirSet := *dir != ""
	if !dirSet {
		wd, err := os.Getwd()
		if err != nil {
			wd = "."
		}
		*dir = wd
	} else if err := os.MkdirAll(*dir, 0o755); err != nil {
		log.Fatalf("cannot create data dir: %v", err)
	}

	srv := server.New(server.Options{Port: *port, Dir: *dir})
	if err := srv.Load(); err != nil {
		log.Printf("snapshot load failed, starting empty: %v", err)
	}
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", *port))
	if err != nil {
		log.Fatalf("listen: %v", err)
	}
	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
		<-sig
		if dirSet {
			if err := srv.Save(); err != nil {
				log.Printf("save on shutdown failed: %v", err)
			}
		}
		os.Exit(0)
	}()
	log.Printf("Ready to accept connections on 127.0.0.1:%d", *port)
	if err := srv.Serve(ln); err != nil {
		log.Fatalf("serve: %v", err)
	}
}
