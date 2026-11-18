// Hand-crafted tapered evaluation.
#include <algorithm>
#include <cstdlib>

#include "search.h"

namespace {
const int MAT_MG[6] = {82, 337, 365, 477, 1025, 0};
const int MAT_EG[6] = {94, 281, 297, 512, 936, 0};
const int PHASE_W[6] = {0, 1, 1, 2, 4, 0};
const int PASS_MG[8] = {0, 0, 5, 10, 20, 35, 60, 0};
const int PASS_EG[8] = {0, 0, 10, 20, 40, 70, 120, 0};

int pstMG[6][64], pstEG[6][64];
U64 fileMask[8], adjFiles[8], passedMask[2][64], frontFile[2][64], aheadMask[2][64];

struct EvalInit {
    EvalInit() {
        initTables();
        for (int f = 0; f < 8; f++) {
            fileMask[f] = 0;
            for (int r = 0; r < 8; r++) fileMask[f] |= bit(r * 8 + f);
        }
        for (int f = 0; f < 8; f++) {
            adjFiles[f] = 0;
            if (f > 0) adjFiles[f] |= fileMask[f - 1];
            if (f < 7) adjFiles[f] |= fileMask[f + 1];
        }
        for (int s = 0; s < 64; s++) {
            int f = s & 7, r = s >> 3;
            for (int c = 0; c < 2; c++) {
                U64 ahead = 0;
                for (int rr = 0; rr < 8; rr++)
                    if (c == WHITE ? rr > r : rr < r) ahead |= 0xFFULL << (rr * 8);
                aheadMask[c][s] = ahead;
                frontFile[c][s] = ahead & fileMask[f];
                passedMask[c][s] = ahead & (fileMask[f] | adjFiles[f]);
            }
            int fc = std::min(f, 7 - f), rc = std::min(r, 7 - r), center = fc + rc;
            pstMG[PAWN][s] = (r >= 1 && r <= 6) ? 4 * (r - 1) + ((fc >= 2 && r <= 4) ? 8 : 0) - (fc == 0 ? 4 : 0) : 0;
            pstEG[PAWN][s] = (r >= 1 && r <= 6) ? 8 * (r - 1) : 0;
            pstMG[KNIGHT][s] = 7 * center - 28;
            pstEG[KNIGHT][s] = 5 * center - 20;
            pstMG[BISHOP][s] = 3 * center - 10 + ((r == 0) ? -4 : 0);
            pstEG[BISHOP][s] = 2 * center - 6;
            pstMG[ROOK][s] = (r == 6 ? 10 : 0) + (fc == 3 ? 4 : 0) + (r == 0 && fc == 3 ? 2 : 0);
            pstEG[ROOK][s] = (r == 6 ? 8 : 0);
            pstMG[QUEEN][s] = 2 * center - 6;
            pstEG[QUEEN][s] = 4 * center - 12;
            pstMG[KING][s] = -14 * r + (fc <= 1 ? 12 : 0) - (fc == 3 ? 8 : 0);
            pstEG[KING][s] = 9 * center - 24;
        }
    }
} evalInit;
}  // namespace

int evaluate(const Position& p) {
    int mg[2] = {0, 0}, eg[2] = {0, 0}, units[2] = {0, 0}, phase = 0;
    U64 pawnsOf[2] = {p.pieces[PAWN], p.pieces[6 + PAWN]};
    for (int c = 0; c < 2; c++) {
        int them = c ^ 1;
        U64 own = pawnsOf[c], en = pawnsOf[them];
        U64 enPawnAtt = 0;
        for (U64 b = en; b;) enPawnAtt |= pawnAtt[them][popLsb(b)];
        U64 mobArea = ~p.occ[c] & ~enPawnAtt;
        int eks = p.kingSq(them);
        U64 ezone = kingAtt[eks] | bit(eks);
        for (int t = PAWN; t <= KING; t++) {
            U64 b = p.pieces[c * 6 + t];
            if (t != PAWN && t != KING && b) phase += PHASE_W[t] * popcount(b);
            if (t == BISHOP && popcount(b) >= 2) {
                mg[c] += 30;
                eg[c] += 50;
            }
            while (b) {
                int s = popLsb(b);
                int idx = c == WHITE ? s : s ^ 56;
                mg[c] += MAT_MG[t] + pstMG[t][idx];
                eg[c] += MAT_EG[t] + pstEG[t][idx];
                int f = s & 7, rel = c == WHITE ? (s >> 3) : 7 - (s >> 3);
                U64 a = 0;
                switch (t) {
                    case PAWN: {
                        bool doubled = (own & frontFile[c][s]) != 0;
                        if (doubled) {
                            mg[c] -= 10;
                            eg[c] -= 20;
                        }
                        if (!(own & adjFiles[f])) {
                            mg[c] -= 10;
                            eg[c] -= 8;
                        }
                        if (!doubled && !(en & passedMask[c][s])) {
                            mg[c] += PASS_MG[rel];
                            eg[c] += PASS_EG[rel];
                        }
                        break;
                    }
                    case KNIGHT:
                        a = knightAtt[s];
                        mg[c] += 4 * (popcount(a & mobArea) - 4);
                        eg[c] += 4 * (popcount(a & mobArea) - 4);
                        units[them] += 2 * popcount(a & ezone);
                        break;
                    case BISHOP:
                        a = bishopAttacks(s, p.all);
                        mg[c] += 3 * (popcount(a & mobArea) - 6);
                        eg[c] += 3 * (popcount(a & mobArea) - 6);
                        units[them] += 2 * popcount(a & ezone);
                        break;
                    case ROOK:
                        a = rookAttacks(s, p.all);
                        mg[c] += 2 * (popcount(a & mobArea) - 7);
                        eg[c] += 4 * (popcount(a & mobArea) - 7);
                        units[them] += 3 * popcount(a & ezone);
                        if (!(own & fileMask[f])) {
                            int bonus = (en & fileMask[f]) ? 6 : 12;
                            mg[c] += bonus;
                            eg[c] += bonus / 2;
                        }
                        break;
                    case QUEEN:
                        a = queenAttacks(s, p.all);
                        mg[c] += 1 * (popcount(a & mobArea) - 13);
                        eg[c] += 2 * (popcount(a & mobArea) - 13);
                        units[them] += 5 * popcount(a & ezone);
                        break;
                    case KING: {
                        int krank = s >> 3;
                        for (int ff = std::max(0, f - 1); ff <= std::min(7, f + 1); ff++) {
                            U64 pw = own & fileMask[ff] & aheadMask[c][s];
                            if (!pw) {
                                mg[c] -= 15;
                                continue;
                            }
                            int ps = c == WHITE ? lsb(pw) : msb(pw);
                            int d = std::abs((ps >> 3) - krank);
                            mg[c] += d == 1 ? 10 : (d == 2 ? 6 : -8);
                        }
                        break;
                    }
                }
            }
        }
    }
    for (int c = 0; c < 2; c++) mg[c] -= std::min(units[c] * units[c] / 6, 200);
    if (phase > 24) phase = 24;
    int smg = mg[WHITE] - mg[BLACK], seg = eg[WHITE] - eg[BLACK];
    int score = (smg * phase + seg * (24 - phase)) / 24;
    score = p.side == WHITE ? score : -score;
    return score + 8;
}
