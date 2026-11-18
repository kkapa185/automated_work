-- smoke check of string/utf8/os/math through the real CLI
local s = string.format('%5.2f', math.pi)
assert(s == " 3.14", s)
assert(#utf8.char(8364) == 3)
assert(os.date('!%Y', 0) == "1970")
print(s, #utf8.char(8364), os.date('!%Y', 0))
