// UCI front end.
#include <chrono>
#include <iostream>
#include <sstream>
#include <thread>

#include "chess.h"
#include "output.h"
#include "search.h"

static Position g_pos;
static std::thread g_worker;
static bool g_infiniteSearch = false;

static void stopSearch() {
    g_stop = true;
    if (g_worker.joinable()) g_worker.join();
}

static void waitSearch() {
    if (g_worker.joinable()) g_worker.join();
}

static void cmdPosition(std::istringstream& in) {
    std::string tok;
    in >> tok;
    Position np;
    bool ok = true;
    if (tok == "startpos") {
        np.setStartpos();
        in >> tok;
    } else if (tok == "fen") {
        std::string fen;
        while (in >> tok && tok != "moves") fen += tok + " ";
        ok = np.setFen(fen);
    } else {
        return;
    }
    if (!ok) {
        out("info string invalid fen");
        return;
    }
    if (tok == "moves") {
        std::string ms;
        while (in >> ms) {
            Move m;
            if (!np.parseMove(ms, m)) {
                out("info string illegal move " + ms);
                break;
            }
            np.make(m);
        }
    }
    g_pos = np;
}

static void cmdGo(std::istringstream& in) {
    Limits lim;
    std::string tok;
    int perftDepth = -1;
    while (in >> tok) {
        if (tok == "depth") in >> lim.depth;
        else if (tok == "movetime") in >> lim.movetime;
        else if (tok == "nodes") in >> lim.nodes;
        else if (tok == "wtime") in >> lim.wtime;
        else if (tok == "btime") in >> lim.btime;
        else if (tok == "winc") in >> lim.winc;
        else if (tok == "binc") in >> lim.binc;
        else if (tok == "movestogo") in >> lim.movestogo;
        else if (tok == "infinite") lim.infinite = true;
        else if (tok == "perft") in >> perftDepth;
    }
    if (perftDepth >= 0) {
        int d = perftDepth < 1 ? 1 : perftDepth;
        Position p = g_pos;
        Move ml[256];
        int n = p.gen(ml, false);
        U64 total = 0;
        for (int i = 0; i < n; i++) {
            p.make(ml[i]);
            if (p.legalAfterMake()) {
                U64 c = d == 1 ? 1 : perft(p, d - 1);
                total += c;
                out(moveToString(ml[i]) + ": " + std::to_string(c));
            }
            p.unmake();
        }
        out("");
        out("Nodes searched: " + std::to_string(total));
        return;
    }
    // No limits at all behaves like infinite.
    if (!lim.depth && !lim.nodes && !lim.movetime && lim.wtime < 0 && lim.btime < 0) lim.infinite = true;
    stopSearch();
    g_stop = false;
    g_infiniteSearch = lim.infinite;
    Position p = g_pos;
    g_worker = std::thread([p, lim]() mutable {
        Move best = think(p, lim);
        if (lim.infinite)
            while (!g_stop) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        out("bestmove " + moveToString(best));
    });
}

int main() {
    initTables();
    g_pos.setStartpos();
    ttResize(64);
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string cmd;
        if (!(in >> cmd)) continue;
        if (cmd == "uci") {
            out("id name ChessEngine7");
            out("id author Claude");
            out("option name Hash type spin default 64 min 1 max 4096");
            out("uciok");
        } else if (cmd == "isready") {
            out("readyok");
        } else if (cmd == "ucinewgame") {
            stopSearch();
            ttClear();
            g_pos.setStartpos();
        } else if (cmd == "setoption") {
            std::string tok, name, value;
            in >> tok;  // "name"
            while (in >> tok && tok != "value") name += (name.empty() ? "" : " ") + tok;
            while (in >> tok) value += (value.empty() ? "" : " ") + tok;
            if (name == "Hash") {
                int mb = atoi(value.c_str());
                if (mb < 1) mb = 1;
                if (mb > 4096) mb = 4096;
                stopSearch();
                ttResize((size_t)mb);
            }
        } else if (cmd == "position") {
            stopSearch();
            cmdPosition(in);
        } else if (cmd == "go") {
            cmdGo(in);
        } else if (cmd == "stop") {
            stopSearch();
        } else if (cmd == "quit") {
            stopSearch();
            return 0;
        } else if (cmd == "d") {
            out(g_pos.pretty());
            out("Fen: " + g_pos.fen());
            out("Key: " + std::to_string(g_pos.key));
            std::string ch = "Checkers:";
            U64 c = g_pos.attackersTo(g_pos.kingSq(g_pos.side), g_pos.side ^ 1);
            while (c) ch += " " + squareToString(popLsb(c));
            out(ch);
        } else if (cmd == "eval") {
            out("Eval: " + std::to_string(evaluate(g_pos)) + " cp (side to move)");
        }
    }
    // EOF: let a bounded search finish and print its bestmove; abort an infinite one.
    if (g_infiniteSearch) g_stop = true;
    waitSearch();
    return 0;
}
