#pragma once
#include <atomic>

#include "chess.h"

int evaluate(const Position& p);  // centipawns, side-to-move perspective

struct Limits {
    int depth = 0;           // 0 = unlimited
    long long nodes = 0;     // 0 = unlimited
    int movetime = 0;        // ms, 0 = none
    int wtime = -1, btime = -1, winc = 0, binc = 0, movestogo = 0;
    bool infinite = false;
};

extern std::atomic<bool> g_stop;

void ttResize(size_t mb);
void ttClear();

// Runs a search on a copy of pos, printing UCI info lines. Returns the best move (0 if none).
Move think(Position& pos, const Limits& lim);
