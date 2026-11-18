.PHONY: all build test clean
all build:
	go build -o bin/lua .
test: build
	go vet ./...
	go test ./...
	sh tests/run_tests.sh
clean:
	rm -rf bin
