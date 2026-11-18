// Core chess types: bitboards, position, move generation.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

typedef uint64_t U64;
typedef uint16_t Move;  // from | to<<6 | promoType<<12 (promoType: 1=N 2=B 3=R 4=Q, 0 none). 0 = null move.

enum Color { WHITE = 0, BLACK = 1 };
enum PieceType { PAWN = 0, KNIGHT, BISHOP, ROOK, QUEEN, KING };
const int NO_PIECE = 12;  // piece = color*6 + type
enum { WK_RIGHT = 1, WQ_RIGHT = 2, BK_RIGHT = 4, BQ_RIGHT = 8 };

inline int moveFrom(Move m) { return m & 63; }
inline int moveTo(Move m) { return (m >> 6) & 63; }
inline int movePromo(Move m) { return (m >> 12) & 7; }
inline Move makeMove(int f, int t, int promo = 0) { return (Move)(f | (t << 6) | (promo << 12)); }

inline int popcount(U64 b) { return __builtin_popcountll(b); }
inline int lsb(U64 b) { return __builtin_ctzll(b); }
inline int msb(U64 b) { return 63 - __builtin_clzll(b); }
inline int popLsb(U64& b) { int s = lsb(b); b &= b - 1; return s; }
inline U64 bit(int s) { return 1ULL << s; }

extern U64 knightAtt[64], kingAtt[64], pawnAtt[2][64], rayBB[8][64];
extern U64 zPiece[12][64], zCastle[16], zEp[8], zSide;
extern int castleMask[64];

void initTables();
U64 rookAttacks(int sq, U64 occ);
U64 bishopAttacks(int sq, U64 occ);
inline U64 queenAttacks(int sq, U64 occ) { return rookAttacks(sq, occ) | bishopAttacks(sq, occ); }

std::string moveToString(Move m);
std::string squareToString(int sq);

struct State {
    U64 key;
    int castling, ep, halfmove, captured;
    Move move;
};

struct Position {
    U64 pieces[12];
    U64 occ[2];
    U64 all;
    int board[64];
    int side, castling, ep, halfmove, fullmove;
    U64 key;
    std::vector<State> hist;

    Position();
    bool setFen(const std::string& fen);
    void setStartpos();
    std::string fen() const;
    std::string pretty() const;

    void make(Move m);
    void unmake();
    void makeNull();
    void unmakeNull();

    bool attacked(int sq, int byColor) const;
    U64 attackersTo(int sq, int byColor) const;
    int kingSq(int c) const { return lsb(pieces[c * 6 + KING]); }
    bool inCheck() const { return attacked(kingSq(side), side ^ 1); }
    // After make(): true if the side that just moved did not leave its king attacked.
    bool legalAfterMake() const { return !attacked(kingSq(side ^ 1), side); }

    // Pseudo-legal generation; capsOnly = captures and queen promotions only.
    int gen(Move* out, bool capsOnly) const;
    // Fully legal moves.
    std::vector<Move> legalMoves();
    bool isCapture(Move m) const;
    bool isDraw(int ply) const;
    bool insufficientMaterial() const;
    bool hasNonPawnMaterial(int c) const;
    bool parseMove(const std::string& s, Move& out);
    U64 computeKey() const;

   private:
    void put(int pc, int sq);
    void remove(int pc, int sq);
    bool epHashed() const;
};

U64 perft(Position& p, int depth);
