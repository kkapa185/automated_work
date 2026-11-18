CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -DNDEBUG -Wall -Wextra -pthread
SRC := $(wildcard src/*.cpp)
HDR := $(wildcard src/*.h)

all: build/engine

build/engine: $(SRC) $(HDR)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -o $@ $(SRC)

test: build/engine
	python3 -m unittest discover -s tests -v

clean:
	rm -rf build

.PHONY: all test clean
