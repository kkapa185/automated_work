/* Lexer + parser: source text -> AST with resolved variables (locals, upvalues, globals). */
#include "lua.h"
#include <ctype.h>
#include <stdarg.h>

enum {
  TK_AND = 257, TK_BREAK, TK_DO, TK_ELSE, TK_ELSEIF, TK_END, TK_FALSE, TK_FOR, TK_FUNCTION, TK_GOTO, TK_GLOBAL,
  TK_IF, TK_IN, TK_LOCAL, TK_NIL, TK_NOT, TK_OR, TK_REPEAT, TK_RETURN, TK_THEN, TK_TRUE, TK_UNTIL, TK_WHILE,
  TK_IDIV, TK_CONCAT, TK_DOTS, TK_EQ, TK_GE, TK_LE, TK_NE, TK_SHL, TK_SHR, TK_DBCOLON, TK_EOS,
  TK_FLT, TK_INT, TK_NAME, TK_STRING
};
static const char *const tknames[] = {
  "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "global", "if", "in",
  "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
  "//", "..", "...", "==", ">=", "<=", "~=", "<<", ">>", "::", "<eof>", "<number>", "<integer>", "<name>", "<string>"
};

typedef struct Token { int t; Str *s; lint i; lnum n; int line; const char *start; } Token;

typedef struct PendGoto { Node *g; Str *name; int line; int nact; } PendGoto;
typedef struct BlockScope {
  struct BlockScope *prev; int nact0, nslots0; int isloop, isrepeat, hasclose, notail;
  Label **labels; int nlabels, caplabels;
  PendGoto *pend; int npend, cappend;
  Node **stmts; int nstmts, capstmts; int lastnonvoid;
} BlockScope;

typedef struct FuncState {
  struct FuncState *parent; Proto *p; BlockScope *bs;
  VarInfo **act; int nact, capact; int nslotsact;
  VarInfo **upvi; UpDesc *ups; int nup, capup;
  Node **refs; int nrefs, caprefs;
  int is_vararg;
} FuncState;

typedef struct Parser {
  const char *src, *p, *end; int line;
  Chunk *ck; State *L;
  Token t, ahead; int hasahead; int lastline;
  FuncState *fs; VarInfo *env_vi;
  jmp_buf jb; char errbuf[600]; int level;
  char *buf; size_t bufn, bufcap;
  const char *tokstart;
} Parser;

/* ---------- errors ---------- */
static void tok2str(Parser *P, int t, char *out, size_t sz, Token *tk) {
  if (t < 257) { if (isprint(t)) snprintf(out, sz, "%c", t); else snprintf(out, sz, "<\\%d>", t); }
  else if (t == TK_NAME || t == TK_STRING || t == TK_FLT || t == TK_INT) {
    size_t n = (size_t)(P->p - tk->start); if (n > sz - 1) n = sz - 1;
    memcpy(out, tk->start, n); out[n] = 0;
  } else snprintf(out, sz, "%s", tknames[t - 257]);
}
static void __attribute__((noreturn)) perr_at(Parser *P, int line, const char *msg, const char *near) {
  char src[80]; strncpy(src, P->ck->short_src, sizeof src - 1); src[sizeof src - 1] = 0;
  if (near) snprintf(P->errbuf, sizeof P->errbuf, "%s:%d: %s near %s", src, line, msg, near);
  else snprintf(P->errbuf, sizeof P->errbuf, "%s:%d: %s", src, line, msg);
  longjmp(P->jb, 1);
}
static void __attribute__((noreturn)) lexerr(Parser *P, const char *msg, int tok) {
  char nb[200];
  if (tok && tok != TK_EOS) {
    char tmp[150];
    if (tok == TK_STRING || tok == TK_NAME || tok == TK_INT || tok == TK_FLT) {
      size_t n = (size_t)(P->p - P->tokstart); if (n > 100) n = 100;
      memcpy(tmp, P->tokstart, n); tmp[n] = 0;
    } else tok2str(P, tok, tmp, sizeof tmp, &P->t);
    snprintf(nb, sizeof nb, "'%s'", tmp);
    perr_at(P, P->line, msg, nb);
  }
  perr_at(P, P->line, msg, "<eof>");
}
static void __attribute__((noreturn)) synerr(Parser *P, const char *msg) {
  char nb[200], tmp[150];
  if (P->t.t == TK_EOS) perr_at(P, P->t.line, msg, "<eof>");
  tok2str(P, P->t.t, tmp, sizeof tmp, &P->t);
  snprintf(nb, sizeof nb, "'%s'", tmp);
  perr_at(P, P->t.line, msg, nb);
}
static void __attribute__((noreturn)) semerr(Parser *P, int line, const char *fmt, ...) {
  char buf[300]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
  perr_at(P, line, buf, NULL);
}

static Str *pstr(Parser *P, const char *s, size_t len) {
  Str *x = str_new(s, len); chunk_addconst(P->ck, x); return x;
}

/* ---------- lexer ---------- */
#define CUR(P) ((P)->p < (P)->end ? (int)(unsigned char)*(P)->p : -1)
#define PEEK(P, k) ((P)->p + (k) < (P)->end ? (int)(unsigned char)(P)->p[k] : -1)

static void bufreset(Parser *P) { P->bufn = 0; }
static void bufadd(Parser *P, int c) {
  if (P->bufn + 1 >= P->bufcap) { P->bufcap = P->bufcap ? P->bufcap * 2 : 256; P->buf = realloc(P->buf, P->bufcap); }
  P->buf[P->bufn++] = (char)c;
}
static void newline(Parser *P) {
  int old = CUR(P); P->p++;
  int c = CUR(P);
  if ((c == '\n' || c == '\r') && c != old) P->p++;
  P->line++;
}
static int skip_sep(Parser *P) { /* at '[' or ']' ; returns level+2 if well formed, 1 if single, 0 if malformed */
  const char *q = P->p; int c = *q; size_t count = 0; q++;
  while (q < P->end && *q == '=') { q++; count++; }
  if (q < P->end && *q == c) return (int)count + 2;
  return count == 0 ? 1 : 0;
}
static void read_long(Parser *P, Token *tk, int sep, int iscomment) {
  int startline = P->line;
  P->p += sep; /* skip [==[ */
  if (CUR(P) == '\r' || CUR(P) == '\n') newline(P);
  bufreset(P);
  for (;;) {
    int c = CUR(P);
    if (c < 0) {
      char m[80]; snprintf(m, sizeof m, "unfinished long %s (starting at line %d)", iscomment ? "comment" : "string", startline);
      lexerr(P, m, 0);
    }
    if (c == ']') {
      const char *q = P->p + 1; int cnt = 0;
      while (q < P->end && *q == '=') { q++; cnt++; }
      if (q < P->end && *q == ']' && cnt + 2 == sep) { P->p = q + 1; break; }
      bufadd(P, c); P->p++;
    } else if (c == '\n' || c == '\r') { bufadd(P, '\n'); newline(P); }
    else { bufadd(P, c); P->p++; }
  }
  if (!iscomment) tk->s = pstr(P, P->buf ? P->buf : "", P->bufn);
}
static int hexval(int c) { return isdigit(c) ? c - '0' : tolower(c) - 'a' + 10; }
static void utf8_esc(Parser *P, unsigned long x) {
  char b[8]; int n = 1;
  if (x < 0x80) b[7] = (char)x;
  else {
    unsigned int mfb = 0x3f;
    do { b[8 - (n++)] = (char)(0x80 | (x & 0x3f)); x >>= 6; mfb >>= 1; } while (x > mfb);
    b[8 - n] = (char)(((~mfb << 1) | x) & 0xff);
  }
  for (int i = 8 - n; i < 8; i++) bufadd(P, b[i]);
  if (x < 0x80 && n == 1) { /* handled above */ }
}
static void read_string(Parser *P, Token *tk, int del) {
  P->p++;
  bufreset(P);
  for (;;) {
    int c = CUR(P);
    if (c == del) { P->p++; break; }
    if (c < 0) lexerr(P, "unfinished string", TK_EOS);
    if (c == '\n' || c == '\r') lexerr(P, "unfinished string", TK_STRING);
    if (c == '\\') {
      P->p++; c = CUR(P);
      switch (c) {
        case 'a': bufadd(P, '\a'); P->p++; break;
        case 'b': bufadd(P, '\b'); P->p++; break;
        case 'f': bufadd(P, '\f'); P->p++; break;
        case 'n': bufadd(P, '\n'); P->p++; break;
        case 'r': bufadd(P, '\r'); P->p++; break;
        case 't': bufadd(P, '\t'); P->p++; break;
        case 'v': bufadd(P, '\v'); P->p++; break;
        case 'x': {
          P->p++; int v = 0;
          for (int i = 0; i < 2; i++) {
            int d = CUR(P);
            if (d < 0 || !isxdigit(d)) { if (d >= 0) P->p++; lexerr(P, "hexadecimal digit expected", TK_STRING); }
            v = v * 16 + hexval(d); P->p++;
          }
          bufadd(P, v); break;
        }
        case 'u': {
          P->p++;
          if (CUR(P) != '{') { if (CUR(P) >= 0) P->p++; lexerr(P, "missing '{' in \\u{xxxx}", TK_STRING); }
          P->p++;
          unsigned long r = 0; int any = 0;
          while (CUR(P) >= 0 && isxdigit(CUR(P))) {
            r = r * 16 + (unsigned long)hexval(CUR(P)); any = 1; P->p++;
            if (r > 0x7FFFFFFFUL) lexerr(P, "UTF-8 value too large", TK_STRING);
          }
          if (!any) { if (CUR(P) >= 0) P->p++; lexerr(P, "hexadecimal digit expected", TK_STRING); }
          if (CUR(P) != '}') { if (CUR(P) >= 0) P->p++; lexerr(P, "missing '}' in \\u{xxxx}", TK_STRING); }
          P->p++;
          utf8_esc(P, r); break;
        }
        case '\n': case '\r': bufadd(P, '\n'); newline(P); break;
        case '\\': case '"': case '\'': bufadd(P, c); P->p++; break;
        case -1: lexerr(P, "unfinished string", TK_EOS);
        case 'z': {
          P->p++;
          while (CUR(P) >= 0 && isspace(CUR(P))) { if (CUR(P) == '\n' || CUR(P) == '\r') newline(P); else P->p++; }
          break;
        }
        default: {
          if (!isdigit(c)) { P->p++; lexerr(P, "invalid escape sequence", TK_STRING); }
          int v = 0;
          for (int i = 0; i < 3 && CUR(P) >= 0 && isdigit(CUR(P)); i++) { v = v * 10 + (CUR(P) - '0'); P->p++; }
          if (v > 255) lexerr(P, "decimal escape too large", TK_STRING);
          bufadd(P, v);
        }
      }
    } else { bufadd(P, c); P->p++; }
  }
  tk->s = pstr(P, P->buf ? P->buf : "", P->bufn);
}
static int read_numeral(Parser *P, Token *tk) {
  const char *s = P->p; const char *expo = "Ee";
  if (*P->p == '0' && (PEEK(P, 1) == 'x' || PEEK(P, 1) == 'X')) { expo = "Pp"; P->p += 2; }
  for (;;) {
    int c = CUR(P);
    if (c >= 0 && strchr(expo, c)) { P->p++; if (CUR(P) == '+' || CUR(P) == '-') P->p++; }
    else if (c >= 0 && (isxdigit(c) || c == '.')) P->p++;
    else break;
  }
  if (CUR(P) >= 0 && (isalpha(CUR(P)) || CUR(P) == '_')) P->p++;
  Value v;
  if (!str2number(s, (size_t)(P->p - s), &v)) lexerr(P, "malformed number", TK_FLT);
  if (v.t == T_INT) { tk->i = v.u.i; return TK_INT; }
  tk->n = v.u.n; return TK_FLT;
}
static const char *const reserved[] = { "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
  "goto", "global", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while" };

static void lex(Parser *P, Token *tk) {
  for (;;) {
    int c = CUR(P);
    tk->line = P->line; tk->start = P->p; P->tokstart = P->p;
    switch (c) {
      case -1: tk->t = TK_EOS; return;
      case '\n': case '\r': newline(P); continue;
      case ' ': case '\f': case '\t': case '\v': P->p++; continue;
      case '-':
        if (PEEK(P, 1) != '-') { P->p++; tk->t = '-'; return; }
        P->p += 2;
        if (CUR(P) == '[') {
          int sep = skip_sep(P);
          if (sep >= 2) { read_long(P, tk, sep, 1); continue; }
        }
        while (CUR(P) >= 0 && CUR(P) != '\n' && CUR(P) != '\r') P->p++;
        continue;
      case '[': {
        int sep = skip_sep(P);
        if (sep >= 2) { read_long(P, tk, sep, 0); tk->t = TK_STRING; return; }
        if (sep == 0) lexerr(P, "invalid long string delimiter", '[');
        P->p++; tk->t = '['; return;
      }
      case '=': P->p++; if (CUR(P) == '=') { P->p++; tk->t = TK_EQ; } else tk->t = '='; return;
      case '<': P->p++; if (CUR(P) == '=') { P->p++; tk->t = TK_LE; } else if (CUR(P) == '<') { P->p++; tk->t = TK_SHL; } else tk->t = '<'; return;
      case '>': P->p++; if (CUR(P) == '=') { P->p++; tk->t = TK_GE; } else if (CUR(P) == '>') { P->p++; tk->t = TK_SHR; } else tk->t = '>'; return;
      case '/': P->p++; if (CUR(P) == '/') { P->p++; tk->t = TK_IDIV; } else tk->t = '/'; return;
      case '~': P->p++; if (CUR(P) == '=') { P->p++; tk->t = TK_NE; } else tk->t = '~'; return;
      case ':': P->p++; if (CUR(P) == ':') { P->p++; tk->t = TK_DBCOLON; } else tk->t = ':'; return;
      case '"': case '\'': read_string(P, tk, c); tk->t = TK_STRING; return;
      case '.':
        if (PEEK(P, 1) == '.') {
          if (PEEK(P, 2) == '.') { P->p += 3; tk->t = TK_DOTS; return; }
          P->p += 2; tk->t = TK_CONCAT; return;
        }
        if (PEEK(P, 1) >= 0 && isdigit(PEEK(P, 1))) { tk->t = read_numeral(P, tk); return; }
        P->p++; tk->t = '.'; return;
      case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
        tk->t = read_numeral(P, tk); return;
      default:
        if (isalpha(c) || c == '_') {
          const char *s = P->p;
          while (CUR(P) >= 0 && (isalnum(CUR(P)) || CUR(P) == '_')) P->p++;
          size_t len = (size_t)(P->p - s);
          for (int i = 0; i < (int)(sizeof reserved / sizeof *reserved); i++)
            if (strlen(reserved[i]) == len && memcmp(reserved[i], s, len) == 0) { tk->t = TK_AND + i; return; }
          tk->s = pstr(P, s, len); tk->t = TK_NAME; return;
        }
        P->p++; tk->t = c; return;
    }
  }
}
static void next(Parser *P) {
  P->lastline = P->line;
  if (P->hasahead) { P->t = P->ahead; P->hasahead = 0; }
  else lex(P, &P->t);
}
static int lookahead(Parser *P) {
  if (!P->hasahead) {
    const char *sp = P->tokstart;
    lex(P, &P->ahead); P->hasahead = 1; P->tokstart = sp;
  }
  return P->ahead.t;
}
static int testnext(Parser *P, int t) { if (P->t.t == t) { next(P); return 1; } return 0; }
static void tokstr_for_expect(int t, char *out, size_t sz) {
  if (t < 257) snprintf(out, sz, "'%c'", t); else snprintf(out, sz, "'%s'", tknames[t - 257]);
}
static void check(Parser *P, int t) {
  if (P->t.t != t) { char b[64], m[100]; tokstr_for_expect(t, b, sizeof b); snprintf(m, sizeof m, "%s expected", b); synerr(P, m); }
}
static void expect(Parser *P, int t) { check(P, t); next(P); }
static void expect_match(Parser *P, int what, int who, int line) {
  if (P->t.t != what) {
    if (line == P->t.line) { check(P, what); }
    char a[64], b[64], m[160]; tokstr_for_expect(what, a, sizeof a); tokstr_for_expect(who, b, sizeof b);
    snprintf(m, sizeof m, "%s expected (to close %s at line %d)", a, b, line);
    synerr(P, m);
  }
  next(P);
}
static Str *expect_name(Parser *P) { check(P, TK_NAME); Str *s = P->t.s; next(P); return s; }

/* ---------- AST helpers ---------- */
static Node *newnode(Parser *P, int k, int line) {
  Node *n = arena_alloc(P->ck, sizeof(Node)); n->k = (uint8_t)k; n->line = line; return n;
}
typedef struct NVec { Node **v; int n, cap; } NVec;
static void nv_push(NVec *v, Node *n) {
  if (v->n == v->cap) { v->cap = v->cap ? v->cap * 2 : 8; v->v = realloc(v->v, (size_t)v->cap * sizeof(Node *)); }
  v->v[v->n++] = n;
}
static Node **nv_arena(Parser *P, NVec *v) {
  Node **a = arena_alloc(P->ck, (size_t)(v->n ? v->n : 1) * sizeof(Node *));
  if (v->n) memcpy(a, v->v, (size_t)v->n * sizeof(Node *));
  free(v->v); v->v = NULL; return a;
}
static void enterlevel(Parser *P) { if (++P->level > 190) semerr(P, P->t.line, "chunk has too many syntax levels"); }
#define leavelevel(P) ((P)->level--)

/* ---------- scopes ---------- */
static void fs_addact(FuncState *fs, VarInfo *vi) {
  if (fs->nact == fs->capact) { fs->capact = fs->capact ? fs->capact * 2 : 16; fs->act = realloc(fs->act, (size_t)fs->capact * sizeof(VarInfo *)); }
  fs->act[fs->nact++] = vi;
}
static VarInfo *new_local(Parser *P, Str *name, int attr) {
  FuncState *fs = P->fs;
  VarInfo *vi = arena_alloc(P->ck, sizeof(VarInfo));
  vi->name = name; vi->slot = fs->nslotsact++; vi->attr = (uint8_t)attr;
  if (fs->nslotsact > fs->p->nslots) fs->p->nslots = fs->nslotsact;
  return vi;
}
static void activate(FuncState *fs, VarInfo *vi) { fs_addact(fs, vi); }

static BlockScope *enter_block(Parser *P, BlockScope *bs, int isloop) {
  memset(bs, 0, sizeof *bs);
  bs->prev = P->fs->bs; bs->nact0 = P->fs->nact; bs->nslots0 = P->fs->nslotsact; bs->isloop = isloop;
  bs->lastnonvoid = -1;
  P->fs->bs = bs;
  return bs;
}
static Block *leave_block(Parser *P, BlockScope *bs) {
  FuncState *fs = P->fs;
  Block *b = arena_alloc(P->ck, sizeof(Block));
  b->n = bs->nstmts; b->hasclose = (uint8_t)bs->hasclose;
  b->stmts = arena_alloc(P->ck, (size_t)(bs->nstmts ? bs->nstmts : 1) * sizeof(Node *));
  if (bs->nstmts) memcpy(b->stmts, bs->stmts, (size_t)bs->nstmts * sizeof(Node *));
  free(bs->stmts);
  b->labels = arena_alloc(P->ck, (size_t)(bs->nlabels ? bs->nlabels : 1) * sizeof(Label *));
  b->nlabels = bs->nlabels;
  for (int i = 0; i < bs->nlabels; i++) {
    Label *l = bs->labels[i]; l->blk = b; b->labels[i] = l;
    l->trailing = !bs->isrepeat && l->idx > bs->lastnonvoid;
  }
  /* resolve pending gotos against this block's labels */
  int keep = 0;
  for (int i = 0; i < bs->npend; i++) {
    PendGoto *pg = &bs->pend[i]; Label *found = NULL;
    for (int j = 0; j < bs->nlabels; j++) if (bs->labels[j]->name == pg->name) { found = bs->labels[j]; break; }
    if (found) {
      if (found->nactive > pg->nact && !found->trailing) {
        VarInfo *v = fs->act[0]; /* find the local being jumped into */
        int idx = bs->nact0 + 0; (void)idx;
        /* the first local declared at slot position pg->nact inside this block */
        for (int a = 0; a < fs->nact; a++) if (fs->act[a]->slot == pg->nact && fs->act[a]->slot >= 0) { v = fs->act[a]; break; }
        semerr(P, pg->line, "<goto %s> at line %d jumps into the scope of local '%s'", pg->name->data, pg->line, v->name->data);
      }
      pg->g->u.lbl = found;
    } else bs->pend[keep++] = *pg;
  }
  bs->npend = keep;
  fs->bs = bs->prev;
  if (keep) {
    if (!bs->prev) {
      PendGoto *pg = &bs->pend[0];
      if (!strcmp(pg->name->data, "\x01break")) semerr(P, pg->line, "break outside a loop at line %d", pg->line);
      semerr(P, pg->line, "no visible label '%s' for <goto> at line %d", pg->name->data, pg->line);
    }
    BlockScope *pb = bs->prev;
    for (int i = 0; i < keep; i++) {
      if (pb->npend == pb->cappend) { pb->cappend = pb->cappend ? pb->cappend * 2 : 4; pb->pend = realloc(pb->pend, (size_t)pb->cappend * sizeof(PendGoto)); }
      pb->pend[pb->npend] = bs->pend[i]; pb->pend[pb->npend].nact = bs->nslots0; pb->npend++;
    }
  }
  free(bs->pend); free(bs->labels);
  fs->nact = bs->nact0; fs->nslotsact = bs->nslots0;
  return b;
}
static void add_stmt(BlockScope *bs, Node *s, int isvoid) {
  if (bs->nstmts == bs->capstmts) { bs->capstmts = bs->capstmts ? bs->capstmts * 2 : 8; bs->stmts = realloc(bs->stmts, (size_t)bs->capstmts * sizeof(Node *)); }
  bs->stmts[bs->nstmts++] = s;
  if (!isvoid) bs->lastnonvoid = bs->nstmts - 1;
}

/* ---------- variable resolution ---------- */
typedef struct Res { int kind; VarInfo *vi; FuncState *owner; int attr; } Res; /* kind 0 local/upval, 1 global */

static int upval_for(FuncState *fs, FuncState *owner, VarInfo *vi) {
  for (int i = 0; i < fs->nup; i++) if (fs->upvi[i] == vi) return i;
  UpDesc d; memset(&d, 0, sizeof d); d.name = vi->name;
  if (fs->parent == owner) { vi->captured = 1; d.fromlocal = 1; d.idx = vi->slot; }
  else { d.fromlocal = 0; d.idx = upval_for(fs->parent, owner, vi); }
  if (fs->nup == fs->capup) {
    fs->capup = fs->capup ? fs->capup * 2 : 4;
    fs->upvi = realloc(fs->upvi, (size_t)fs->capup * sizeof(VarInfo *));
    fs->ups = realloc(fs->ups, (size_t)fs->capup * sizeof(UpDesc));
  }
  fs->upvi[fs->nup] = vi; fs->ups[fs->nup] = d;
  return fs->nup++;
}

static void fs_addref(FuncState *fs, Node *n) {
  if (fs->nrefs == fs->caprefs) { fs->caprefs = fs->caprefs ? fs->caprefs * 2 : 32; fs->refs = realloc(fs->refs, (size_t)fs->caprefs * sizeof(Node *)); }
  fs->refs[fs->nrefs++] = n;
}

static Node *var_node(Parser *P, Str *name, int line);

static Node *env_node(Parser *P, int line) {
  static Str *envname; (void)envname;
  Str *nm = pstr(P, "_ENV", 4);
  return var_node(P, nm, line);
}

static Node *var_node(Parser *P, Str *name, int line) {
  FuncState *fs = P->fs;
  int isenv = name->len == 4 && memcmp(name->data, "_ENV", 4) == 0;
  int seen_gdecl = 0, wild = -1; /* wild: -1 none, 0 rw, 1 const */
  for (FuncState *f = fs; f; f = f->parent) {
    for (int i = f->nact - 1; i >= 0; i--) {
      VarInfo *vi = f->act[i];
      if (vi->slot >= 0) { /* local */
        if (vi->name == name) {
          Node *n;
          if (f == fs) {
            n = newnode(P, E_LOCAL, line); n->u.vi = vi; n->slot = vi->slot; n->name = name; fs_addref(fs, n);
          } else {
            n = newnode(P, E_UPVAL, line); n->slot = upval_for(fs, f, vi); n->name = name; n->u.vi = vi;
          }
          return n;
        }
      } else { /* global declaration */
        if (vi->name == NULL) { if (wild < 0) wild = vi->attr == 1; }
        else if (vi->name == name) {
          Node *n = newnode(P, E_FIELD, line); n->flag = 1 | (vi->attr == 1 ? 2 : 0); n->name = name;
          n->a = env_node(P, line); n->b = NULL; return n;
        } else seen_gdecl = 1;
      }
    }
  }
  if (isenv) { /* the chunk's implicit _ENV upvalue */
    FuncState *root = fs; while (root->parent) root = root->parent;
    Node *n = newnode(P, E_UPVAL, line); n->slot = upval_for(fs, NULL, P->env_vi); n->name = name; n->u.vi = P->env_vi;
    return n;
  }
  Node *n = newnode(P, E_FIELD, line); n->name = name;
  if (wild < 0 && seen_gdecl) semerr(P, line, "variable '%s' not declared", name->data);
  n->flag = 1 | (wild == 1 ? 2 : 0);
  n->a = env_node(P, line);
  return n;
}

/* ---------- expressions ---------- */
static Node *expr(Parser *P);
static Node *subexpr(Parser *P, int limit);
static Block *block(Parser *P, BlockScope *bs, int isloop);
static Node *funcbody(Parser *P, int ismethod, int line, Str *name);

static int is_multi(Node *n) { return n->k == E_CALL || n->k == E_METH || n->k == E_VARARG; }

static Node *strnode(Parser *P, Str *s, int line) { Node *n = newnode(P, E_STR, line); n->u.s = s; return n; }

static Node *table_cons(Parser *P) {
  int line = P->t.line;
  Node *t = newnode(P, E_TABLE, line);
  NVec v = {0};
  expect(P, '{');
  while (P->t.t != '}') {
    Node *it;
    if (P->t.t == TK_NAME && lookahead(P) == '=') {
      int l = P->t.line; Str *nm = P->t.s; next(P); next(P);
      it = newnode(P, IT_KEY, l); it->a = strnode(P, nm, l); it->b = expr(P);
    } else if (P->t.t == '[') {
      int l = P->t.line; next(P);
      it = newnode(P, IT_KEY, l); it->a = expr(P); expect(P, ']'); expect(P, '='); it->b = expr(P);
    } else { it = newnode(P, IT_POS, P->t.line); it->a = expr(P); }
    nv_push(&v, it);
    if (!testnext(P, ',') && !testnext(P, ';')) break;
  }
  expect_match(P, '}', '{', line);
  t->n = v.n; t->list = nv_arena(P, &v);
  return t;
}

static Node *callargs(Parser *P, Node *f, Str *meth, int line) {
  NVec v = {0};
  switch (P->t.t) {
    case '(': {
      int l = P->t.line; next(P);
      if (P->t.t != ')') {
        nv_push(&v, expr(P));
        while (testnext(P, ',')) nv_push(&v, expr(P));
      }
      expect_match(P, ')', '(', l);
      break;
    }
    case '{': nv_push(&v, table_cons(P)); break;
    case TK_STRING: { Node *s = strnode(P, P->t.s, P->t.line); next(P); nv_push(&v, s); break; }
    default: synerr(P, "function arguments expected");
  }
  Node *c = newnode(P, meth ? E_METH : E_CALL, line);
  c->a = f; c->name = meth; c->n = v.n; c->list = nv_arena(P, &v);
  return c;
}

static Node *primaryexp(Parser *P) {
  switch (P->t.t) {
    case TK_NAME: { Str *s = P->t.s; int line = P->t.line; next(P); return var_node(P, s, line); }
    case '(': {
      int line = P->t.line; next(P);
      Node *e = expr(P);
      expect_match(P, ')', '(', line);
      if (is_multi(e) || e->k == E_CONCAT) {
        Node *pn = newnode(P, E_PAREN, line); pn->a = e; return pn;
      }
      return e;
    }
    default: synerr(P, "unexpected symbol");
  }
}
static Node *suffixedexp(Parser *P) {
  int line = P->t.line;
  Node *e = primaryexp(P);
  for (;;) {
    switch (P->t.t) {
      case '.': {
        int l = P->t.line; next(P);
        Str *nm = expect_name(P);
        Node *n = newnode(P, E_FIELD, l); n->a = e; n->name = nm; e = n; break;
      }
      case '[': {
        int l = P->t.line; next(P);
        Node *k = expr(P); expect(P, ']');
        if (k->k == E_STR) { Node *n = newnode(P, E_FIELD, l); n->a = e; n->name = k->u.s; e = n; }
        else { Node *n = newnode(P, E_INDEX, l); n->a = e; n->b = k; e = n; }
        break;
      }
      case ':': {
        next(P); Str *nm = expect_name(P);
        e = callargs(P, e, nm, line); break;
      }
      case '(': case TK_STRING: case '{':
        e = callargs(P, e, NULL, line); break;
      default: return e;
    }
  }
}
static Node *simpleexp(Parser *P) {
  int line = P->t.line; Node *n;
  switch (P->t.t) {
    case TK_FLT: n = newnode(P, E_FLT, line); n->u.n = P->t.n; next(P); return n;
    case TK_INT: n = newnode(P, E_INT, line); n->u.i = P->t.i; next(P); return n;
    case TK_STRING: n = strnode(P, P->t.s, line); next(P); return n;
    case TK_NIL: next(P); return newnode(P, E_NIL, line);
    case TK_TRUE: next(P); return newnode(P, E_TRUE, line);
    case TK_FALSE: next(P); return newnode(P, E_FALSE, line);
    case TK_DOTS:
      if (!P->fs->is_vararg) synerr(P, "cannot use '...' outside a vararg function");
      next(P); return newnode(P, E_VARARG, line);
    case '{': return table_cons(P);
    case TK_FUNCTION: next(P); return funcbody(P, 0, line, NULL);
    default: return suffixedexp(P);
  }
}

static const struct { uint8_t l, r; } prio[] = {
  [OP_ADD] = {10, 10}, [OP_SUB] = {10, 10}, [OP_MUL] = {11, 11}, [OP_MOD] = {11, 11}, [OP_POW] = {14, 13},
  [OP_DIV] = {11, 11}, [OP_IDIV] = {11, 11}, [OP_BAND] = {6, 6}, [OP_BOR] = {4, 4}, [OP_BXOR] = {5, 5},
  [OP_SHL] = {7, 7}, [OP_SHR] = {7, 7}, [OP_EQ] = {3, 3}, [OP_NE] = {3, 3}, [OP_LT] = {3, 3}, [OP_LE] = {3, 3},
  [OP_GT] = {3, 3}, [OP_GE] = {3, 3}
};
#define PRIO_CONCAT_L 9
#define PRIO_CONCAT_R 8
#define PRIO_AND 2
#define PRIO_OR 1
#define PRIO_UNARY 12
enum { BK_NONE, BK_BIN, BK_AND, BK_OR, BK_CONCAT };
static int getbinop(int t, int *op) {
  switch (t) {
    case '+': *op = OP_ADD; return BK_BIN; case '-': *op = OP_SUB; return BK_BIN;
    case '*': *op = OP_MUL; return BK_BIN; case '%': *op = OP_MOD; return BK_BIN;
    case '^': *op = OP_POW; return BK_BIN; case '/': *op = OP_DIV; return BK_BIN;
    case TK_IDIV: *op = OP_IDIV; return BK_BIN; case '&': *op = OP_BAND; return BK_BIN;
    case '|': *op = OP_BOR; return BK_BIN; case '~': *op = OP_BXOR; return BK_BIN;
    case TK_SHL: *op = OP_SHL; return BK_BIN; case TK_SHR: *op = OP_SHR; return BK_BIN;
    case TK_EQ: *op = OP_EQ; return BK_BIN; case TK_NE: *op = OP_NE; return BK_BIN;
    case '<': *op = OP_LT; return BK_BIN; case TK_LE: *op = OP_LE; return BK_BIN;
    case '>': *op = OP_GT; return BK_BIN; case TK_GE: *op = OP_GE; return BK_BIN;
    case TK_AND: return BK_AND; case TK_OR: return BK_OR; case TK_CONCAT: return BK_CONCAT;
    default: return BK_NONE;
  }
}

static Node *subexpr(Parser *P, int limit) {
  enterlevel(P);
  Node *e;
  int line = P->t.line;
  int ut = P->t.t;
  if (ut == TK_NOT || ut == '-' || ut == '#' || ut == '~') {
    next(P);
    Node *o = subexpr(P, PRIO_UNARY);
    if (ut == '-' && o->k == E_INT) { o->u.i = (lint)((luint)0 - (luint)o->u.i); e = o; }
    else if (ut == '-' && o->k == E_FLT) { o->u.n = -o->u.n; e = o; }
    else { e = newnode(P, ut == TK_NOT ? E_NOT : ut == '-' ? E_NEG : ut == '#' ? E_LEN : E_BNOT, line); e->a = o; }
  } else e = simpleexp(P);
  for (;;) {
    int op = 0, bk = getbinop(P->t.t, &op);
    if (bk == BK_NONE) break;
    int lp, rp;
    if (bk == BK_BIN) { lp = prio[op].l; rp = prio[op].r; }
    else if (bk == BK_AND) { lp = rp = PRIO_AND; }
    else if (bk == BK_OR) { lp = rp = PRIO_OR; }
    else { lp = PRIO_CONCAT_L; rp = PRIO_CONCAT_R; }
    if (lp <= limit) break;
    int opline = P->t.line;
    next(P);
    Node *n;
    if (bk == BK_CONCAT) { /* iterative: a .. b .. c  =>  one node with an operand list (right associative) */
      NVec cv = {0}; nv_push(&cv, e);
      nv_push(&cv, subexpr(P, PRIO_CONCAT_L));
      while (P->t.t == TK_CONCAT) { next(P); nv_push(&cv, subexpr(P, PRIO_CONCAT_L)); }
      n = newnode(P, E_CONCAT, opline); n->n = cv.n; n->list = nv_arena(P, &cv);
    } else {
      Node *r = subexpr(P, rp);
      if (bk == BK_BIN) { n = newnode(P, E_BIN, opline); n->op = (uint8_t)op; n->a = e; n->b = r; }
      else if (bk == BK_AND) { n = newnode(P, E_AND, opline); n->a = e; n->b = r; }
      else { n = newnode(P, E_OR, opline); n->a = e; n->b = r; }
    }
    e = n;
  }
  leavelevel(P);
  return e;
}
static Node *expr(Parser *P) { return subexpr(P, 0); }

/* ---------- functions ---------- */
static void open_func(Parser *P, FuncState *fs, int line) {
  memset(fs, 0, sizeof *fs);
  fs->parent = P->fs; P->fs = fs;
  Proto *p = arena_alloc(P->ck, sizeof(Proto));
  p->chunk = P->ck; p->line = line; p->nslots = 1;
  fs->p = p;
}
static void close_func(Parser *P, FuncState *fs, int line) {
  Proto *p = fs->p;
  for (int i = 0; i < fs->nrefs; i++) { Node *n = fs->refs[i]; n->k = n->u.vi->captured ? E_BOXED : E_LOCAL; }
  p->nup = fs->nup; p->lastline = line;
  p->up = arena_alloc(P->ck, (size_t)(fs->nup ? fs->nup : 1) * sizeof(UpDesc));
  if (fs->nup) memcpy(p->up, fs->ups, (size_t)fs->nup * sizeof(UpDesc));
  p->is_vararg = fs->is_vararg;
  free(fs->act); free(fs->upvi); free(fs->ups); free(fs->refs);
  P->fs = fs->parent;
}
static void statlist(Parser *P);

static Node *funcbody(Parser *P, int ismethod, int line, Str *name) {
  FuncState fs; open_func(P, &fs, line);
  fs.p->name = name;
  BlockScope bs; enter_block(P, &bs, 0);
  VarInfo *params[256]; int np = 0;
  if (ismethod) { params[np++] = new_local(P, pstr(P, "self", 4), 0); activate(&fs, params[np - 1]); }
  expect(P, '(');
  if (P->t.t != ')') {
    do {
      if (P->t.t == TK_NAME) {
        if (np >= 200) synerr(P, "too many parameters");
        params[np++] = new_local(P, P->t.s, 0); activate(&fs, params[np - 1]); next(P);
      } else if (P->t.t == TK_DOTS) { next(P); fs.is_vararg = 1; break; }
      else synerr(P, "<name> expected");
    } while (testnext(P, ','));
  }
  expect(P, ')');
  fs.p->nparams = np;
  fs.p->params = arena_alloc(P->ck, (size_t)(np ? np : 1) * sizeof(VarInfo *));
  for (int i = 0; i < np; i++) fs.p->params[i] = params[i];
  statlist(P);
  int endline = P->t.line;
  expect_match(P, TK_END, TK_FUNCTION, line);
  fs.p->body = leave_block(P, &bs);
  close_func(P, &fs, endline);
  Node *n = newnode(P, E_FUNC, line); n->u.p = fs.p;
  return n;
}

/* ---------- statements ---------- */
static int block_follow(Parser *P, int withuntil) {
  switch (P->t.t) {
    case TK_ELSE: case TK_ELSEIF: case TK_END: case TK_EOS: return 1;
    case TK_UNTIL: return withuntil;
    default: return 0;
  }
}
static Node *exprlist(Parser *P, Node ***out, int *n) {
  NVec v = {0};
  nv_push(&v, expr(P));
  while (testnext(P, ',')) nv_push(&v, expr(P));
  *n = v.n; *out = nv_arena(P, &v);
  return NULL;
}
static int fs_inclose(FuncState *fs) {
  for (BlockScope *b = fs->bs; b; b = b->prev) if (b->hasclose || b->notail) return 1;
  return 0;
}
static void add_goto_pending(BlockScope *bs, Node *g, Str *name, int line, int nact) {
  if (bs->npend == bs->cappend) { bs->cappend = bs->cappend ? bs->cappend * 2 : 4; bs->pend = realloc(bs->pend, (size_t)bs->cappend * sizeof(PendGoto)); }
  bs->pend[bs->npend].g = g; bs->pend[bs->npend].name = name; bs->pend[bs->npend].line = line; bs->pend[bs->npend].nact = nact;
  bs->npend++;
}
static Label *find_label(FuncState *fs, Str *name) {
  for (BlockScope *b = fs->bs; b; b = b->prev)
    for (int i = 0; i < b->nlabels; i++) if (b->labels[i]->name == name) return b->labels[i];
  return NULL;
}
static int parse_attrib(Parser *P) {
  if (testnext(P, '<')) {
    Str *a = expect_name(P); int r;
    if (!strcmp(a->data, "const")) r = 1;
    else if (!strcmp(a->data, "close")) r = 2;
    else semerr(P, P->t.line, "unknown attribute '%s'", a->data);
    expect(P, '>');
    return r;
  }
  return 0;
}
static void check_assignable(Parser *P, Node *t) {
  if (t->k == E_LOCAL || t->k == E_BOXED || t->k == E_UPVAL) {
    if (t->u.vi->attr && t->u.vi != P->env_vi) semerr(P, P->t.line, "attempt to assign to const variable '%s'", t->name->data);
  } else if (t->k == E_FIELD && (t->flag & 2)) semerr(P, P->t.line, "attempt to assign to const variable '%s'", t->name->data);
  else if (t->k != E_FIELD && t->k != E_INDEX) synerr(P, "syntax error");
}

static Node *localstat(Parser *P, int line) {
  VarInfo *vars[200]; int nv = 0; int closeidx = -1;
  int pre = parse_attrib(P);
  do {
    Str *nm = expect_name(P);
    int at = parse_attrib(P); if (!at) at = pre;
    if (at == 2) { if (closeidx >= 0) semerr(P, line, "multiple to-be-closed variables in local list"); closeidx = nv; }
    if (nv >= 190) synerr(P, "too many local variables");
    vars[nv++] = new_local(P, nm, at);
  } while (testnext(P, ','));
  /* new_local already took slots, but variables only become visible after the initialisers */
  Node *s = newnode(P, S_LOCAL, line);
  if (testnext(P, '=')) {
    FuncState *fs = P->fs;
    int saved = fs->nact; (void)saved;
    exprlist(P, &s->list, &s->n);
  }
  s->u.vars = arena_alloc(P->ck, (size_t)nv * sizeof(VarInfo *));
  memcpy(s->u.vars, vars, (size_t)nv * sizeof(VarInfo *));
  s->slot = nv;
  for (int i = 0; i < nv; i++) activate(P->fs, vars[i]);
  if (closeidx >= 0) { P->fs->bs->hasclose = 1; s->flag = 1; P->fs->p->hasclose = 1; }
  return s;
}

static Node *globalstat(Parser *P, int line) {
  int pre = parse_attrib(P);
  if (P->t.t == '*') { /* global [attrib] * */
    next(P);
    VarInfo *vi = arena_alloc(P->ck, sizeof(VarInfo));
    vi->name = NULL; vi->slot = -1; vi->attr = (uint8_t)(pre == 1 ? 1 : 0);
    if (pre == 2) semerr(P, line, "global variables cannot be to-be-closed");
    activate(P->fs, vi);
    return NULL;
  }
  VarInfo *vars[200]; int nv = 0;
  do {
    Str *nm = expect_name(P);
    int at = parse_attrib(P); if (!at) at = pre;
    if (at == 2) semerr(P, line, "global variables cannot be to-be-closed");
    VarInfo *vi = arena_alloc(P->ck, sizeof(VarInfo));
    vi->name = nm; vi->slot = -1; vi->attr = (uint8_t)at;
    vars[nv++] = vi;
  } while (testnext(P, ','));
  Node *s = newnode(P, S_GLOBAL, line);
  s->u.vars = arena_alloc(P->ck, (size_t)nv * sizeof(VarInfo *));
  memcpy(s->u.vars, vars, (size_t)nv * sizeof(VarInfo *));
  s->slot = nv;
  if (testnext(P, '=')) {
    exprlist(P, &s->list, &s->n);
    /* initialisation: targets are the (not yet visible) declared names */
  }
  for (int i = 0; i < nv; i++) activate(P->fs, vars[i]);
  /* build target nodes now that the declarations are active */
  s->list2 = arena_alloc(P->ck, (size_t)nv * sizeof(Node *)); s->n2 = nv;
  for (int i = 0; i < nv; i++) {
    Node *t = newnode(P, E_FIELD, line); t->flag = 1; t->name = vars[i]->name; t->a = env_node(P, line);
    s->list2[i] = t;
  }
  return s;
}

static Node *exprstat(Parser *P) {
  int line = P->t.line;
  Node *e = suffixedexp(P);
  if (P->t.t == '=' || P->t.t == ',') {
    NVec tg = {0}; nv_push(&tg, e); check_assignable(P, e);
    while (testnext(P, ',')) { Node *t = suffixedexp(P); check_assignable(P, t); nv_push(&tg, t); }
    expect(P, '=');
    Node *s = newnode(P, S_ASSIGN, line);
    s->n = tg.n; s->list = nv_arena(P, &tg);
    exprlist(P, &s->list2, &s->n2);
    return s;
  }
  if (e->k != E_CALL && e->k != E_METH) synerr(P, "syntax error");
  Node *s = newnode(P, S_CALL, line); s->a = e; return s;
}

static Block *block(Parser *P, BlockScope *bs, int isloop) {
  enter_block(P, bs, isloop);
  statlist(P);
  return leave_block(P, bs);
}

static Node *statement(Parser *P);

static void statlist(Parser *P) {
  while (!block_follow(P, 1)) {
    if (P->t.t == TK_RETURN) {
      int line = P->t.line; next(P);
      Node *s = newnode(P, S_RETURN, line);
      if (!block_follow(P, 1) && P->t.t != ';') exprlist(P, &s->list, &s->n);
      testnext(P, ';');
      if (s->n == 1 && (s->list[0]->k == E_CALL || s->list[0]->k == E_METH) && !fs_inclose(P->fs)) s->flag = 1;
      add_stmt(P->fs->bs, s, 0);
      return;
    }
    Node *s = statement(P);
    if (s) add_stmt(P->fs->bs, s, s->k == S_LABEL);
  }
}

static Node *statement(Parser *P) {
  int line = P->t.line;
  enterlevel(P);
  Node *s = NULL;
  switch (P->t.t) {
    case ';': next(P); break;
    case TK_IF: {
      Node *top = NULL, **tail = &top;
      for (;;) {
        int l = P->t.line; next(P);
        Node *n = newnode(P, S_IF, l);
        n->a = expr(P); expect(P, TK_THEN);
        BlockScope bs; n->blk = block(P, &bs, 0);
        *tail = n; tail = &n->b;
        if (P->t.t == TK_ELSEIF) continue;
        if (P->t.t == TK_ELSE) {
          next(P);
          Node *d = newnode(P, S_DO, P->t.line); BlockScope b2; d->blk = block(P, &b2, 0);
          n->b = d;
        }
        break;
      }
      expect_match(P, TK_END, TK_IF, line);
      s = top; break;
    }
    case TK_WHILE: {
      next(P);
      s = newnode(P, S_WHILE, line); s->a = expr(P); expect(P, TK_DO);
      BlockScope bs; s->blk = block(P, &bs, 1);
      expect_match(P, TK_END, TK_WHILE, line); break;
    }
    case TK_DO: {
      next(P); s = newnode(P, S_DO, line);
      BlockScope bs; s->blk = block(P, &bs, 0);
      expect_match(P, TK_END, TK_DO, line); break;
    }
    case TK_FOR: {
      next(P);
      Str *n1 = expect_name(P);
      BlockScope outer; enter_block(P, &outer, 0);
      if (P->t.t == '=') {
        next(P);
        s = newnode(P, S_FORNUM, line);
        s->a = expr(P); expect(P, ','); s->b = expr(P);
        if (testnext(P, ',')) s->c = expr(P);
        expect(P, TK_DO);
        VarInfo *vi = new_local(P, n1, 3); activate(P->fs, vi); s->u.vi = vi;
        BlockScope bs; s->blk = block(P, &bs, 1);
      } else if (P->t.t == ',' || P->t.t == TK_IN) {
        VarInfo *vars[64]; int nv = 0;
        vars[nv++] = new_local(P, n1, 3);
        while (testnext(P, ',')) { if (nv >= 60) synerr(P, "too many variables"); vars[nv++] = new_local(P, expect_name(P), 0); }
        expect(P, TK_IN);
        s = newnode(P, S_FORIN, line);
        exprlist(P, &s->list, &s->n);
        expect(P, TK_DO);
        for (int i = 0; i < nv; i++) activate(P->fs, vars[i]);
        s->u.vars = arena_alloc(P->ck, (size_t)nv * sizeof(VarInfo *));
        memcpy(s->u.vars, vars, (size_t)nv * sizeof(VarInfo *)); s->slot = nv;
        BlockScope bs; enter_block(P, &bs, 1); bs.notail = 1; statlist(P); s->blk = leave_block(P, &bs);
      } else synerr(P, "'=' or 'in' expected");
      expect_match(P, TK_END, TK_FOR, line);
      leave_block(P, &outer);
      break;
    }
    case TK_REPEAT: {
      next(P);
      s = newnode(P, S_REPEAT, line);
      BlockScope bs; enter_block(P, &bs, 1); bs.isrepeat = 1;
      statlist(P);
      expect_match(P, TK_UNTIL, TK_REPEAT, line);
      s->a = expr(P);
      s->blk = leave_block(P, &bs);
      break;
    }
    case TK_FUNCTION: {
      next(P);
      Str *n1 = expect_name(P);
      Node *target = var_node(P, n1, line); int ismethod = 0;
      Str *fname = n1;
      while (P->t.t == '.' || P->t.t == ':') {
        int colon = P->t.t == ':'; next(P);
        Str *k = expect_name(P);
        Node *f = newnode(P, E_FIELD, P->t.line); f->a = target; f->name = k; target = f; fname = k;
        if (colon) { ismethod = 1; break; }
      }
      check_assignable(P, target);
      s = newnode(P, S_ASSIGN, line);
      s->n = 1; s->list = arena_alloc(P->ck, sizeof(Node *)); s->list[0] = target;
      s->n2 = 1; s->list2 = arena_alloc(P->ck, sizeof(Node *));
      s->list2[0] = funcbody(P, ismethod, line, fname);
      break;
    }
    case TK_LOCAL:
      next(P);
      if (testnext(P, TK_FUNCTION)) {
        Str *nm = expect_name(P);
        VarInfo *vi = new_local(P, nm, 0); activate(P->fs, vi);
        s = newnode(P, S_LOCALFUNC, line); s->u.vi = vi;
        s->a = funcbody(P, 0, line, nm);
      } else s = localstat(P, line);
      break;
    case TK_GLOBAL:
      if (lookahead(P) == TK_FUNCTION) {
        next(P); next(P);
        Str *nm = expect_name(P);
        VarInfo *vi = arena_alloc(P->ck, sizeof(VarInfo)); vi->name = nm; vi->slot = -1;
        activate(P->fs, vi);
        s = newnode(P, S_GLOBALFUNC, line);
        Node *t = newnode(P, E_FIELD, line); t->flag = 1; t->name = nm; t->a = env_node(P, line);
        s->a = t; s->name = nm;
        s->b = funcbody(P, 0, line, nm);
      } else if (lookahead(P) == TK_NAME || lookahead(P) == '<' || lookahead(P) == '*') {
        next(P); s = globalstat(P, line);
      } else s = exprstat(P);
      break;
    case TK_DBCOLON: {
      next(P);
      Str *nm = expect_name(P);
      expect(P, TK_DBCOLON);
      Label *ex = find_label(P->fs, nm);
      if (ex) semerr(P, line, "label '%s' already defined on line %d", nm->data, ex->line);
      Label *l = arena_alloc(P->ck, sizeof(Label));
      BlockScope *bs = P->fs->bs;
      l->name = nm; l->line = line; l->idx = bs->nstmts; l->nactive = P->fs->nslotsact;
      if (bs->nlabels == bs->caplabels) { bs->caplabels = bs->caplabels ? bs->caplabels * 2 : 4; bs->labels = realloc(bs->labels, (size_t)bs->caplabels * sizeof(Label *)); }
      bs->labels[bs->nlabels++] = l;
      s = newnode(P, S_LABEL, line); s->u.lbl = l;
      break;
    }
    case TK_RETURN: synerr(P, "unexpected return");
    case TK_BREAK: {
      next(P);
      int inloop = 0; for (BlockScope *b = P->fs->bs; b; b = b->prev) if (b->isloop) { inloop = 1; break; }
      if (!inloop) semerr(P, line, "break outside a loop at line %d", line);
      s = newnode(P, S_BREAK, line); break;
    }
    case TK_GOTO: {
      next(P);
      Str *nm = expect_name(P);
      s = newnode(P, S_GOTO, line);
      Label *l = find_label(P->fs, nm);
      if (l) s->u.lbl = l;
      else add_goto_pending(P->fs->bs, s, nm, line, P->fs->nslotsact);
      break;
    }
    default: s = exprstat(P); break;
  }
  leavelevel(P);
  return s;
}

/* ---------- entry points ---------- */
void chunkid(char *out, size_t outsz, const char *source, size_t srclen) {
  if (source[0] == '=') {
    size_t n = srclen - 1; if (n > outsz - 1) n = outsz - 1;
    memcpy(out, source + 1, n); out[n] = 0;
  } else if (source[0] == '@') {
    size_t n = srclen - 1;
    if (n <= outsz - 1) { memcpy(out, source + 1, n); out[n] = 0; }
    else { size_t keep = outsz - 1 - 3; memcpy(out, "...", 3); memcpy(out + 3, source + 1 + n - keep, keep); out[outsz - 1] = 0; }
  } else {
    const char *nl = memchr(source, '\n', srclen);
    size_t avail = outsz - 15; /* [string "..."] + nul */
    size_t l = nl ? (size_t)(nl - source) : srclen;
    if (!nl && l <= avail) snprintf(out, outsz, "[string \"%.*s\"]", (int)l, source);
    else { if (l > avail) l = avail; snprintf(out, outsz, "[string \"%.*s...\"]", (int)l, source); }
  }
}

Proto *parse_chunk(State *L, const char *src, size_t len, const char *chunkname, Value *errmsg) {
  Parser P; memset(&P, 0, sizeof P);
  P.L = L; P.src = src; P.p = src; P.end = src + len; P.line = 1;
  P.ck = chunk_new();
  chunkid(P.ck->short_src, sizeof P.ck->short_src, chunkname, strlen(chunkname));
  P.ck->source = pstr(&P, chunkname, strlen(chunkname));
  if (setjmp(P.jb)) {
    *errmsg = mkstr(str_newz(P.errbuf));
    free(P.buf);
    return NULL;
  }
  if (P.p < P.end && *P.p == '#') while (P.p < P.end && *P.p != '\n') P.p++;
  FuncState fs; open_func(&P, &fs, 0);
  fs.is_vararg = 1;
  P.env_vi = arena_alloc(P.ck, sizeof(VarInfo)); P.env_vi->name = pstr(&P, "_ENV", 4); P.env_vi->slot = 0; P.env_vi->attr = 0;
  fs.nup = 1; fs.capup = 4;
  fs.upvi = malloc(4 * sizeof(VarInfo *)); fs.ups = malloc(4 * sizeof(UpDesc));
  fs.upvi[0] = P.env_vi; memset(&fs.ups[0], 0, sizeof(UpDesc)); fs.ups[0].name = P.env_vi->name;
  BlockScope bs; enter_block(&P, &bs, 0);
  next(&P);
  statlist(&P);
  check(&P, TK_EOS);
  fs.p->body = leave_block(&P, &bs);
  close_func(&P, &fs, P.line);
  free(P.buf);
  return fs.p;
}
