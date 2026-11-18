// Iterative deepening PVS alpha-beta search with quiescence and a transposition table.
#include "search.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>

#include "output.h"

std::atomic<bool> g_stop(false);

namespace {
const int MATE = 30000;
const int MATE_BOUND = MATE - 200;
const int INF = 32000;
const int MAXPLY = 128;
const int VAL[7] = {100, 320, 330, 500, 900, 20000, 0};

enum { TT_NONE = 0, TT_EXACT, TT_LOWER, TT_UPPER };
struct TTEntry {
    U64 key;
    int16_t score;
    Move move;
    int8_t depth;
    uint8_t flag;
};
std::vector<TTEntry> tt(1 << 20);
size_t ttMask = (1 << 20) - 1;

inline TTEntry& ttSlot(U64 key) { return tt[key & ttMask]; }

int scoreToTT(int s, int ply) { return s > MATE_BOUND ? s + ply : (s < -MATE_BOUND ? s - ply : s); }
int scoreFromTT(int s, int ply) { return s > MATE_BOUND ? s - ply : (s < -MATE_BOUND ? s + ply : s); }

struct Searcher {
    Position pos;
    Limits lim;
    std::chrono::steady_clock::time_point start;
    long long hardMs = 0, softMs = 0;
    long long nodes = 0;
    bool stopped = false;
    int rootDepth = 0, seldepth = 0;
    Move pv[MAXPLY + 1][MAXPLY + 1];
    int pvLen[MAXPLY + 1];
    Move killers[MAXPLY + 1][2];
    int history[2][64][64];
    int lmr[64][64];

    long long elapsed() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
    }

    void checkTime() {
        if (rootDepth <= 1) return;
        if (g_stop.load(std::memory_order_relaxed)) stopped = true;
        else if (lim.nodes && nodes >= lim.nodes) stopped = true;
        else if (hardMs && elapsed() >= hardMs) stopped = true;
    }

    int scoreMove(Move m, Move ttMove, int ply) const {
        if (m == ttMove) return 10000000;
        int f = moveFrom(m), t = moveTo(m);
        int promo = movePromo(m);
        if (pos.isCapture(m)) {
            int victim = pos.board[t] == NO_PIECE ? PAWN : pos.board[t] % 6;
            return 1000000 + VAL[victim] * 10 - VAL[pos.board[f] % 6] / 10 + (promo ? 5000 : 0);
        }
        if (promo) return 900000 + promo;
        if (m == killers[ply][0]) return 800000;
        if (m == killers[ply][1]) return 790000;
        return history[pos.side][f][t];
    }

    int qsearch(int alpha, int beta, int ply) {
        nodes++;
        if ((nodes & 2047) == 0) checkTime();
        if (stopped) return 0;
        if (ply > seldepth) seldepth = ply;
        if (ply >= MAXPLY - 1) return evaluate(pos);
        if (pos.isDraw(ply)) return 0;
        bool inCheck = pos.inCheck();
        int standPat = -INF;
        if (!inCheck) {
            standPat = evaluate(pos);
            if (standPat >= beta) return standPat;
            if (standPat > alpha) alpha = standPat;
        }
        Move ml[256];
        int sc[256];
        int n = pos.gen(ml, !inCheck);
        for (int i = 0; i < n; i++) sc[i] = scoreMove(ml[i], 0, ply);
        int legal = 0, best = inCheck ? -INF : standPat;
        for (int i = 0; i < n; i++) {
            int bi = i;
            for (int j = i + 1; j < n; j++)
                if (sc[j] > sc[bi]) bi = j;
            std::swap(ml[i], ml[bi]);
            std::swap(sc[i], sc[bi]);
            Move m = ml[i];
            if (!inCheck && !movePromo(m)) {
                int victim = pos.board[moveTo(m)] == NO_PIECE ? PAWN : pos.board[moveTo(m)] % 6;
                if (standPat + VAL[victim] + 200 < alpha) continue;
            }
            pos.make(m);
            if (!pos.legalAfterMake()) {
                pos.unmake();
                continue;
            }
            legal++;
            int s = -qsearch(-beta, -alpha, ply + 1);
            pos.unmake();
            if (stopped) return 0;
            if (s > best) {
                best = s;
                if (s > alpha) {
                    alpha = s;
                    if (s >= beta) break;
                }
            }
        }
        if (inCheck && legal == 0) return -MATE + ply;
        return best;
    }

    int negamax(int depth, int alpha, int beta, int ply, bool allowNull) {
        pvLen[ply] = ply;
        if (ply >= MAXPLY - 1) return evaluate(pos);
        nodes++;
        if ((nodes & 2047) == 0) checkTime();
        if (stopped) return 0;
        bool pvNode = beta - alpha > 1;
        bool root = ply == 0;
        bool inCheck = pos.inCheck();
        if (!root) {
            if (pos.isDraw(ply)) return 0;
            alpha = std::max(alpha, -MATE + ply);
            beta = std::min(beta, MATE - ply - 1);
            if (alpha >= beta) return alpha;
        }
        if (inCheck) depth++;
        if (depth <= 0) return qsearch(alpha, beta, ply);
        if (ply > seldepth) seldepth = ply;

        TTEntry& e = ttSlot(pos.key);
        Move ttMove = 0;
        int ttScore = 0;
        bool ttHit = e.key == pos.key && e.flag != TT_NONE;
        if (ttHit) {
            ttMove = e.move;
            ttScore = scoreFromTT(e.score, ply);
            if (!pvNode && e.depth >= depth) {
                if (e.flag == TT_EXACT) return ttScore;
                if (e.flag == TT_LOWER && ttScore >= beta) return ttScore;
                if (e.flag == TT_UPPER && ttScore <= alpha) return ttScore;
            }
        }
        int staticEval = inCheck ? -INF : evaluate(pos);
        if (!pvNode && !inCheck && std::abs(beta) < MATE_BOUND) {
            if (depth <= 3 && staticEval - 120 * depth >= beta) return staticEval;
            if (allowNull && depth >= 3 && staticEval >= beta && pos.hasNonPawnMaterial(pos.side)) {
                int R = 2 + depth / 4;
                pos.makeNull();
                int s = -negamax(depth - 1 - R, -beta, -beta + 1, ply + 1, false);
                pos.unmakeNull();
                if (stopped) return 0;
                if (s >= beta) return s >= MATE_BOUND ? beta : s;
            }
        }

        Move ml[256];
        int sc[256];
        int n = pos.gen(ml, false);
        for (int i = 0; i < n; i++) sc[i] = scoreMove(ml[i], ttMove, ply);
        int legal = 0, best = -INF;
        Move bestMove = 0;
        int origAlpha = alpha;
        Move quietsTried[256];
        int nq = 0;
        for (int i = 0; i < n; i++) {
            int bi = i;
            for (int j = i + 1; j < n; j++)
                if (sc[j] > sc[bi]) bi = j;
            std::swap(ml[i], ml[bi]);
            std::swap(sc[i], sc[bi]);
            Move m = ml[i];
            bool quiet = !pos.isCapture(m) && !movePromo(m);
            pos.make(m);
            if (!pos.legalAfterMake()) {
                pos.unmake();
                continue;
            }
            legal++;
            bool givesCheck = pos.inCheck();
            if (quiet && !pvNode && !inCheck && !givesCheck && depth <= 3 && legal > 4 + depth * depth &&
                std::abs(alpha) < MATE_BOUND) {
                pos.unmake();
                continue;
            }
            int s;
            if (legal == 1) {
                s = -negamax(depth - 1, -beta, -alpha, ply + 1, true);
            } else {
                int r = 0;
                if (depth >= 3 && legal > 3 && quiet && !inCheck && !givesCheck) {
                    r = lmr[std::min(depth, 63)][std::min(legal, 63)];
                    if (pvNode) r--;
                    if (m == killers[ply][0] || m == killers[ply][1]) r--;
                    r = std::max(0, std::min(r, depth - 2));
                }
                s = -negamax(depth - 1 - r, -alpha - 1, -alpha, ply + 1, true);
                if (s > alpha && r > 0) s = -negamax(depth - 1, -alpha - 1, -alpha, ply + 1, true);
                if (s > alpha && s < beta) s = -negamax(depth - 1, -beta, -alpha, ply + 1, true);
            }
            pos.unmake();
            if (stopped) return 0;
            if (quiet) quietsTried[nq++] = m;
            if (s > best) {
                best = s;
                bestMove = m;
                if (s > alpha) {
                    alpha = s;
                    pv[ply][ply] = m;
                    for (int k = ply + 1; k < pvLen[ply + 1]; k++) pv[ply][k] = pv[ply + 1][k];
                    pvLen[ply] = std::max(pvLen[ply + 1], ply + 1);
                    if (s >= beta) {
                        if (quiet) {
                            if (killers[ply][0] != m) {
                                killers[ply][1] = killers[ply][0];
                                killers[ply][0] = m;
                            }
                            int bonus = std::min(depth * depth, 400);
                            for (int k = 0; k < nq; k++) {
                                int& h = history[pos.side][moveFrom(quietsTried[k])][moveTo(quietsTried[k])];
                                int b = quietsTried[k] == m ? bonus : -bonus;
                                h += b - h * std::abs(b) / 16384;
                            }
                        }
                        break;
                    }
                }
            }
        }
        if (legal == 0) return inCheck ? -MATE + ply : 0;
        if (!stopped) {
            uint8_t flag = best >= beta ? TT_LOWER : (best > origAlpha ? TT_EXACT : TT_UPPER);
            if (e.key != pos.key || e.flag == TT_NONE || depth >= e.depth - 2 || flag == TT_EXACT) {
                if (bestMove == 0 && e.key == pos.key) bestMove = e.move;
                e.key = pos.key;
                e.score = (int16_t)scoreToTT(best, ply);
                e.move = bestMove;
                e.depth = (int8_t)std::min(depth, 100);
                e.flag = flag;
            }
        }
        return best;
    }

    std::string scoreStr(int s) const {
        if (s > MATE_BOUND) return "mate " + std::to_string((MATE - s + 1) / 2);
        if (s < -MATE_BOUND) return "mate -" + std::to_string((MATE + s) / 2);
        return "cp " + std::to_string(s);
    }

    void report(int depth, int score) {
        long long ms = elapsed();
        std::string pvs;
        for (int i = 0; i < pvLen[0]; i++) pvs += " " + moveToString(pv[0][i]);
        long long nps = ms > 0 ? nodes * 1000 / ms : nodes * 1000;
        out("info depth " + std::to_string(depth) + " seldepth " + std::to_string(seldepth) + " score " + scoreStr(score) +
            " nodes " + std::to_string(nodes) + " nps " + std::to_string(nps) + " time " + std::to_string(ms) + " pv" + pvs);
    }

    Move run() {
        start = std::chrono::steady_clock::now();
        for (int d = 0; d < 64; d++)
            for (int m = 0; m < 64; m++) lmr[d][m] = (d && m) ? (int)(0.75 + std::log((double)d) * std::log((double)m) / 2.25) : 0;
        std::memset(killers, 0, sizeof killers);
        std::memset(history, 0, sizeof history);
        // time management
        bool timed = false, fixedTime = false;
        if (lim.movetime > 0) {
            hardMs = lim.movetime > 50 ? lim.movetime - 12 : std::max(1, lim.movetime * 3 / 4);
            softMs = hardMs;
            timed = true;
            fixedTime = true;
        } else if (!lim.infinite && (lim.wtime >= 0 || lim.btime >= 0) && lim.depth == 0 && lim.nodes == 0) {
            long long t = pos.side == WHITE ? lim.wtime : lim.btime;
            long long inc = pos.side == WHITE ? lim.winc : lim.binc;
            if (t < 0) t = 0;
            long long avail = std::max(1LL, t - 30);
            int mtg = lim.movestogo > 0 ? std::min(lim.movestogo, 40) : 30;
            softMs = std::max(1LL, std::min(avail * 8 / 10, avail / mtg + inc * 3 / 4));
            hardMs = std::max(softMs, std::min(avail * 6 / 10, softMs * 4));
            hardMs = std::max(1LL, hardMs);
            timed = true;
        }
        std::vector<Move> legal = pos.legalMoves();
        if (legal.empty()) {
            out(std::string("info depth 0 score ") + (pos.inCheck() ? "mate 0" : "cp 0"));
            return 0;
        }
        Move best = legal[0];
        int maxDepth = lim.depth > 0 ? std::min(lim.depth, MAXPLY - 2) : 64;
        int prevScore = 0;
        for (int d = 1; d <= maxDepth; d++) {
            rootDepth = d;
            int alpha = -INF, beta = INF, delta = 25;
            if (d >= 5) {
                alpha = std::max(-INF, prevScore - delta);
                beta = std::min(INF, prevScore + delta);
            }
            int score;
            while (true) {
                score = negamax(d, alpha, beta, 0, false);
                if (stopped) break;
                if (score <= alpha && alpha > -INF) {
                    alpha = std::max(-INF, alpha - delta);
                    delta *= 2;
                    if (delta > 400) alpha = -INF;
                } else if (score >= beta && beta < INF) {
                    beta = std::min(INF, beta + delta);
                    delta *= 2;
                    if (delta > 400) beta = INF;
                } else break;
            }
            if (stopped) break;
            prevScore = score;
            if (pvLen[0] > 0) best = pv[0][0];
            report(d, score);
            if (!lim.infinite && lim.depth == 0 && timed) {
                if (legal.size() == 1) break;
                if (!fixedTime && elapsed() * 2 >= softMs) break;
            }
            if (std::abs(score) > MATE_BOUND && timed && d >= 2 * ((MATE - std::abs(score) + 1) / 2) + 2) break;
        }
        return best;
    }
};
}  // namespace

void ttResize(size_t mb) {
    size_t n = 1024;
    while (n * 2 * sizeof(TTEntry) <= mb * 1024 * 1024) n *= 2;
    tt.assign(n, TTEntry{0, 0, 0, 0, TT_NONE});
    ttMask = n - 1;
}
void ttClear() { tt.assign(tt.size(), TTEntry{0, 0, 0, 0, TT_NONE}); }

Move think(Position& pos, const Limits& lim) {
    static Searcher* s = new Searcher();
    s->pos = pos;
    s->lim = lim;
    s->nodes = 0;
    s->stopped = false;
    s->rootDepth = 0;
    s->seldepth = 0;
    s->hardMs = s->softMs = 0;
    for (int i = 0; i <= MAXPLY; i++) s->pvLen[i] = i;
    Move m = s->run();
    return m;
}
