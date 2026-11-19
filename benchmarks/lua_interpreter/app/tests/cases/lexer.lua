-- R4: lexical rules
assert(#"\u{20AC}" == 3 and #"\u{7FFFFFFF}" == 6 and #"\u{7F}" == 1 and #"\u{80}" == 2)
assert("\x41\x42" == "AB" and "\65\066\067" == "ABC" and #"\0" == 1 and #"a\0b" == 3)
assert("a\z
        b" == "ab")
assert("a\
b" == "a\nb")
assert("\a\b\f\n\r\t\v\\\"\'" == "\7\8\12\10\13\9\11\92\34\39")
assert([[
first newline skipped]] == "first newline skipped")
assert([==[a]]b]=]c]==] == "a]]b]=]c")
assert(#[[

]] == 1)
--[[ long
comment ]] assert(true)
--[==[ another
]] still comment
]==] assert(true)
-- numerals
assert(0xff == 255 and 0XA == 10 and 1e2 == 100.0 and .5 == 0.5 and 3. == 3.0 and 0x.8 == 0.5)
assert(0x1p4 == 16.0 and 0x1.8p1 == 3.0 and 0xA.8p0 == 10.5 and 1E+2 == 100.0 and 5e-1 == 0.5)
assert(0xffffffffffffffff == -1 and 0x7fffffffffffffff == 9223372036854775807)
assert(0x10000000000000000 == 0)       -- hex integers wrap modulo 2^64
assert(9223372036854775807 + 1 < 0)    -- integer wraparound
local big = 9223372036854775808        -- decimal overflow -> float
assert(tostring(big) == "9.2233720368548e+18")
assert(tostring(100) == "100" and tostring(100.0) == "100.0" and tostring(1e100) == "1e+100")
-- shebang-free semantics, line numbers
local ok, msg = load("x = = 1", "=chunk")
assert(not ok and msg == "chunk:1: unexpected symbol near '='", msg)
ok, msg = load("x = 'abc", "=chunk")
assert(not ok and msg == "chunk:1: unfinished string near <eof>", msg)
ok, msg = load("x = 'abc\ny = 1", "=chunk")
assert(not ok and msg == "chunk:1: unfinished string near ''abc'", msg)
ok, msg = load("x = 3x", "=chunk")
assert(not ok and msg == "chunk:1: malformed number near '3x'", msg)
ok, msg = load("x = [==[ abc", "=chunk")
assert(not ok and msg == "chunk:1: unfinished long string (starting at line 1) near <eof>", msg)
ok, msg = load("\n\nx = '\\q'", "=chunk")
assert(not ok and msg == "chunk:3: invalid escape sequence near ''\\q'", msg)
ok, msg = load("x = '\\300'", "=chunk")
assert(not ok and msg == "chunk:1: decimal escape too large near ''\\300'", msg)
ok, msg = load("x = '\\xZZ'", "=chunk")
assert(not ok and msg == "chunk:1: hexadecimal digit expected near ''\\xZ'", msg)
ok, msg = load("--[[ unfinished", "=chunk")
assert(not ok and msg == "chunk:1: unfinished long comment (starting at line 1) near <eof>", msg)
-- identifiers / keywords
local _a1, __ = 1, 2
assert(_a1 + __ == 3)
print("lexer ok")
