/*
 * jsmn.h - minimalistic, allocation-free JSON tokenizer (single header, C89).
 *
 * Usage:
 *   - In exactly one .c file:   #include "jsmn.h"
 *   - In other files:           #define JSMN_HEADER  then #include "jsmn.h"
 *   - Single-file programs:     #define JSMN_STATIC  then #include "jsmn.h"
 *
 * Options (define before including):
 *   JSMN_STRICT        strict JSON grammar checking
 *   JSMN_PARENT_LINKS  jsmntok_t gets a `parent` field; O(1) bracket matching
 *   JSMN_HEADER        declarations only
 *   JSMN_STATIC        all functions are `static`
 *
 * See README.md for the exact semantics.
 */
#ifndef JSMN_H
#define JSMN_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef JSMN_STATIC
#define JSMN_API static
#else
#define JSMN_API extern
#endif

typedef enum {
  JSMN_UNDEFINED = 0,
  JSMN_OBJECT = 1 << 0,
  JSMN_ARRAY = 1 << 1,
  JSMN_STRING = 1 << 2,
  JSMN_PRIMITIVE = 1 << 3
} jsmntype_t;

enum jsmnerr {
  /* Not enough tokens were provided */
  JSMN_ERROR_NOMEM = -1,
  /* Invalid character inside JSON string */
  JSMN_ERROR_INVAL = -2,
  /* The string is not a full JSON packet, more bytes expected */
  JSMN_ERROR_PART = -3
};

/*
 * JSON token description.
 * type   type (object, array, string etc.)
 * start  start position in JSON data string
 * end    end position (exclusive) in JSON data string
 * size   number of direct children
 */
typedef struct jsmntok {
  jsmntype_t type;
  int start;
  int end;
  int size;
#ifdef JSMN_PARENT_LINKS
  int parent;
#endif
} jsmntok_t;

/*
 * JSON parser. Contains an array of token blocks available. Also stores
 * the string being parsed now and current position in that string.
 */
typedef struct jsmn_parser {
  unsigned int pos;     /* offset in the JSON string */
  unsigned int toknext; /* next token to allocate */
  int toksuper;         /* superior token node, e.g. parent object or array */
} jsmn_parser;

/* Create JSON parser over an array of tokens. */
JSMN_API void jsmn_init(jsmn_parser *parser);

/*
 * Run JSON parser. Returns the number of tokens used, or a negative jsmnerr.
 * If tokens is NULL only the number of required tokens is computed.
 */
JSMN_API int jsmn_parse(jsmn_parser *parser, const char *js, const size_t len,
                        jsmntok_t *tokens, const unsigned int num_tokens);

#ifndef JSMN_HEADER

/* Allocate a token (or only count it when tokens == NULL).
 * Returns its index, or -1 when the token array is exhausted. */
static int jsmn_new_token(jsmn_parser *parser, jsmntok_t *tokens,
                          unsigned int num_tokens, jsmntype_t type, int start,
                          int end, int parent) {
  jsmntok_t *tok;
  if (tokens == NULL) {
    parser->toknext++;
    return (int)parser->toknext - 1;
  }
  if (parser->toknext >= num_tokens) {
    return -1;
  }
  tok = &tokens[parser->toknext++];
  tok->type = type;
  tok->start = start;
  tok->end = end;
  tok->size = 0;
#ifdef JSMN_PARENT_LINKS
  tok->parent = parent;
#else
  (void)parent;
#endif
  return (int)parser->toknext - 1;
}

#ifdef JSMN_STRICT

static int jsmn_is_ws(char c) {
  return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

/* Last non-whitespace character before pos, or 0 when there is none. */
static char jsmn_prev(const char *js, size_t pos) {
  while (pos > 0) {
    pos--;
    if (!jsmn_is_ws(js[pos])) {
      return js[pos];
    }
  }
  return 0;
}

static int jsmn_is_digit(char c) { return c >= '0' && c <= '9'; }

static int jsmn_lit_eq(const char *s, size_t n, const char *lit) {
  size_t i = 0;
  while (lit[i] != '\0') {
    if (i >= n || s[i] != lit[i]) {
      return 0;
    }
    i++;
  }
  return i == n;
}

/* Is s[0..n) a JSON number or one of true/false/null? */
static int jsmn_valid_primitive(const char *s, size_t n) {
  size_t i = 0;
  if (jsmn_lit_eq(s, n, "true") || jsmn_lit_eq(s, n, "false") ||
      jsmn_lit_eq(s, n, "null")) {
    return 1;
  }
  if (i < n && s[i] == '-') {
    i++;
  }
  if (i >= n) {
    return 0;
  }
  if (s[i] == '0') {
    i++;
  } else if (s[i] >= '1' && s[i] <= '9') {
    while (i < n && jsmn_is_digit(s[i])) {
      i++;
    }
  } else {
    return 0;
  }
  if (i < n && s[i] == '.') {
    i++;
    if (i >= n || !jsmn_is_digit(s[i])) {
      return 0;
    }
    while (i < n && jsmn_is_digit(s[i])) {
      i++;
    }
  }
  if (i < n && (s[i] == 'e' || s[i] == 'E')) {
    i++;
    if (i < n && (s[i] == '+' || s[i] == '-')) {
      i++;
    }
    if (i >= n || !jsmn_is_digit(s[i])) {
      return 0;
    }
    while (i < n && jsmn_is_digit(s[i])) {
      i++;
    }
  }
  return i == n;
}

static int jsmn_only_ws(const char *js, size_t from, size_t to) {
  for (; from < to; from++) {
    if (!jsmn_is_ws(js[from])) {
      return 0;
    }
  }
  return 1;
}

/* May a value (or, if is_string, an object key) start at pos? */
static int jsmn_strict_before(const char *js, size_t pos,
                              const jsmntok_t *tokens, int toksuper,
                              int is_string) {
  char prev;
  if (tokens == NULL || toksuper < 0) {
    return 1;
  }
  prev = jsmn_prev(js, pos);
  switch (tokens[toksuper].type) {
  case JSMN_ARRAY:
    return prev == '[' || prev == ',';
  case JSMN_OBJECT:
    return is_string && (prev == '{' || prev == ',');
  case JSMN_STRING: /* a key awaiting its value */
    return prev == ':';
  default:
    return 0;
  }
}

#endif /* JSMN_STRICT */

/* Parse an unquoted primitive starting at parser->pos. On success parser->pos
 * is left on the last character of the primitive. On error pos is unchanged. */
static int jsmn_parse_primitive(jsmn_parser *parser, const char *js,
                                const size_t len, jsmntok_t *tokens,
                                const unsigned int num_tokens) {
  size_t start = parser->pos;
  size_t i;
  int done = 0;
  int idx;

  for (i = start; i < len; i++) {
    unsigned char c = (unsigned char)js[i];
    if (c == '\t' || c == '\r' || c == '\n' || c == ' ' || c == ',' ||
        c == ']' || c == '}' || c == ':') {
      done = 1;
      break;
    }
    if (c < 32 || c == 127) {
      return JSMN_ERROR_INVAL;
    }
  }
  if (!done) {
    /* Input ended inside the primitive: more digits may follow. Only a
     * top-level primitive of a lenient parse is accepted as complete. */
#ifdef JSMN_STRICT
    return JSMN_ERROR_PART;
#else
    /* Accept only when no container is open (in counting mode toksuper is
     * the nesting depth; otherwise look for an unclosed token). */
    if (tokens == NULL) {
      if (parser->toksuper != -1) {
        return JSMN_ERROR_PART;
      }
    } else {
      int k;
      for (k = (int)parser->toknext - 1; k >= 0; k--) {
        if (tokens[k].end == -1) {
          return JSMN_ERROR_PART;
        }
      }
    }
#endif
  }
#ifdef JSMN_STRICT
  if (!jsmn_valid_primitive(js + start, i - start)) {
    return JSMN_ERROR_INVAL;
  }
#endif
  idx = jsmn_new_token(parser, tokens, num_tokens, JSMN_PRIMITIVE, (int)start,
                       (int)i, parser->toksuper);
  if (idx < 0) {
    return JSMN_ERROR_NOMEM;
  }
  parser->pos = (unsigned int)(i - 1);
  return 0;
}

/* Parse a quoted string starting at parser->pos (the opening quote). On
 * success parser->pos is left on the closing quote. On error pos is
 * unchanged so that the call can be repeated with more data. */
static int jsmn_parse_string(jsmn_parser *parser, const char *js,
                             const size_t len, jsmntok_t *tokens,
                             const unsigned int num_tokens) {
  size_t start = parser->pos;
  size_t i = start + 1;
  int idx;

  while (i < len) {
    unsigned char c = (unsigned char)js[i];
    if (c == '"') {
      idx = jsmn_new_token(parser, tokens, num_tokens, JSMN_STRING,
                           (int)start + 1, (int)i, parser->toksuper);
      if (idx < 0) {
        return JSMN_ERROR_NOMEM;
      }
      parser->pos = (unsigned int)i;
      return 0;
    }
    if (c == '\\') {
      int k;
      if (i + 1 >= len) {
        return JSMN_ERROR_PART;
      }
      i++;
      switch (js[i]) {
      case '"':
      case '/':
      case '\\':
      case 'b':
      case 'f':
      case 'r':
      case 'n':
      case 't':
        break;
      case 'u':
        for (k = 0; k < 4; k++) {
          char h;
          if (i + 1 >= len) {
            return JSMN_ERROR_PART;
          }
          i++;
          h = js[i];
          if (!((h >= '0' && h <= '9') || (h >= 'A' && h <= 'F') ||
                (h >= 'a' && h <= 'f'))) {
            return JSMN_ERROR_INVAL;
          }
        }
        break;
      default:
        return JSMN_ERROR_INVAL;
      }
    }
#ifdef JSMN_STRICT
    else if (c < 32) {
      return JSMN_ERROR_INVAL;
    }
#endif
    i++;
  }
  return JSMN_ERROR_PART;
}

JSMN_API void jsmn_init(jsmn_parser *parser) {
  parser->pos = 0;
  parser->toknext = 0;
  parser->toksuper = -1;
}

JSMN_API int jsmn_parse(jsmn_parser *parser, const char *js, const size_t len,
                        jsmntok_t *tokens, const unsigned int num_tokens) {
  int r;
  int i;
  int idx;
  jsmntype_t type;

  /* In counting mode (tokens == NULL) there is no token storage to consult,
   * so toksuper is used as a plain nesting depth (-1 = top level) and only
   * bracket balance, strings and primitives are validated. */
  for (; (size_t)parser->pos < len; parser->pos++) {
    char c = js[parser->pos];
    switch (c) {
    case '{':
    case '[':
#ifdef JSMN_STRICT
      if (!jsmn_strict_before(js, parser->pos, tokens, parser->toksuper, 0)) {
        return JSMN_ERROR_INVAL;
      }
#endif
      idx = jsmn_new_token(parser, tokens, num_tokens,
                           c == '{' ? JSMN_OBJECT : JSMN_ARRAY,
                           (int)parser->pos, -1, parser->toksuper);
      if (idx < 0) {
        return JSMN_ERROR_NOMEM;
      }
      if (tokens != NULL) {
        if (parser->toksuper != -1) {
          tokens[parser->toksuper].size++;
        }
        parser->toksuper = idx;
      } else {
        parser->toksuper++;
      }
      break;

    case '}':
    case ']':
      if (tokens == NULL) {
        if (parser->toksuper < 0) {
          return JSMN_ERROR_INVAL;
        }
        parser->toksuper--;
        break;
      }
      type = (c == '}') ? JSMN_OBJECT : JSMN_ARRAY;
#ifdef JSMN_PARENT_LINKS
      i = parser->toksuper;
      while (i != -1 && tokens[i].type != JSMN_OBJECT &&
             tokens[i].type != JSMN_ARRAY) {
        i = tokens[i].parent;
      }
#else
      for (i = (int)parser->toknext - 1; i >= 0; i--) {
        if (tokens[i].end == -1) {
          break;
        }
      }
#endif
      if (i < 0 || tokens[i].type != type) {
        return JSMN_ERROR_INVAL;
      }
#ifdef JSMN_STRICT
      if (parser->toksuper != -1) {
        const jsmntok_t *s = &tokens[parser->toksuper];
        if ((s->type == JSMN_STRING && s->size == 0) ||
            (s->type == JSMN_OBJECT &&
             (int)parser->toknext - 1 != parser->toksuper) ||
            jsmn_prev(js, parser->pos) == ',') {
          return JSMN_ERROR_INVAL;
        }
      }
#endif
      tokens[i].end = (int)parser->pos + 1;
#ifdef JSMN_PARENT_LINKS
      parser->toksuper = tokens[i].parent;
#else
      if (i > 0 && tokens[i - 1].type == JSMN_STRING &&
          tokens[i - 1].size == 1) {
        parser->toksuper = i - 1; /* the key owning this container */
      } else {
        parser->toksuper = -1;
        for (r = i - 1; r >= 0; r--) {
          if (tokens[r].end == -1) {
            parser->toksuper = r;
            break;
          }
        }
      }
#endif
      break;

    case '"':
#ifdef JSMN_STRICT
      if (!jsmn_strict_before(js, parser->pos, tokens, parser->toksuper, 1)) {
        return JSMN_ERROR_INVAL;
      }
#endif
      r = jsmn_parse_string(parser, js, len, tokens, num_tokens);
      if (r < 0) {
        return r;
      }
      if (tokens != NULL && parser->toksuper != -1) {
        tokens[parser->toksuper].size++;
      }
      break;

    case '\t':
    case '\r':
    case '\n':
    case ' ':
      break;

    case ':':
      if (tokens == NULL) {
        break;
      }
#ifdef JSMN_STRICT
      if (parser->toksuper == -1 ||
          tokens[parser->toksuper].type != JSMN_OBJECT ||
          parser->toknext == 0 ||
          tokens[parser->toknext - 1].type != JSMN_STRING ||
          tokens[parser->toknext - 1].size != 0 ||
          !jsmn_only_ws(js, (size_t)tokens[parser->toknext - 1].end + 1,
                        parser->pos)) {
        return JSMN_ERROR_INVAL;
      }
#endif
      parser->toksuper = (int)parser->toknext - 1;
      break;

    case ',':
      if (tokens == NULL) {
        break;
      }
#ifdef JSMN_STRICT
      {
        char prev = jsmn_prev(js, parser->pos);
        if (parser->toksuper == -1 ||
            tokens[parser->toksuper].type == JSMN_OBJECT || prev == 0 ||
            prev == '[' || prev == '{' || prev == ',' || prev == ':') {
          return JSMN_ERROR_INVAL;
        }
      }
#endif
      if (parser->toksuper != -1 &&
          tokens[parser->toksuper].type != JSMN_OBJECT &&
          tokens[parser->toksuper].type != JSMN_ARRAY) {
#ifdef JSMN_PARENT_LINKS
        parser->toksuper = tokens[parser->toksuper].parent;
#else
        for (i = (int)parser->toknext - 1; i >= 0; i--) {
          if (tokens[i].end == -1) {
            parser->toksuper = i;
            break;
          }
        }
#endif
      }
      break;

    default:
#ifdef JSMN_STRICT
      if (!(c == '-' || (c >= '0' && c <= '9') || c == 't' || c == 'f' ||
            c == 'n')) {
        return JSMN_ERROR_INVAL;
      }
      if (!jsmn_strict_before(js, parser->pos, tokens, parser->toksuper, 0)) {
        return JSMN_ERROR_INVAL;
      }
#endif
      r = jsmn_parse_primitive(parser, js, len, tokens, num_tokens);
      if (r < 0) {
        return r;
      }
      if (tokens != NULL && parser->toksuper != -1) {
        tokens[parser->toksuper].size++;
      }
      break;
    }
  }

  if (tokens != NULL) {
    for (i = (int)parser->toknext - 1; i >= 0; i--) {
      if (tokens[i].end == -1) {
        return JSMN_ERROR_PART;
      }
    }
  } else if (parser->toksuper >= 0) {
    return JSMN_ERROR_PART;
  }
  return (int)parser->toknext;
}

#endif /* JSMN_HEADER */

#ifdef __cplusplus
}
#endif

#endif /* JSMN_H */
