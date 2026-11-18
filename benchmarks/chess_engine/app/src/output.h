#pragma once
#include <cstdio>
#include <mutex>
#include <string>

// Thread-safe, flushed line output to stdout.
inline void out(const std::string& line) {
    static std::mutex m;
    std::lock_guard<std::mutex> g(m);
    std::fwrite(line.data(), 1, line.size(), stdout);
    std::fputc('\n', stdout);
    std::fflush(stdout);
}
