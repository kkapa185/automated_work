#include "chess.h"

#include <cctype>
#include <cstring>
#include <sstream>

U64 knightAtt[64], kingAtt[64], pawnAtt[2][64], rayBB[8][64];
U64 zPiece[12][64], zCastle[16], zEp[8], zSide;
int castleMask[64];

static const int DF[8] = {0, 1, 0, -1, 1, -1, 1, -1};
static const int DR[8] = {1, 0, -1, 0, 1, 1, -1, -1};
// directions: 0 N, 1 E, 2 S, 3 W, 4 NE, 5 NW, 6 SE, 7 SW

static U64 rngState = 0x9E3779B97F4A7C15ULL;
static U64 rnd() {  // splitmix64
    U64 z = (rngState += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

void initTables() {
    static bool done = false;
    if (done) return;
    done = true;
    for (int s = 0; s < 64; s++) {
        int f = s & 7, r = s >> 3;
        for (int d = 0; d < 8; d++) {
            U64 b = 0;
            int ff = f + DF[d], rr = r + DR[d];
            while (ff >= 0 && ff < 8 && rr >= 0 && rr < 8) {
                b |= bit(rr * 8 + ff);
                ff += DF[d];
                rr += DR[d];
            }
            rayBB[d][s] = b;
        }
        static const int kn[8][2] = {{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}};
        knightAtt[s] = kingAtt[s] = pawnAtt[0][s] = pawnAtt[1][s] = 0;
        for (auto& k : kn) {
            int ff = f + k[0], rr = r + k[1];
            if (ff >= 0 && ff < 8 && rr >= 0 && rr < 8) knightAtt[s] |= bit(rr * 8 + ff);
        }
        for (int df = -1; df <= 1; df++)
            for (int dr = -1; dr <= 1; dr++) {
                if (!df && !dr) continue;
                int ff = f + df, rr = r + dr;
                if (ff >= 0 && ff < 8 && rr >= 0 && rr < 8) kingAtt[s] |= bit(rr * 8 + ff);
            }
        for (int df = -1; df <= 1; df += 2) {
            if (f + df < 0 || f + df > 7) continue;
            if (r < 7) pawnAtt[WHITE][s] |= bit((r + 1) * 8 + f + df);
            if (r > 0) pawnAtt[BLACK][s] |= bit((r - 1) * 8 + f + df);
        }
    }
    for (int p = 0; p < 12; p++)
        for (int s = 0; s < 64; s++) zPiece[p][s] = rnd();
    for (int i = 0; i < 16; i++) zCastle[i] = rnd();
    for (int i = 0; i < 8; i++) zEp[i] = rnd();
    zSide = rnd();
    for (int s = 0; s < 64; s++) castleMask[s] = 15;
    castleMask[0] = ~WQ_RIGHT & 15;
    castleMask[7] = ~WK_RIGHT & 15;
    castleMask[4] = ~(WK_RIGHT | WQ_RIGHT) & 15;
    castleMask[56] = ~BQ_RIGHT & 15;
    castleMask[63] = ~BK_RIGHT & 15;
    castleMask[60] = ~(BK_RIGHT | BQ_RIGHT) & 15;
}

namespace {
struct Init {
    Init() { initTables(); }
} initOnce;
}  // namespace

static inline U64 rayAtt(int d, int sq, U64 occ) {
    U64 a = rayBB[d][sq];
    U64 b = a & occ;
    if (b) {
        int s = (d == 0 || d == 1 || d == 4 || d == 5) ? lsb(b) : msb(b);
        a ^= rayBB[d][s];
    }
    return a;
}
U64 rookAttacks(int sq, U64 occ) { return rayAtt(0, sq, occ) | rayAtt(1, sq, occ) | rayAtt(2, sq, occ) | rayAtt(3, sq, occ); }
U64 bishopAttacks(int sq, U64 occ) { return rayAtt(4, sq, occ) | rayAtt(5, sq, occ) | rayAtt(6, sq, occ) | rayAtt(7, sq, occ); }

std::string squareToString(int sq) {
    std::string s;
    s += (char)('a' + (sq & 7));
    s += (char)('1' + (sq >> 3));
    return s;
}
std::string moveToString(Move m) {
    if (!m) return "0000";
    std::string s = squareToString(moveFrom(m)) + squareToString(moveTo(m));
    if (movePromo(m)) s += "nbrq"[movePromo(m) - 1];
    return s;
}

Position::Position() {
    std::memset(pieces, 0, sizeof pieces);
    occ[0] = occ[1] = all = 0;
    for (int i = 0; i < 64; i++) board[i] = NO_PIECE;
    side = WHITE;
    castling = 0;
    ep = -1;
    halfmove = 0;
    fullmove = 1;
    key = 0;
}

void Position::setStartpos() { setFen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"); }

void Position::put(int pc, int sq) {
    pieces[pc] |= bit(sq);
    occ[pc / 6] |= bit(sq);
    all |= bit(sq);
    board[sq] = pc;
    key ^= zPiece[pc][sq];
}
void Position::remove(int pc, int sq) {
    pieces[pc] &= ~bit(sq);
    occ[pc / 6] &= ~bit(sq);
    all &= ~bit(sq);
    board[sq] = NO_PIECE;
    key ^= zPiece[pc][sq];
}

bool Position::epHashed() const { return ep != -1 && (pawnAtt[side ^ 1][ep] & pieces[side * 6 + PAWN]); }

U64 Position::computeKey() const {
    U64 k = 0;
    for (int s = 0; s < 64; s++)
        if (board[s] != NO_PIECE) k ^= zPiece[board[s]][s];
    k ^= zCastle[castling];
    if (side == BLACK) k ^= zSide;
    if (epHashed()) k ^= zEp[ep & 7];
    return k;
}

bool Position::setFen(const std::string& fenStr) {
    Position np;  // parse into a scratch copy so that a bad FEN leaves *this untouched
    std::memset(np.pieces, 0, sizeof np.pieces);
    np.occ[0] = np.occ[1] = np.all = 0;
    for (int i = 0; i < 64; i++) np.board[i] = NO_PIECE;
    np.key = 0;
    np.hist.clear();
    std::istringstream in(fenStr);
    std::string bd, stm, cas = "-", eps = "-";
    int hm = 0, fm = 1;
    if (!(in >> bd >> stm)) return false;
    in >> cas >> eps;
    if (in) {
        std::string a, b;
        if (in >> a) {
            for (char c : a) if (!isdigit((unsigned char)c)) return false;
            if (a.size() > 6) return false;
            hm = atoi(a.c_str());
            if (in >> b) {
                for (char c : b) if (!isdigit((unsigned char)c)) return false;
                if (b.size() > 6) return false;
                fm = atoi(b.c_str());
            }
        }
    }
    int r = 7, f = 0;
    for (char c : bd) {
        if (c == '/') {
            if (f != 8 || r == 0) return false;
            r--;
            f = 0;
        } else if (c >= '1' && c <= '8') {
            f += c - '0';
            if (f > 8) return false;
        } else {
            const char* p = std::strchr("PNBRQKpnbrqk", c);
            if (!p || !c || f >= 8) return false;
            int idx = (int)(p - "PNBRQKpnbrqk");
            int pc = idx < 6 ? idx : 6 + (idx - 6);
            int sq = r * 8 + f;
            np.pieces[pc] |= bit(sq);
            np.occ[pc / 6] |= bit(sq);
            np.all |= bit(sq);
            np.board[sq] = pc;
            f++;
        }
    }
    if (r != 0 || f != 8) return false;
    if (stm == "w") np.side = WHITE;
    else if (stm == "b") np.side = BLACK;
    else return false;
    np.castling = 0;
    if (cas != "-") {
        for (char c : cas) {
            if (c == 'K') np.castling |= WK_RIGHT;
            else if (c == 'Q') np.castling |= WQ_RIGHT;
            else if (c == 'k') np.castling |= BK_RIGHT;
            else if (c == 'q') np.castling |= BQ_RIGHT;
            else return false;
        }
    }
    // Drop castling rights that are impossible given the piece placement.
    if (np.board[4] != 5) np.castling &= ~(WK_RIGHT | WQ_RIGHT);
    if (np.board[7] != 3) np.castling &= ~WK_RIGHT;
    if (np.board[0] != 3) np.castling &= ~WQ_RIGHT;
    if (np.board[60] != 11) np.castling &= ~(BK_RIGHT | BQ_RIGHT);
    if (np.board[63] != 9) np.castling &= ~BK_RIGHT;
    if (np.board[56] != 9) np.castling &= ~BQ_RIGHT;
    np.ep = -1;
    if (eps != "-") {
        if (eps.size() != 2 || eps[0] < 'a' || eps[0] > 'h') return false;
        if (eps[1] != (np.side == WHITE ? '6' : '3')) return false;
        np.ep = (eps[1] - '1') * 8 + (eps[0] - 'a');
    }
    np.halfmove = hm;
    np.fullmove = fm < 1 ? 1 : fm;
    if (popcount(np.pieces[5]) != 1 || popcount(np.pieces[11]) != 1) return false;
    if (np.pieces[0] & 0xFF000000000000FFULL) return false;
    if (np.pieces[6] & 0xFF000000000000FFULL) return false;
    if (np.attacked(np.kingSq(np.side ^ 1), np.side)) return false;  // side not to move in check
    np.key = np.computeKey();
    *this = np;
    return true;
}

std::string Position::fen() const {
    std::string s;
    for (int r = 7; r >= 0; r--) {
        int empty = 0;
        for (int f = 0; f < 8; f++) {
            int pc = board[r * 8 + f];
            if (pc == NO_PIECE) {
                empty++;
                continue;
            }
            if (empty) s += (char)('0' + empty);
            empty = 0;
            s += "PNBRQKpnbrqk"[pc];
        }
        if (empty) s += (char)('0' + empty);
        if (r) s += '/';
    }
    s += side == WHITE ? " w " : " b ";
    if (!castling) s += '-';
    else {
        if (castling & WK_RIGHT) s += 'K';
        if (castling & WQ_RIGHT) s += 'Q';
        if (castling & BK_RIGHT) s += 'k';
        if (castling & BQ_RIGHT) s += 'q';
    }
    s += ' ';
    s += ep == -1 ? "-" : squareToString(ep);
    s += ' ' + std::to_string(halfmove) + ' ' + std::to_string(fullmove);
    return s;
}

std::string Position::pretty() const {
    std::string s = " +---+---+---+---+---+---+---+---+\n";
    for (int r = 7; r >= 0; r--) {
        for (int f = 0; f < 8; f++) {
            int pc = board[r * 8 + f];
            s += std::string(" | ") + (pc == NO_PIECE ? ' ' : "PNBRQKpnbrqk"[pc]);
        }
        s += " | " + std::to_string(r + 1) + "\n +---+---+---+---+---+---+---+---+\n";
    }
    s += "   a   b   c   d   e   f   g   h\n";
    return s;
}

U64 Position::attackersTo(int sq, int by) const {
    U64 a = pawnAtt[by ^ 1][sq] & pieces[by * 6 + PAWN];
    a |= knightAtt[sq] & pieces[by * 6 + KNIGHT];
    a |= kingAtt[sq] & pieces[by * 6 + KING];
    a |= bishopAttacks(sq, all) & (pieces[by * 6 + BISHOP] | pieces[by * 6 + QUEEN]);
    a |= rookAttacks(sq, all) & (pieces[by * 6 + ROOK] | pieces[by * 6 + QUEEN]);
    return a;
}

bool Position::attacked(int sq, int by) const {
    if (pawnAtt[by ^ 1][sq] & pieces[by * 6 + PAWN]) return true;
    if (knightAtt[sq] & pieces[by * 6 + KNIGHT]) return true;
    if (kingAtt[sq] & pieces[by * 6 + KING]) return true;
    if (bishopAttacks(sq, all) & (pieces[by * 6 + BISHOP] | pieces[by * 6 + QUEEN])) return true;
    if (rookAttacks(sq, all) & (pieces[by * 6 + ROOK] | pieces[by * 6 + QUEEN])) return true;
    return false;
}

void Position::make(Move m) {
    State st{key, castling, ep, halfmove, NO_PIECE, m};
    int f = moveFrom(m), t = moveTo(m), us = side;
    int pc = board[f], type = pc % 6;
    int cap = board[t];
    if (epHashed()) key ^= zEp[ep & 7];
    key ^= zCastle[castling];
    halfmove++;
    if (type == PAWN && ep != -1 && t == ep && cap == NO_PIECE) {
        int csq = t + (us == WHITE ? -8 : 8);
        cap = board[csq];
        remove(cap, csq);
        halfmove = 0;
    } else if (cap != NO_PIECE) {
        remove(cap, t);
        halfmove = 0;
    }
    st.captured = cap;
    remove(pc, f);
    if (type == PAWN) {
        halfmove = 0;
        put(movePromo(m) ? us * 6 + movePromo(m) : pc, t);
    } else {
        put(pc, t);
        if (type == KING && (t - f == 2 || f - t == 2)) {
            if (t > f) {
                int rk = board[t + 1];
                remove(rk, t + 1);
                put(rk, t - 1);
            } else {
                int rk = board[t - 2];
                remove(rk, t - 2);
                put(rk, t + 1);
            }
        }
    }
    ep = (type == PAWN && (t - f == 16 || f - t == 16)) ? (f + t) / 2 : -1;
    castling &= castleMask[f] & castleMask[t];
    key ^= zCastle[castling];
    side ^= 1;
    key ^= zSide;
    if (epHashed()) key ^= zEp[ep & 7];
    if (us == BLACK) fullmove++;
    hist.push_back(st);
}

void Position::unmake() {
    State st = hist.back();
    hist.pop_back();
    Move m = st.move;
    side ^= 1;
    int us = side;
    if (us == BLACK) fullmove--;
    int f = moveFrom(m), t = moveTo(m);
    int pc = board[t];
    int type = pc % 6;
    if (movePromo(m)) {
        remove(pc, t);
        put(us * 6 + PAWN, f);
    } else {
        remove(pc, t);
        put(pc, f);
    }
    if (type == KING && (t - f == 2 || f - t == 2) && !movePromo(m)) {
        if (t > f) {
            int rk = board[t - 1];
            remove(rk, t - 1);
            put(rk, t + 1);
        } else {
            int rk = board[t + 1];
            remove(rk, t + 1);
            put(rk, t - 2);
        }
    }
    if (st.captured != NO_PIECE) {
        int csq = t;
        if (pc % 6 == PAWN && !movePromo(m) && st.ep == t) csq = t + (us == WHITE ? -8 : 8);
        put(st.captured, csq);
    }
    castling = st.castling;
    ep = st.ep;
    halfmove = st.halfmove;
    key = st.key;
}

void Position::makeNull() {
    State st{key, castling, ep, halfmove, NO_PIECE, 0};
    if (epHashed()) key ^= zEp[ep & 7];
    ep = -1;
    side ^= 1;
    key ^= zSide;
    halfmove++;
    hist.push_back(st);
}
void Position::unmakeNull() {
    State st = hist.back();
    hist.pop_back();
    side ^= 1;
    castling = st.castling;
    ep = st.ep;
    halfmove = st.halfmove;
    key = st.key;
}

bool Position::isCapture(Move m) const {
    int t = moveTo(m);
    if (board[t] != NO_PIECE) return true;
    return board[moveFrom(m)] % 6 == PAWN && t == ep;
}

bool Position::hasNonPawnMaterial(int c) const {
    return (pieces[c * 6 + KNIGHT] | pieces[c * 6 + BISHOP] | pieces[c * 6 + ROOK] | pieces[c * 6 + QUEEN]) != 0;
}

bool Position::insufficientMaterial() const {
    if (pieces[PAWN] | pieces[6 + PAWN] | pieces[ROOK] | pieces[6 + ROOK] | pieces[QUEEN] | pieces[6 + QUEEN]) return false;
    int minors = popcount(pieces[KNIGHT] | pieces[BISHOP] | pieces[6 + KNIGHT] | pieces[6 + BISHOP]);
    return minors <= 1;
}

bool Position::isDraw(int ply) const {
    if (halfmove >= 100) return true;
    if (insufficientMaterial()) return true;
    int n = (int)hist.size(), cnt = 0;
    for (int i = 4; i <= halfmove && i <= n; i += 2) {
        if (hist[n - i].key == key) {
            if (i <= ply) return true;
            if (++cnt >= 2) return true;
        }
    }
    return false;
}

static inline void addPromos(Move*& o, int f, int t, bool capsOnly) {
    *o++ = makeMove(f, t, 4);
    if (capsOnly) return;
    *o++ = makeMove(f, t, 3);
    *o++ = makeMove(f, t, 2);
    *o++ = makeMove(f, t, 1);
}

int Position::gen(Move* out, bool capsOnly) const {
    Move* o = out;
    int us = side, them = us ^ 1;
    U64 own = occ[us], enemy = occ[them];
    int up = us == WHITE ? 8 : -8;
    int startRank = us == WHITE ? 1 : 6, promoRank = us == WHITE ? 6 : 1;
    U64 pw = pieces[us * 6 + PAWN];
    while (pw) {
        int s = popLsb(pw);
        int r = s >> 3, to = s + up;
        bool promo = r == promoRank;
        if (board[to] == NO_PIECE) {
            if (promo) addPromos(o, s, to, capsOnly);
            else if (!capsOnly) {
                *o++ = makeMove(s, to);
                if (r == startRank && board[to + up] == NO_PIECE) *o++ = makeMove(s, to + up);
            }
        }
        U64 at = pawnAtt[us][s] & enemy;
        while (at) {
            int t = popLsb(at);
            if (promo) addPromos(o, s, t, capsOnly);
            else *o++ = makeMove(s, t);
        }
        if (ep != -1 && (pawnAtt[us][s] & bit(ep))) *o++ = makeMove(s, ep);
    }
    U64 targets = capsOnly ? enemy : ~own;
    for (int type = KNIGHT; type <= KING; type++) {
        U64 b = pieces[us * 6 + type];
        while (b) {
            int s = popLsb(b);
            U64 a;
            switch (type) {
                case KNIGHT: a = knightAtt[s]; break;
                case BISHOP: a = bishopAttacks(s, all); break;
                case ROOK: a = rookAttacks(s, all); break;
                case QUEEN: a = queenAttacks(s, all); break;
                default: a = kingAtt[s]; break;
            }
            a &= targets;
            while (a) *o++ = makeMove(s, popLsb(a));
        }
    }
    if (!capsOnly && castling) {
        if (us == WHITE) {
            if ((castling & WK_RIGHT) && board[4] == 5 && board[7] == 3 && !(all & (bit(5) | bit(6))) &&
                !attacked(4, BLACK) && !attacked(5, BLACK) && !attacked(6, BLACK))
                *o++ = makeMove(4, 6);
            if ((castling & WQ_RIGHT) && board[4] == 5 && board[0] == 3 && !(all & (bit(1) | bit(2) | bit(3))) &&
                !attacked(4, BLACK) && !attacked(3, BLACK) && !attacked(2, BLACK))
                *o++ = makeMove(4, 2);
        } else {
            if ((castling & BK_RIGHT) && board[60] == 11 && board[63] == 9 && !(all & (bit(61) | bit(62))) &&
                !attacked(60, WHITE) && !attacked(61, WHITE) && !attacked(62, WHITE))
                *o++ = makeMove(60, 62);
            if ((castling & BQ_RIGHT) && board[60] == 11 && board[56] == 9 && !(all & (bit(57) | bit(58) | bit(59))) &&
                !attacked(60, WHITE) && !attacked(59, WHITE) && !attacked(58, WHITE))
                *o++ = makeMove(60, 58);
        }
    }
    return (int)(o - out);
}

std::vector<Move> Position::legalMoves() {
    Move ml[256];
    int n = gen(ml, false);
    std::vector<Move> res;
    for (int i = 0; i < n; i++) {
        make(ml[i]);
        if (legalAfterMake()) res.push_back(ml[i]);
        unmake();
    }
    return res;
}

bool Position::parseMove(const std::string& s, Move& out) {
    if (s.size() < 4 || s.size() > 5) return false;
    for (Move m : legalMoves())
        if (moveToString(m) == s) {
            out = m;
            return true;
        }
    return false;
}

U64 perft(Position& p, int depth) {
    Move ml[256];
    int n = p.gen(ml, false);
    U64 c = 0;
    for (int i = 0; i < n; i++) {
        p.make(ml[i]);
        if (p.legalAfterMake()) c += depth == 1 ? 1 : perft(p, depth - 1);
        p.unmake();
    }
    return c;
}
