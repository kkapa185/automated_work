/* Test-suite for jsmn.h. Compiled in four configurations by the Makefile.
 * Expected values are derived by hand from the written specification. */
#include <stdio.h>
#include <string.h>
#include "../jsmn.h"

static int checks = 0, failures = 0, tests = 0, test_failed;

#define CHECK(cond)                                                        \
  do {                                                                     \
    checks++;                                                              \
    if (!(cond)) {                                                         \
      failures++;                                                          \
      test_failed = 1;                                                     \
      printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);             \
    }                                                                      \
  } while (0)

#define RUN(fn)                                                            \
  do {                                                                     \
    test_failed = 0;                                                       \
    tests++;                                                               \
    fn();                                                                  \
    printf("%s %s\n", test_failed ? "not ok" : "ok    ", #fn);             \
  } while (0)

#define N 256
static jsmntok_t tk[N];

static int parse(const char *js) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), tk, N);
}

static int count(const char *js) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), NULL, 0);
}

/* token i has given type, text and size */
static int tok(const char *js, int i, jsmntype_t type, const char *text,
               int size) {
  size_t l = strlen(text);
  return tk[i].type == type && tk[i].size == size &&
         (size_t)(tk[i].end - tk[i].start) == l &&
         strncmp(js + tk[i].start, text, l) == 0;
}

/* R2/R3 */
static void test_types_and_init(void) {
  jsmn_parser p;
  jsmntok_t t;
  p.pos = 7; p.toknext = 9; p.toksuper = 4;
  jsmn_init(&p);
  CHECK(p.pos == 0 && p.toknext == 0 && p.toksuper == -1);
  CHECK(JSMN_UNDEFINED == 0 && JSMN_OBJECT == 1 && JSMN_ARRAY == 2 &&
        JSMN_STRING == 4 && JSMN_PRIMITIVE == 8);
  CHECK(JSMN_ERROR_NOMEM == -1 && JSMN_ERROR_INVAL == -2 &&
        JSMN_ERROR_PART == -3);
  t.type = JSMN_OBJECT; t.start = t.end = t.size = 0;
#ifdef JSMN_PARENT_LINKS
  t.parent = -1;
#endif
  CHECK(t.size == 0);
}

/* R15 */
static void test_empty(void) {
  CHECK(parse("") == 0);
  CHECK(parse("  \t\r\n ") == 0);
  CHECK(count("") == 0);
}

/* R4 */
static void test_simple_object(void) {
  const char *js = "{\"a\":1}";
  CHECK(parse(js) == 3);
  CHECK(tk[0].type == JSMN_OBJECT && tk[0].start == 0 && tk[0].end == 7 &&
        tk[0].size == 1);
  CHECK(tk[1].type == JSMN_STRING && tk[1].start == 2 && tk[1].end == 3 &&
        tk[1].size == 1);
  CHECK(tk[2].type == JSMN_PRIMITIVE && tk[2].start == 5 && tk[2].end == 6 &&
        tk[2].size == 0);
}

/* R4, R5: document order, sizes, types */
static void test_nested_document_order(void) {
  const char *js = "{\"a\":[1,\"x\",true,null],\"b\":{\"c\":false}}";
  CHECK(parse(js) == 11);
  CHECK(tok(js, 0, JSMN_OBJECT, js, 2));
  CHECK(tok(js, 1, JSMN_STRING, "a", 1));
  CHECK(tok(js, 2, JSMN_ARRAY, "[1,\"x\",true,null]", 4));
  CHECK(tok(js, 3, JSMN_PRIMITIVE, "1", 0));
  CHECK(tok(js, 4, JSMN_STRING, "x", 0));
  CHECK(tok(js, 5, JSMN_PRIMITIVE, "true", 0));
  CHECK(tok(js, 6, JSMN_PRIMITIVE, "null", 0));
  CHECK(tok(js, 7, JSMN_STRING, "b", 1));
  CHECK(tok(js, 8, JSMN_OBJECT, "{\"c\":false}", 1));
  CHECK(tok(js, 9, JSMN_STRING, "c", 1));
  CHECK(tok(js, 10, JSMN_PRIMITIVE, "false", 0));
}

static void test_sizes(void) {
  const char *js = "{\"a\":{\"b\":1,\"c\":2},\"d\":[]}";
  CHECK(parse(js) == 9);
  CHECK(tk[0].size == 2);
  CHECK(tk[1].size == 1);
  CHECK(tk[2].type == JSMN_OBJECT && tk[2].size == 2);
  CHECK(tk[3].size == 1 && tk[4].size == 0);
  CHECK(tk[5].size == 1 && tk[6].size == 0);
  CHECK(tk[7].size == 1);
  CHECK(tk[8].type == JSMN_ARRAY && tk[8].size == 0);
}

static void test_array_root(void) {
  const char *js = "[1, 2, 3]";
  CHECK(parse(js) == 4);
  CHECK(tok(js, 0, JSMN_ARRAY, js, 3));
  CHECK(tok(js, 1, JSMN_PRIMITIVE, "1", 0));
  CHECK(tok(js, 3, JSMN_PRIMITIVE, "3", 0));
  CHECK(parse("[[],[[]],{}]") == 5);
  CHECK(tk[0].size == 3 && tk[1].size == 0 && tk[2].size == 1);
}

static void test_numbers_and_literals(void) {
  const char *js = "[-12.5e+3, 0, true, false, null]";
  CHECK(parse(js) == 6);
  CHECK(tok(js, 1, JSMN_PRIMITIVE, "-12.5e+3", 0));
  CHECK(tok(js, 5, JSMN_PRIMITIVE, "null", 0));
}

/* R9 */
static void test_string_escapes(void) {
  const char *js = "[\"a\\\"b\\/c\\\\d\\be\\ff\\rg\\nh\\ti\\u00e9\\uABCD\"]";
  CHECK(parse(js) == 2);
  CHECK(tk[1].type == JSMN_STRING);
  /* escapes are not decoded: token covers the raw text without quotes */
  CHECK(tk[1].start == 2 && tk[1].end == (int)strlen(js) - 2);
  CHECK(parse("[\"\\\\\"]") == 2); /* "\\" then closing quote */
  CHECK(parse("[\"\"]") == 2 && tk[1].start == tk[1].end);
}

static void test_invalid_escapes(void) {
  CHECK(parse("[\"\\x\"]") == JSMN_ERROR_INVAL);
  CHECK(parse("[\"\\u12G4\"]") == JSMN_ERROR_INVAL);
  CHECK(parse("[\"\\u12\"]") == JSMN_ERROR_INVAL);
  CHECK(parse("[\"\\u123") == JSMN_ERROR_PART);
  CHECK(parse("[\"\\") == JSMN_ERROR_PART);
  CHECK(count("[\"\\q\"]") == JSMN_ERROR_INVAL); /* counting mode too */
  CHECK(count("[\"\\u00zz\"]") == JSMN_ERROR_INVAL);
}

/* R8, R10 */
static void test_part(void) {
  CHECK(parse("\"abc") == JSMN_ERROR_PART);
  CHECK(parse("[\"abc") == JSMN_ERROR_PART);
  CHECK(parse("{\"a\":\"b\"") == JSMN_ERROR_PART);
  CHECK(parse("[") == JSMN_ERROR_PART);
  CHECK(parse("{\"a\":[1,2]") == JSMN_ERROR_PART);
  CHECK(parse("[[]") == JSMN_ERROR_PART);
}

static void test_unmatched_closers(void) {
  CHECK(parse("]") == JSMN_ERROR_INVAL);
  CHECK(parse("}") == JSMN_ERROR_INVAL);
  CHECK(parse("{]") == JSMN_ERROR_INVAL);
  CHECK(parse("[}") == JSMN_ERROR_INVAL);
  CHECK(parse("{\"a\":1}}") == JSMN_ERROR_INVAL);
  CHECK(parse("[1]]") == JSMN_ERROR_INVAL);
  CHECK(parse("[{]}") == JSMN_ERROR_INVAL);
  CHECK(parse("[[]") == JSMN_ERROR_PART);
}

/* R6, R7 */
static void test_counting_mode(void) {
  const char *docs[] = {"{\"a\":[1,\"x\",true,null],\"b\":{\"c\":false}}",
                        "[1, 2, 3]", "{}", "[[],[[]],{}]",
                        "{\"a\":{\"b\":1,\"c\":2},\"d\":[]}", "\"s\"", "[]"};
  size_t i;
  for (i = 0; i < sizeof docs / sizeof docs[0]; i++) {
    int n = parse(docs[i]);
    CHECK(n > 0);
    CHECK(count(docs[i]) == n);
  }
  CHECK(count("{\"a\":[1,\"x\",true,null],\"b\":{\"c\":false}}") == 11);
  /* skipped checks: no error for these, only the tokens seen so far */
  CHECK(count("{\"a\":\"b\"") == 3);  /* unclosed object is not detected */
  CHECK(count("[}") == 1);            /* mismatched closer not detected  */
  CHECK(count("]") == 0);             /* unmatched closer not detected   */
  CHECK(count("[[\"a\"") == 3);
  /* counting mode never touches the parser's token bookkeeping */
  {
    jsmn_parser p;
    jsmn_init(&p);
    CHECK(jsmn_parse(&p, "[1,2]", 5, NULL, 0) == 3);
    CHECK(p.toknext == 0);
  }
}

/* R8: NOMEM, grow and resume */
static void test_nomem_and_grow(void) {
  jsmn_parser p;
  jsmntok_t small[2];
  const char *js = "[1,2,3]";
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, js, strlen(js), small, 2) == JSMN_ERROR_NOMEM);
  /* caller grows the array (the already-filled tokens are kept) */
  memcpy(tk, small, sizeof small);
  CHECK(jsmn_parse(&p, js, strlen(js), tk, 4) == 4);
  CHECK(tok(js, 0, JSMN_ARRAY, js, 3));
  CHECK(tok(js, 1, JSMN_PRIMITIVE, "1", 0));
  CHECK(tok(js, 2, JSMN_PRIMITIVE, "2", 0));
  CHECK(tok(js, 3, JSMN_PRIMITIVE, "3", 0));
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "{}", 2, tk, 0) == JSMN_ERROR_NOMEM);
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "\"a\"", 3, tk, 0) == JSMN_ERROR_NOMEM);
#ifndef JSMN_STRICT
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "12", 2, tk, 0) == JSMN_ERROR_NOMEM);
#endif
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "[\"a\",\"b\"]", 9, tk, 2) == JSMN_ERROR_NOMEM);
  CHECK(jsmn_parse(&p, "[\"a\",\"b\"]", 9, tk, 3) == 3);
  CHECK(tk[0].size == 2 && tk[0].end == 9);
  CHECK(tok("[\"a\",\"b\"]", 2, JSMN_STRING, "b", 0));
}

static int is_prim_char(char c) {
  return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || c == '-' ||
         c == '.' || c == '+';
}

/* R8: feed growing prefixes of a document to the same parser */
static void test_resume_prefixes(void) {
  const char *js =
      "{\"key\":\"va\\u00e9lue\",\"n\":[10,20,{\"x\":\"y\"}],\"t\":[ true , "
      "false ]}";
  size_t len = strlen(js), l;
  jsmn_parser p;
  jsmntok_t ref[N];
  int r = 0, n;
  n = parse(js);
  CHECK(n == 14);
  memcpy(ref, tk, sizeof ref);
  jsmn_init(&p);
  for (l = 1; l <= len; l++) {
    if (l < len && is_prim_char(js[l - 1]) && is_prim_char(js[l])) {
      continue; /* would split a primitive */
    }
    r = jsmn_parse(&p, js, l, tk, N);
    if (l < len) {
      CHECK(r == JSMN_ERROR_PART);
    }
  }
  CHECK(r == n);
  CHECK(memcmp(tk, ref, sizeof(jsmntok_t) * (size_t)n) == 0);
}

/* R8, R9: every prefix, including cuts inside strings and escapes */
static void test_resume_every_byte(void) {
  const char *js = "{\"k\":\"va\\u00e9lue\",\"a\":[\"x\\n\\\"y\"]}";
  size_t len = strlen(js), l;
  jsmn_parser p;
  int r = 0;
  jsmn_init(&p);
  for (l = 1; l <= len; l++) {
    r = jsmn_parse(&p, js, l, tk, N);
    if (l < len) CHECK(r == JSMN_ERROR_PART);
  }
  CHECK(r == 6);
  CHECK(tok(js, 2, JSMN_STRING, "va\\u00e9lue", 0));
  CHECK(tok(js, 5, JSMN_STRING, "x\\n\\\"y", 0));
  CHECK(tk[0].size == 2 && tk[4].size == 1);
}

/* R5, R12 */
static void test_primitive_terminators(void) {
  const char *js = "[1\t,2\r,3\n,4 ,5]";
  CHECK(parse(js) == 6);
  CHECK(parse("{\"a\":1}") == 3);
  CHECK(tk[2].end == 6);
  CHECK(parse("[1\n]") == 2);
  CHECK(parse("[\"a\\u0041\"  ]") == 2);
}

static void test_illegal_chars(void) {
  CHECK(parse("[1\x01]") == JSMN_ERROR_INVAL);
  CHECK(parse("[1\x7f]") == JSMN_ERROR_INVAL);
  CHECK(parse("[1\x80]") == JSMN_ERROR_INVAL);
  CHECK(count("[1\x01]") == JSMN_ERROR_INVAL);
}

#ifndef JSMN_STRICT
/* R5, R12: non-strict primitives */
static void test_nonstrict_primitives(void) {
  const char *js = "[abc, @x, tru]";
  CHECK(parse(js) == 4);
  CHECK(tok(js, 1, JSMN_PRIMITIVE, "abc", 0));
  CHECK(tok(js, 2, JSMN_PRIMITIVE, "@x", 0));
  CHECK(parse("12") == 1);
  CHECK(tk[0].type == JSMN_PRIMITIVE && tk[0].start == 0 && tk[0].end == 2);
  CHECK(parse("abc") == 1);
  CHECK(parse("{a:1}") == 3);
  CHECK(tok("{a:1}", 1, JSMN_PRIMITIVE, "a", 1));
  CHECK(parse("[1") == JSMN_ERROR_PART);
}
#else
/* R11 */
static void test_strict_primitive_start(void) {
  CHECK(parse("[abc]") == JSMN_ERROR_INVAL);
  CHECK(parse("[@]") == JSMN_ERROR_INVAL);
  CHECK(parse("[?1]") == JSMN_ERROR_INVAL);
  CHECK(parse("[Tru]") == JSMN_ERROR_INVAL);
  CHECK(parse("[.5]") == JSMN_ERROR_INVAL);
  CHECK(parse("[+1]") == JSMN_ERROR_INVAL);
  CHECK(count("[abc]") == JSMN_ERROR_INVAL);
  CHECK(parse("{\"a\":x}") == JSMN_ERROR_INVAL);
}

static void test_strict_spelling_not_checked(void) {
  const char *js = "[tru, 01, -, nul, fals1, 1e]";
  CHECK(parse(js) == 7);
  CHECK(tok(js, 1, JSMN_PRIMITIVE, "tru", 0));
  CHECK(tok(js, 2, JSMN_PRIMITIVE, "01", 0));
  CHECK(tok(js, 3, JSMN_PRIMITIVE, "-", 0));
}

static void test_strict_terminators(void) {
  const char *js = "{\"a\":1:2}";
  /* ':' does not terminate a primitive: "1:2" is one token */
  CHECK(parse(js) == 3);
  CHECK(tok(js, 2, JSMN_PRIMITIVE, "1:2", 0));
  CHECK(parse("[1\t,2\r,3\n,4 ,5]") == 6);
  CHECK(parse("[1]") == 2);
  CHECK(parse("{\"a\":1}") == 3);
}

static void test_strict_end_of_input(void) {
  CHECK(parse("1") == JSMN_ERROR_PART);
  CHECK(parse("[1") == JSMN_ERROR_PART);
  CHECK(parse("true") == JSMN_ERROR_PART);
  CHECK(count("12") == JSMN_ERROR_PART);
  CHECK(parse("\"s\"") == 1);
  {
    /* resume once the terminator arrives */
    jsmn_parser p;
    jsmn_init(&p);
    CHECK(jsmn_parse(&p, "[12", 3, tk, N) == JSMN_ERROR_PART);
    CHECK(jsmn_parse(&p, "[123]", 5, tk, N) == 2);
    CHECK(tk[1].start == 1 && tk[1].end == 4);
  }
}

static void test_strict_keys(void) {
  CHECK(parse("{1:2}") == JSMN_ERROR_INVAL);
  CHECK(parse("{true:1}") == JSMN_ERROR_INVAL);
  CHECK(parse("{{}:1}") == JSMN_ERROR_INVAL);
  CHECK(parse("{[]:1}") == JSMN_ERROR_INVAL);
  CHECK(parse("{\"a\":1 2}") == JSMN_ERROR_INVAL);
  CHECK(parse("{\"a\":1,\"b\":[true,{\"c\":null}]}") == 9);
  CHECK(parse("{\"a\":{},\"b\":[]}") == 5);
}
#endif

#ifdef JSMN_PARENT_LINKS
/* R13 */
static void test_parent_links(void) {
  const char *js = "{\"a\":[1,2],\"b\":3}";
  int par[7] = {-1, 0, 1, 2, 2, 0, 5};
  int i;
  CHECK(parse(js) == 7);
  for (i = 0; i < 7; i++) CHECK(tk[i].parent == par[i]);
  CHECK(parse("[[1],[2,[3]],4]") == 8);
  CHECK(tk[0].parent == -1 && tk[1].parent == 0 && tk[2].parent == 1 &&
        tk[3].parent == 0 && tk[4].parent == 3 && tk[5].parent == 3 &&
        tk[6].parent == 5 && tk[7].parent == 0);
  CHECK(parse("\"s\"") == 1 && tk[0].parent == -1);
}
#endif

/* R13, R14: deep nesting, both closing-bracket matching strategies */
static void test_deep_nesting(void) {
  static jsmntok_t big[1024];
  char js[1024];
  int d = 300, i;
  jsmn_parser p;
  for (i = 0; i < d; i++) js[i] = '[';
  for (i = 0; i < d; i++) js[d + i] = ']';
  js[2 * d] = 0;
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, js, strlen(js), big, 1024) == d);
  for (i = 0; i < d; i++) {
    CHECK(big[i].start == i && big[i].end == 2 * d - i);
    CHECK(big[i].size == (i < d - 1 ? 1 : 0));
  }
  js[2 * d - 1] = 0;
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, js, strlen(js), big, 1024) == JSMN_ERROR_PART);
}

/* R14: an object closed after nested value containers keeps parent right */
static void test_siblings_after_close(void) {
  const char *js = "[{\"a\":[1]},{\"b\":2},[3]]";
  CHECK(parse(js) == 10);
  CHECK(tk[0].size == 3);
  CHECK(tok(js, 1, JSMN_OBJECT, "{\"a\":[1]}", 1));
  CHECK(tok(js, 5, JSMN_OBJECT, "{\"b\":2}", 1));
  CHECK(tok(js, 8, JSMN_ARRAY, "[3]", 1));
  CHECK(tok(js, 9, JSMN_PRIMITIVE, "3", 0));
}

/* R1: the example from the task text (key size 1) */
static void test_key_sizes(void) {
  const char *js = "{\"a\":\"b\",\"c\":[],\"d\":{}}";
  CHECK(parse(js) == 7);
  CHECK(tk[0].size == 3);
  CHECK(tk[1].size == 1 && tk[3].size == 1 && tk[5].size == 1);
  CHECK(tk[2].size == 0 && tk[4].size == 0 && tk[6].size == 0);
}

/* NUL byte ends the input, strings with raw NUL are unterminated */
static void test_len_respected(void) {
  jsmn_parser p;
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "[1,2,3]", 3, tk, N) == JSMN_ERROR_PART);
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "[]garbage", 2, tk, N) == 1);
}

/* A5: processing stops at the first NUL byte */
static void test_nul_terminates(void) {
  jsmn_parser p;
  jsmn_init(&p);
  CHECK(jsmn_parse(&p, "[1]\0junk", 9, tk, N) == 2);
  CHECK(p.pos == 3);
}

int main(void) {
  RUN(test_types_and_init);
  RUN(test_empty);
  RUN(test_simple_object);
  RUN(test_nested_document_order);
  RUN(test_sizes);
  RUN(test_array_root);
  RUN(test_numbers_and_literals);
  RUN(test_string_escapes);
  RUN(test_invalid_escapes);
  RUN(test_part);
  RUN(test_unmatched_closers);
  RUN(test_counting_mode);
  RUN(test_nomem_and_grow);
  RUN(test_resume_prefixes);
  RUN(test_resume_every_byte);
  RUN(test_primitive_terminators);
  RUN(test_illegal_chars);
#ifndef JSMN_STRICT
  RUN(test_nonstrict_primitives);
#else
  RUN(test_strict_primitive_start);
  RUN(test_strict_spelling_not_checked);
  RUN(test_strict_terminators);
  RUN(test_strict_end_of_input);
  RUN(test_strict_keys);
#endif
#ifdef JSMN_PARENT_LINKS
  RUN(test_parent_links);
#endif
  RUN(test_deep_nesting);
  RUN(test_siblings_after_close);
  RUN(test_key_sizes);
  RUN(test_len_respected);
  RUN(test_nul_terminates);
  printf("%d tests, %d checks, %d failures\n", tests, checks, failures);
  return failures ? 1 : 0;
}
