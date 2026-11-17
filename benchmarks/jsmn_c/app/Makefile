CC      ?= cc
CFLAGS  ?= -O2
WARN     = -std=c89 -pedantic -Wall -Wextra -Werror
INC      = -I.
B        = build

CONFIGS  = default strict links strict_links
FLAGS_default       =
FLAGS_strict        = -DJSMN_STRICT=1
FLAGS_links         = -DJSMN_PARENT_LINKS=1
FLAGS_strict_links  = -DJSMN_STRICT=1 -DJSMN_PARENT_LINKS=1

.PHONY: all test examples clean sanitize $(CONFIGS)

all: examples

test: $(CONFIGS) static_test examples
	@sh tests/run_examples.sh $(B)
	@echo "ALL TESTS PASSED"

$(CONFIGS):
	@mkdir -p $(B)
	$(CC) $(CFLAGS) $(WARN) $(INC) $(FLAGS_$@) -o $(B)/test_$@ tests/test.c tests/other_unit.c
	@echo "== test config: $@"
	@$(B)/test_$@

static_test:
	@mkdir -p $(B)
	$(CC) $(CFLAGS) $(WARN) $(INC) -o $(B)/static_test tests/static_test.c
	@$(B)/static_test

examples: $(B)/simple $(B)/jsondump

$(B)/simple: examples/simple.c jsmn.h
	@mkdir -p $(B)
	$(CC) $(CFLAGS) $(WARN) $(INC) -o $@ examples/simple.c

$(B)/jsondump: examples/jsondump.c jsmn.h
	@mkdir -p $(B)
	$(CC) $(CFLAGS) $(WARN) $(INC) -o $@ examples/jsondump.c

# Optional: run all configurations under ASan/UBSan
sanitize:
	@mkdir -p $(B)
	@for c in "" "-DJSMN_STRICT=1" "-DJSMN_PARENT_LINKS=1" "-DJSMN_STRICT=1 -DJSMN_PARENT_LINKS=1"; do \
	  $(CC) -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=all $(WARN) $(INC) $$c -o $(B)/test_san tests/test.c tests/other_unit.c && $(B)/test_san || exit 1; \
	done

clean:
	rm -rf $(B)
