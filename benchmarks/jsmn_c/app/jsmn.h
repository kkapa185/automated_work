/*
 * jsmn.h - minimalistic, allocation-free JSON tokenizer (C89).
 *
 * Define JSMN_HEADER to get declarations only, JSMN_STATIC to make all
 * functions static, JSMN_STRICT for lexical strictness and JSMN_PARENT_LINKS
 * to record the parent index of every token.
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
  JSMN_ERROR_NOMEM = -1, /* not enough tokens */
  JSMN_ERROR_INVAL = -2, /* invalid character / structure */
  JSMN_ERROR_PART = -3   /* input incomplete, more data expected */
};

typedef struct jsmntok {
  jsmntype_t type;
  int start;
  int end;
  int size;
#ifdef JSMN_PARENT_LINKS
  int parent;
#endif
} jsmntok_t;

typedef struct jsmn_parser {
  unsigned int pos;     /* offset in the JSON string */
  unsigned int toknext; /* next token to allocate */
  int toksuper;         /* superior token node, e.g. parent object or array */
} jsmn_parser;

JSMN_API void jsmn_init(jsmn_parser *parser);

JSMN_API int jsmn_parse(jsmn_parser *parser, const char *js, const size_t len,
                        jsmntok_t *tokens, const unsigned int num_tokens);

#ifndef JSMN_HEADER

static jsmntok_t *jsmn_alloc_token(jsmn_parser *parser, jsmntok_t *tokens,
                                   const size_t num_tokens) {
  jsmntok_t *tok;
  if (parser->toknext >= num_tokens) {
    return NULL;
  }
  tok = &tokens[parser->toknext++];
  tok->start = tok->end = -1;
  tok->size = 0;
#ifdef JSMN_PARENT_LINKS
  tok->parent = -1;
#endif
  return tok;
}

static void jsmn_fill_token(jsmntok_t *token, const jsmntype_t type,
                            const int start, const int end) {
  token->type = type;
  token->start = start;
  token->end = end;
  token->size = 0;
}

/* Scan a primitive starting at parser->pos. In counting mode (tokens == NULL)
 * no token is stored. On success parser->pos is left on the last character of
 * the primitive. */
static int jsmn_parse_primitive(jsmn_parser *parser, const char *js,
                                const size_t len, jsmntok_t *tokens,
                                const size_t num_tokens) {
  jsmntok_t *token;
  int start = (int)parser->pos;

  for (; parser->pos < len && js[parser->pos] != '\0'; parser->pos++) {
    switch (js[parser->pos]) {
#ifndef JSMN_STRICT
    case ':':
#endif
    case '\t':
    case '\r':
    case '\n':
    case ' ':
    case ',':
    case ']':
    case '}':
      goto found;
    default:
      break;
    }
    if (js[parser->pos] < 32 || js[parser->pos] >= 127) {
      parser->pos = (unsigned int)start;
      return JSMN_ERROR_INVAL;
    }
  }
#ifdef JSMN_STRICT
  /* In strict mode a primitive must be terminated by a delimiter. */
  parser->pos = (unsigned int)start;
  return JSMN_ERROR_PART;
#endif

found:
  if (tokens != NULL) {
    token = jsmn_alloc_token(parser, tokens, num_tokens);
    if (token == NULL) {
      parser->pos = (unsigned int)start;
      return JSMN_ERROR_NOMEM;
    }
    jsmn_fill_token(token, JSMN_PRIMITIVE, start, (int)parser->pos);
#ifdef JSMN_PARENT_LINKS
    token->parent = parser->toksuper;
#endif
  }
  parser->pos--;
  return 0;
}

/* Scan a quoted string; parser->pos is on the opening quote. On success it is
 * left on the closing quote. */
static int jsmn_parse_string(jsmn_parser *parser, const char *js,
                             const size_t len, jsmntok_t *tokens,
                             const size_t num_tokens) {
  jsmntok_t *token;
  int start = (int)parser->pos;
  int i;

  parser->pos++;
  for (; parser->pos < len && js[parser->pos] != '\0'; parser->pos++) {
    char c = js[parser->pos];

    if (c == '\"') {
      if (tokens != NULL) {
        token = jsmn_alloc_token(parser, tokens, num_tokens);
        if (token == NULL) {
          parser->pos = (unsigned int)start;
          return JSMN_ERROR_NOMEM;
        }
        jsmn_fill_token(token, JSMN_STRING, start + 1, (int)parser->pos);
#ifdef JSMN_PARENT_LINKS
        token->parent = parser->toksuper;
#endif
      }
      return 0;
    }

    if (c == '\\' && parser->pos + 1 < len) {
      parser->pos++;
      switch (js[parser->pos]) {
      case '\"':
      case '/':
      case '\\':
      case 'b':
      case 'f':
      case 'r':
      case 'n':
      case 't':
        break;
      case 'u':
        parser->pos++;
        for (i = 0; i < 4 && parser->pos < len && js[parser->pos] != '\0';
             i++) {
          char h = js[parser->pos];
          if (!((h >= '0' && h <= '9') || (h >= 'A' && h <= 'F') ||
                (h >= 'a' && h <= 'f'))) {
            parser->pos = (unsigned int)start;
            return JSMN_ERROR_INVAL;
          }
          parser->pos++;
        }
        parser->pos--;
        break;
      default:
        parser->pos = (unsigned int)start;
        return JSMN_ERROR_INVAL;
      }
    }
  }
  parser->pos = (unsigned int)start;
  return JSMN_ERROR_PART;
}

JSMN_API int jsmn_parse(jsmn_parser *parser, const char *js, const size_t len,
                        jsmntok_t *tokens, const unsigned int num_tokens) {
  int r;
  int i;
  jsmntok_t *token;
  int count = (int)parser->toknext;

  for (; parser->pos < len && js[parser->pos] != '\0'; parser->pos++) {
    char c = js[parser->pos];
    jsmntype_t type;

    switch (c) {
    case '{':
    case '[':
      count++;
      if (tokens == NULL) {
        break;
      }
      token = jsmn_alloc_token(parser, tokens, num_tokens);
      if (token == NULL) {
        return JSMN_ERROR_NOMEM;
      }
      if (parser->toksuper != -1) {
        jsmntok_t *t = &tokens[parser->toksuper];
#ifdef JSMN_STRICT
        /* An object or array cannot be an object key. */
        if (t->type == JSMN_OBJECT) {
          return JSMN_ERROR_INVAL;
        }
#endif
        t->size++;
#ifdef JSMN_PARENT_LINKS
        token->parent = parser->toksuper;
#endif
      }
      token->type = (c == '{' ? JSMN_OBJECT : JSMN_ARRAY);
      token->start = (int)parser->pos;
      parser->toksuper = (int)parser->toknext - 1;
      break;

    case '}':
    case ']':
      if (tokens == NULL) {
        break;
      }
      type = (c == '}' ? JSMN_OBJECT : JSMN_ARRAY);
      /* find the innermost token that is still open */
#ifdef JSMN_PARENT_LINKS
      if (parser->toknext < 1) {
        return JSMN_ERROR_INVAL;
      }
      i = (int)parser->toknext - 1;
      while (i != -1 && !(tokens[i].start != -1 && tokens[i].end == -1)) {
        i = tokens[i].parent;
      }
#else
      for (i = (int)parser->toknext - 1; i >= 0; i--) {
        if (tokens[i].start != -1 && tokens[i].end == -1) {
          break;
        }
      }
#endif
      if (i < 0 || tokens[i].type != type) {
        return JSMN_ERROR_INVAL;
      }
      token = &tokens[i];
      token->end = (int)parser->pos + 1;
#ifdef JSMN_PARENT_LINKS
      parser->toksuper = token->parent;
#else
      parser->toksuper = -1;
      for (i = i - 1; i >= 0; i--) {
        if (tokens[i].start != -1 && tokens[i].end == -1) {
          parser->toksuper = i;
          break;
        }
      }
#endif
      break;

    case '\"':
      r = jsmn_parse_string(parser, js, len, tokens, num_tokens);
      if (r < 0) {
        return r;
      }
      count++;
      if (parser->toksuper != -1 && tokens != NULL) {
        tokens[parser->toksuper].size++;
      }
      break;

    case '\t':
    case '\r':
    case '\n':
    case ' ':
      break;

    case ':':
      parser->toksuper = (int)parser->toknext - 1;
      break;

    case ',':
      if (tokens != NULL && parser->toksuper != -1 &&
          tokens[parser->toksuper].type != JSMN_ARRAY &&
          tokens[parser->toksuper].type != JSMN_OBJECT) {
#ifdef JSMN_PARENT_LINKS
        parser->toksuper = tokens[parser->toksuper].parent;
#else
        for (i = (int)parser->toknext - 1; i >= 0; i--) {
          if (tokens[i].type == JSMN_ARRAY || tokens[i].type == JSMN_OBJECT) {
            if (tokens[i].start != -1 && tokens[i].end == -1) {
              parser->toksuper = i;
              break;
            }
          }
        }
#endif
      }
      break;

#ifdef JSMN_STRICT
    /* In strict mode primitives are: numbers and booleans/null */
    case '-':
    case '0':
    case '1':
    case '2':
    case '3':
    case '4':
    case '5':
    case '6':
    case '7':
    case '8':
    case '9':
    case 't':
    case 'f':
    case 'n':
      /* And they must not be keys of the object */
      if (tokens != NULL && parser->toksuper != -1) {
        const jsmntok_t *t = &tokens[parser->toksuper];
        if (t->type == JSMN_OBJECT ||
            (t->type == JSMN_STRING && t->size != 0)) {
          return JSMN_ERROR_INVAL;
        }
      }
#else
    /* In non-strict mode every unquoted value is a primitive */
    default:
#endif
      r = jsmn_parse_primitive(parser, js, len, tokens, num_tokens);
      if (r < 0) {
        return r;
      }
      count++;
      if (parser->toksuper != -1 && tokens != NULL) {
        tokens[parser->toksuper].size++;
      }
      break;

#ifdef JSMN_STRICT
    /* Unexpected char in strict mode */
    default:
      return JSMN_ERROR_INVAL;
#endif
    }
  }

  if (tokens != NULL) {
    for (i = (int)parser->toknext - 1; i >= 0; i--) {
      /* Unmatched opened object or array */
      if (tokens[i].start != -1 && tokens[i].end == -1) {
        return JSMN_ERROR_PART;
      }
    }
  }

  return count;
}

JSMN_API void jsmn_init(jsmn_parser *parser) {
  parser->pos = 0;
  parser->toknext = 0;
  parser->toksuper = -1;
}

#endif /* JSMN_HEADER */

#ifdef __cplusplus
}
#endif

#endif /* JSMN_H */
