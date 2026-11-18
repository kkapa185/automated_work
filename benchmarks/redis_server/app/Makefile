.PHONY: build test race clean
build:
	go build -o bin/kvserver ./cmd/kvserver
test: build
	go vet ./...
	go test -count=1 ./...
race:
	KV_RACE=1 go test -count=1 -race ./...
clean:
	rm -rf bin
