CC      ?= cc
CFLAGS  ?= -O2
WARN    := -std=c89 -pedantic -Wall -Wextra -Werror
BUILD   := build

CONFIGS := default strict links both
FLAGS_default :=
FLAGS_strict  := -DJSMN_STRICT=1
FLAGS_links   := -DJSMN_PARENT_LINKS=1
FLAGS_both    := -DJSMN_STRICT=1 -DJSMN_PARENT_LINKS=1

.PHONY: all test clean examples test-multi test-examples \
        $(addprefix test-,$(CONFIGS))

all: examples

examples: $(BUILD)/simple $(BUILD)/jsondump

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/simple: example/simple.c jsmn.h | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) -o $@ $<

$(BUILD)/jsondump: example/jsondump.c jsmn.h | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) -o $@ $<

define CONFIG_RULE
$(BUILD)/test_$(1): test/test.c jsmn.h | $(BUILD)
	$$(CC) $$(CFLAGS) $$(WARN) $$(FLAGS_$(1)) -o $$@ $$<
test-$(1): $(BUILD)/test_$(1)
	@echo "== configuration: $(1) $$(FLAGS_$(1))"
	$(BUILD)/test_$(1)
endef
$(foreach c,$(CONFIGS),$(eval $(call CONFIG_RULE,$(c))))

MULTI_SRC := test/multi_main.c test/multi_impl.c test/static_a.c test/static_b.c

$(BUILD)/multi: $(MULTI_SRC) jsmn.h | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) -o $@ $(MULTI_SRC)

test-multi: $(BUILD)/multi
	$(BUILD)/multi

test-examples: examples
	$(BUILD)/simple > $(BUILD)/simple.out
	diff -u example/simple.expected $(BUILD)/simple.out
	$(BUILD)/jsondump < example/sample.json > $(BUILD)/sample.out
	diff -u example/sample.expected $(BUILD)/sample.out
	! echo '{"a":' | $(BUILD)/jsondump 2>/dev/null

test: $(addprefix test-,$(CONFIGS)) test-multi test-examples
	@echo "ALL TESTS PASSED"

clean:
	$(RM) -r $(BUILD)
