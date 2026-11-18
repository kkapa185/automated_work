STEPS := $(notdir $(wildcard cmd/step*))

.PHONY: all build test test-unit test-cli test-steps test-self clean
all: build

build:
	@mkdir -p bin
	@for s in $(STEPS); do go build -o bin/$$s ./cmd/$$s || exit 1; done
	@go build -o bin/runtests ./tools/runtests

test: build test-unit test-cli test-steps test-self

test-unit:
	go test ./internal/...

test-cli:
	sh tests/cli_test.sh

test-steps:
	@for s in $(STEPS); do bin/runtests -step $$s || exit 1; done

# Run the stepA tests through the mal-in-mal implementation (needs mal/stepA_mal.mal).
test-self: build
	bin/runtests -step stepA_mal -impl "./run mal/stepA_mal.mal" -timeout 300s

clean:
	rm -rf bin
