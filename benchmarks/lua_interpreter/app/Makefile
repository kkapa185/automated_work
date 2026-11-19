CC ?= gcc
CFLAGS ?= -O2 -std=gnu11 -Wall -Wextra -Wno-unused-parameter -Wno-clobbered
SRC := $(wildcard src/*.c)
OBJ := $(SRC:src/%.c=build/%.o)

all: bin/luai

bin/luai: $(OBJ)
	@mkdir -p bin
	$(CC) $(CFLAGS) -o $@ $(OBJ) -lm

build/%.o: src/%.c src/lua.h
	@mkdir -p build
	$(CC) $(CFLAGS) -c -o $@ $<

test: all
	sh tests/run.sh

clean:
	rm -rf build bin/luai

.PHONY: all test clean
