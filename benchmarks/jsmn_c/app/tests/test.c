/* Test-suite for jsmn.h. Compiled in four configurations (see Makefile).
 * Test names carry the requirement ids (R1..R20) from .orchestrator/requirements.md */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "jsmn.h"

extern int other_unit_count(const char *js);

static int checks = 0;
static int fails = 0;

#define CHECK(c)                                                              \
  do {                                                                        \
    checks++;                                                                 \
    if (!(c)) {                                                               \
      fails++;                                                                \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);                     \
    }                                                                         \
  } while (0)

#define N 256
#ifdef JSMN_STRICT
#define STRICT_ON 1
#else
#define STRICT_ON 0
#endif

static int parse(const char *js, jsmntok_t *t, unsigned int n) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), t, n);
}

static int count(const char *js) {
  jsmn_parser p;
  jsmn_init(&p);
  return jsmn_parse(&p, js, strlen(js), NULL, 0);
}

static int rc(const char *js) {
  jsmntok_t t[N];
  return parse(js, t, N);
}

static int tok(const char *js, const jsmntok_t *t, jsmntype_t ty,
               const char *txt, int size) {
  size_t l = strlen(txt);
  return t[0].type == ty && (size_t)(t[0].end - t[0].start) == l &&
         strncmp(js + t[0].start, txt, l) == 0 && t[0].size == size;
}

#define TOK(i, ty, txt, sz) CHECK(tok(js, &t[i], ty, txt, sz))

static void test_R2_R4_types_and_init(void) {
  jsmn_parser p;
  p.pos = 5;
  p.toknext = 5;
  p.toksuper = 5;
  jsmn_init(&p);
  CHECK(p.pos == 0 && p.toknext == 0 && p.toksuper == -1);
  CHECK(JSMN_UNDEFINED == 0 && JSMN_OBJECT == 1 && JSMN_ARRAY == 2 &&
        JSMN_STRING == 4 && JSMN_PRIMITIVE == 8);
  CHECK(JSMN_ERROR_NOMEM == -1 && JSMN_ERROR_INVAL == -2 &&
        JSMN_ERROR_PART == -3);
}

static void test_R1_header_only_linkage(void) {
  CHECK(other_unit_count("{\"a\":[1,2]}") == 5);
}

static void test_R16_empty(void) {
  CHECK(rc("") == 0);
  CHECK(rc("   \n\t ") == 0);
  CHECK(count("") == 0);
  CHECK(parse("", NULL, 0) == 0);
}

static void test_R5_R6_object(void) {
  const char *js = "{\"a\":1,\"b\":[true,\"x\"]}";
  jsmntok_t t[N];
  CHECK(parse(js, t, N) == 7);
  TOK(0, JSMN_OBJECT, js, 2);
  CHECK(t[0].start == 0 && t[0].end == (int)strlen(js));
  TOK(1, JSMN_STRING, "a", 1);
  TOK(2, JSMN_PRIMITIVE, "1", 0);
  TOK(3, JSMN_STRING, "b", 1);
  TOK(4, JSMN_ARRAY, "[true,\"x\"]", 2);
  TOK(5, JSMN_PRIMITIVE, "true", 0);
  TOK(6, JSMN_STRING, "x", 0);
  CHECK(t[1].start == 2 && t[1].end == 3); /* quotes excluded */
}

static void test_R6_sizes(void) {
  const char *js = "[[],{},[1,[2,3]],{\"k\":{\"z\":[]}}, \"s\"]";
  jsmntok_t t[N];
  int n = parse(js, t, N);
  CHECK(n == 14);
  CHECK(t[0].size == 5);
  CHECK(t[1].size == 0 && t[2].size == 0);
  CHECK(t[3].size == 2);
  CHECK(t[5].size == 2);
  CHECK(t[8].size == 1 && t[9].size == 1 && t[10].size == 1);
  CHECK(t[11].size == 1 && t[12].size == 0 && t[13].size == 0);
}

static void test_R5_empty_string_and_unicode(void) {
  const char *js = "[\"\", \"\\u00e9\\n\\\"\", \"h\xc3\xa9\"]";
  jsmntok_t t[N];
  CHECK(parse(js, t, N) == 4);
  CHECK(t[1].start == t[1].end);
  CHECK(tok(js, &t[2], JSMN_STRING, "\\u00e9\\n\\\"", 0)); /* not decoded */
  CHECK(tok(js, &t[3], JSMN_STRING, "h\xc3\xa9", 0));
}

static void test_R7_primitives(void) {
  const char *js = "[true,false,null,-12.5e+3,0,10]";
  jsmntok_t t[N];
  CHECK(parse(js, t, N) == 7);
  CHECK(tok(js, &t[1], JSMN_PRIMITIVE, "true", 0));
  CHECK(tok(js, &t[2], JSMN_PRIMITIVE, "false", 0));
  CHECK(tok(js, &t[3], JSMN_PRIMITIVE, "null", 0));
  CHECK(tok(js, &t[4], JSMN_PRIMITIVE, "-12.5e+3", 0));
  CHECK(tok(js, &t[5], JSMN_PRIMITIVE, "0", 0));
  CHECK(tok(js, &t[6], JSMN_PRIMITIVE, "10", 0));
  /* whitespace around primitives */
  CHECK(rc("[ 1 ,\n2\t,3\r]") == 4);
}

static void test_R7_R13_toplevel_primitive(void) {
  jsmntok_t t[N];
  if (STRICT_ON) {
    /* cannot know whether the number is complete */
    CHECK(rc("123") == JSMN_ERROR_PART);
    CHECK(rc("123 ") == 1);
  } else {
    CHECK(rc("123") == 1);
    CHECK(rc("abc") == 1);
    CHECK(parse("true", t, N) == 1 && t[0].end == 4);
  }
}

static void test_R7_R12_lenient_nonstrict(void) {
  if (!STRICT_ON) {
    jsmntok_t t[N];
    const char *js = "{a:b, c:[x,y z]}";
    CHECK(rc("[abc, x]") == 3);
    CHECK(rc("key1: \"value\"\nkey2 : 123") == 4); /* unquoted keys, no container */
    CHECK(count("key1: \"value\"\nkey2 : 123") == 4);
    CHECK(rc("[1, 23") == JSMN_ERROR_PART);
    CHECK(rc("{\"a\":1 \"b\":2}") >= 0);
    CHECK(rc("[1 2]") == 3);
    CHECK(parse(js, t, N) >= 0);
    CHECK(rc("[\"a\nb\"]") == 2); /* control char in string tolerated */
    CHECK(rc("[a\x01]") == JSMN_ERROR_INVAL);
    CHECK(rc("[a\x7f]") == JSMN_ERROR_INVAL);
    CHECK(rc("[\xc3\xa9]") == 2);
  }
}

static void test_R10_escapes(void) {
  CHECK(rc("[\"\\\" \\/ \\\\ \\b \\f \\r \\n \\t \\u0041 \\uBEEF \\ucafe\"]") == 2);
  CHECK(rc("[\"\\x\"]") == JSMN_ERROR_INVAL);
  CHECK(rc("[\"\\a\"]") == JSMN_ERROR_INVAL);
  CHECK(rc("[\"\\u12G4\"]") == JSMN_ERROR_INVAL);
  CHECK(rc("[\"\\u12\"]") == JSMN_ERROR_INVAL);
  CHECK(rc("[\"\\u12") == JSMN_ERROR_PART);
  CHECK(rc("[\"\\") == JSMN_ERROR_PART);
  CHECK(rc("[\"abc") == JSMN_ERROR_PART);
  CHECK(rc("\"abc") == JSMN_ERROR_PART);
  CHECK(rc("\"abc\\\"") == JSMN_ERROR_PART); /* escaped quote does not end it */
  CHECK(rc("\"a\\\\\"") == 1);               /* escaped backslash then quote */
  if (STRICT_ON) {
    CHECK(rc("[\"a\nb\"]") == JSMN_ERROR_INVAL);
    CHECK(rc("[\"a\tb\"]") == JSMN_ERROR_INVAL);
  }
}

static void test_R11_unterminated_and_unmatched(void) {
  CHECK(rc("{") == JSMN_ERROR_PART);
  CHECK(rc("[") == JSMN_ERROR_PART);
  CHECK(rc("{\"a\":1") == JSMN_ERROR_PART);
  CHECK(rc("[[1,2]") == JSMN_ERROR_PART);
  CHECK(rc("{\"a\":") == JSMN_ERROR_PART);
  CHECK(rc("[1,") == JSMN_ERROR_PART);
  CHECK(rc("]") == JSMN_ERROR_INVAL);
  CHECK(rc("}") == JSMN_ERROR_INVAL);
  CHECK(rc("[]]") == JSMN_ERROR_INVAL);
  CHECK(rc("{}}") == JSMN_ERROR_INVAL);
  CHECK(rc("{]") == JSMN_ERROR_INVAL);
  CHECK(rc("[}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":[}") == JSMN_ERROR_INVAL);
  CHECK(rc("[{]}") == JSMN_ERROR_INVAL);
  /* counting mode also reports unmatched closers */
  CHECK(count("]") == JSMN_ERROR_INVAL);
  CHECK(count("[]}") == JSMN_ERROR_INVAL);
  CHECK(count("[") == JSMN_ERROR_PART);
}

static void test_R17_multiple_toplevel(void) {
  jsmntok_t t[N];
  CHECK(parse("{} [] {\"a\":1}", t, N) == 5);
  CHECK(parse("[1] [2]", t, N) == 4);
}

static void test_R15_nomem(void) {
  jsmntok_t t[N];
  const char *js = "{\"a\":[1,2,3]}";
  CHECK(parse(js, t, 0) == JSMN_ERROR_NOMEM);
  CHECK(parse(js, t, 1) == JSMN_ERROR_NOMEM);
  CHECK(parse(js, t, 5) == JSMN_ERROR_NOMEM);
  CHECK(parse(js, t, 6) == 6);
  CHECK(parse("\"a\"", t, 0) == JSMN_ERROR_NOMEM);
  CHECK(parse("[1]", t, 1) == JSMN_ERROR_NOMEM);
}

static void test_R8_counting(void) {
  const char *docs[] = {"{}",
                        "[1,2,3]",
                        "{\"a\":[1,{\"b\":null}],\"c\":\"d\"}",
                        "[[[]]]",
                        "[\"x\\n\", true, -1.5e3]",
                        "{\"k\":{\"k\":{\"k\":[]}}} [1]"};
  size_t i;
  for (i = 0; i < sizeof(docs) / sizeof(docs[0]); i++) {
    jsmntok_t t[N];
    int real = parse(docs[i], t, N);
    CHECK(real > 0);
    CHECK(count(docs[i]) == real);
  }
  /* tokens==NULL must not need storage, with any num_tokens */
  {
    jsmn_parser p;
    jsmn_init(&p);
    CHECK(jsmn_parse(&p, "[1,2]", 5, NULL, 100) == 3);
  }
}

static int same(const jsmntok_t *a, const jsmntok_t *b, int n) {
  int i;
  for (i = 0; i < n; i++) {
    if (a[i].type != b[i].type || a[i].start != b[i].start ||
        a[i].end != b[i].end || a[i].size != b[i].size) {
      return 0;
    }
#ifdef JSMN_PARENT_LINKS
    if (a[i].parent != b[i].parent) {
      return 0;
    }
#endif
  }
  return 1;
}

static const char *docs[] = {
    "{\"a\":1,\"b\":[true,\"x\\u00e9\\n\"],\"c\":{\"d\":null,\"e\":-2.5e+1}}",
    "[[1,2],[3,[4,5]],\"str\\\"ing\",{\"k\":[]}]",
    "{ \"key with space\" : \"value\" , \"n\" : [ 0 , 12 , 3.5 ] }",
    "{\"a\":{\"b\":{\"c\":{\"d\":[[[]]]}}}}",
    "[{}, [], \"\", 0]"};
#define NDOCS ((int)(sizeof(docs) / sizeof(docs[0])))

static void test_R9_resume_part_bytewise(void) {
  int d;
  for (d = 0; d < NDOCS; d++) {
    const char *js = docs[d];
    size_t len = strlen(js), k;
    jsmntok_t one[N], inc[N];
    jsmn_parser p;
    int full = parse(js, one, N), r = 0, ok = 1;
    CHECK(full > 0);
    jsmn_init(&p);
    for (k = 1; k <= len; k++) {
      r = jsmn_parse(&p, js, k, inc, N);
      if (k < len && r != JSMN_ERROR_PART) {
        ok = 0;
      }
    }
    CHECK(ok);
    CHECK(r == full);
    CHECK(same(one, inc, full));
  }
}

static void test_R9_resume_nomem_growth(void) {
  int d;
  for (d = 0; d < NDOCS; d++) {
    const char *js = docs[d];
    jsmntok_t one[N], inc[N];
    jsmn_parser p;
    unsigned int lim = 0;
    int full = parse(js, one, N), r, guard = 0;
    jsmn_init(&p);
    do {
      r = jsmn_parse(&p, js, strlen(js), inc, lim);
      if (r == JSMN_ERROR_NOMEM) {
        lim++;
      }
    } while (r == JSMN_ERROR_NOMEM && ++guard < 1000);
    CHECK(r == full);
    CHECK(same(one, inc, full));
  }
}

static void test_R9_resume_counting(void) {
  const char *js = docs[0];
  size_t k, len = strlen(js);
  jsmn_parser p;
  int r = 0;
  jsmn_init(&p);
  for (k = 1; k <= len; k++) {
    r = jsmn_parse(&p, js, k, NULL, 0);
  }
  CHECK(r == count(js));
}

static void test_R9_mixed_part_then_nomem(void) {
  const char *js = "{\"a\":[1,2,3],\"b\":\"txt\"}";
  size_t len = strlen(js);
  jsmntok_t one[N], t[N];
  jsmn_parser p;
  int full = parse(js, one, N), r;
  jsmn_init(&p);
  r = jsmn_parse(&p, js, 10, t, 3);
  CHECK(r == JSMN_ERROR_NOMEM);
  r = jsmn_parse(&p, js, 10, t, 8);
  CHECK(r == JSMN_ERROR_PART);
  r = jsmn_parse(&p, js, len, t, 4);
  CHECK(r == JSMN_ERROR_NOMEM);
  r = jsmn_parse(&p, js, len, t, N);
  CHECK(r == full && same(one, t, full));
}

static void test_R5_ranges_in_order(void) {
  int d;
  for (d = 0; d < NDOCS; d++) {
    jsmntok_t t[N];
    int n = parse(docs[d], t, N), i;
    for (i = 0; i < n; i++) {
      CHECK(t[i].start >= 0 && t[i].end >= t[i].start &&
            t[i].end <= (int)strlen(docs[d]));
      if (i > 0) {
        CHECK(t[i].start >= t[i - 1].start);
      }
    }
  }
}

static void test_R15_deep_nesting(void) {
  enum { D = 3000 };
  static char buf[2 * D + 1];
  static jsmntok_t t[D];
  int i;
  for (i = 0; i < D; i++) {
    buf[i] = '[';
    buf[2 * D - 1 - i] = ']';
  }
  buf[2 * D] = '\0';
  CHECK(parse(buf, t, D) == D);
  CHECK(t[0].size == 1 && t[D - 1].size == 0);
  CHECK(t[0].end == 2 * D && t[D - 1].end == D + 1);
  buf[D] = '}'; /* mismatch at the innermost level */
  CHECK(parse(buf, t, D) == JSMN_ERROR_INVAL);
}

#ifdef JSMN_PARENT_LINKS
static void test_R14_parent_links(void) {
  const char *js = "{\"a\":1,\"b\":[true,\"x\"]}";
  int expect[] = {-1, 0, 1, 0, 3, 4, 4};
  jsmntok_t t[N];
  int i;
  CHECK(parse(js, t, N) == 7);
  for (i = 0; i < 7; i++) {
    CHECK(t[i].parent == expect[i]);
  }
  js = "[1] [[2],3]";
  CHECK(parse(js, t, N) == 6);
  CHECK(t[0].parent == -1 && t[1].parent == 0 && t[2].parent == -1 &&
        t[3].parent == 2 && t[4].parent == 3 && t[5].parent == 2);
}
#endif

#ifdef JSMN_STRICT
static void test_R13_strict(void) {
  jsmntok_t t[N];
  const char *js = "[0,-0,1.5e-3,10E+2,-1,true,false,null,0.0,1e5]";
  CHECK(parse(js, t, N) == 11);
  CHECK(rc("{\"a\":1,\"b\":\"c\",\"d\":{},\"e\":[]}") == 9);
  CHECK(rc("{ \"a\" : 1 }") == 3);
  CHECK(rc("[ ]") == 1);
  CHECK(rc("123 ") == 1);
  /* invalid primitives */
  CHECK(rc("[01]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1.]") == JSMN_ERROR_INVAL);
  CHECK(rc("[.5]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1e]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1e+]") == JSMN_ERROR_INVAL);
  CHECK(rc("[-]") == JSMN_ERROR_INVAL);
  CHECK(rc("[+1]") == JSMN_ERROR_INVAL);
  CHECK(rc("[tru]") == JSMN_ERROR_INVAL);
  CHECK(rc("[truex]") == JSMN_ERROR_INVAL);
  CHECK(rc("[True]") == JSMN_ERROR_INVAL);
  CHECK(rc("[nul]") == JSMN_ERROR_INVAL);
  CHECK(rc("[abc]") == JSMN_ERROR_INVAL);
  CHECK(rc("[0x10]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1a]") == JSMN_ERROR_INVAL);
  CHECK(rc("['a']") == JSMN_ERROR_INVAL);
  /* primitives cannot be keys */
  CHECK(rc("{1:2}") == JSMN_ERROR_INVAL);
  CHECK(rc("{a:1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{true:1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{[]:1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{{}:1}") == JSMN_ERROR_INVAL);
  /* primitive must be followed by a delimiter */
  CHECK(rc("[1") == JSMN_ERROR_PART);
  CHECK(rc("{\"a\":tru") == JSMN_ERROR_PART);
  CHECK(rc("[1 2]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1\"a\"]") == JSMN_ERROR_INVAL);
  /* structure */
  CHECK(rc("{\"a\":1 \"b\":2}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\" \"b\"}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\"}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":,\"b\":1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\",\"b\":1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":1,}") == JSMN_ERROR_INVAL);
  CHECK(rc("{,}") == JSMN_ERROR_INVAL);
  CHECK(rc("{:1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\"::1}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":1:2}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":\"b\":\"c\"}") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":1,:2}") == JSMN_ERROR_INVAL);
  CHECK(rc("[1,]") == JSMN_ERROR_INVAL);
  CHECK(rc("[,1]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1,,2]") == JSMN_ERROR_INVAL);
  CHECK(rc("[\"a\" \"b\"]") == JSMN_ERROR_INVAL);
  CHECK(rc("[1:2]") == JSMN_ERROR_INVAL);
  CHECK(rc(",") == JSMN_ERROR_INVAL);
  CHECK(rc(":") == JSMN_ERROR_INVAL);
  CHECK(rc("[[1][2]]") == JSMN_ERROR_INVAL);
  CHECK(rc("{\"a\":[1]\"b\":2}") == JSMN_ERROR_INVAL);
}
#endif

static unsigned long seed = 12345;
static unsigned int rnd(void) {
  seed = seed * 1103515245UL + 12345UL;
  return (unsigned int)((seed >> 16) & 0x7fff);
}

static void test_R3_R8_fuzz_invariants(void) {
  static const char alpha[] = "{}[]\",:\\ \n0123456789-.eE+truefalsnu\"abc\x01";
  int iter;
  for (iter = 0; iter < 20000; iter++) {
    char buf[64];
    size_t len = rnd() % 40, i;
    jsmntok_t t[32];
    int r, c;
    for (i = 0; i < len; i++) {
      buf[i] = alpha[rnd() % (sizeof(alpha) - 1)];
    }
    buf[len] = '\0';
    {
      jsmn_parser p;
      jsmn_init(&p);
      r = jsmn_parse(&p, buf, len, t, 32);
    }
    c = count(buf);
    if (r >= 0) {
      int j;
      CHECK(r <= 32);
      CHECK(c == r); /* counting agrees with a successful real parse */
      for (j = 0; j < r; j++) {
        CHECK(t[j].start >= 0 && t[j].end >= t[j].start &&
              t[j].end <= (int)len && t[j].size >= 0);
        CHECK(t[j].type == JSMN_OBJECT || t[j].type == JSMN_ARRAY ||
              t[j].type == JSMN_STRING || t[j].type == JSMN_PRIMITIVE);
      }
    } else {
      CHECK(r == JSMN_ERROR_NOMEM || r == JSMN_ERROR_INVAL ||
            r == JSMN_ERROR_PART);
    }
  }
}

int main(void) {
  test_R2_R4_types_and_init();
  test_R1_header_only_linkage();
  test_R16_empty();
  test_R5_R6_object();
  test_R6_sizes();
  test_R5_empty_string_and_unicode();
  test_R7_primitives();
  test_R7_R13_toplevel_primitive();
  test_R7_R12_lenient_nonstrict();
  test_R10_escapes();
  test_R11_unterminated_and_unmatched();
  test_R17_multiple_toplevel();
  test_R15_nomem();
  test_R8_counting();
  test_R9_resume_part_bytewise();
  test_R9_resume_nomem_growth();
  test_R9_resume_counting();
  test_R9_mixed_part_then_nomem();
  test_R5_ranges_in_order();
  test_R15_deep_nesting();
#ifdef JSMN_PARENT_LINKS
  test_R14_parent_links();
#endif
#ifdef JSMN_STRICT
  test_R13_strict();
#endif
  test_R3_R8_fuzz_invariants();
  printf("%d checks, %d failures (strict=%d parent_links=%d)\n", checks, fails,
         STRICT_ON,
#ifdef JSMN_PARENT_LINKS
         1
#else
         0
#endif
  );
  return fails ? 1 : 0;
}
