print(1, 1.0, -0.0, 3 // 2, 3.0 // 2, 7 % -3, -7 % 3, 2^10, 10 / 4, 1e100, math.maxinteger + 1 == math.mininteger)
print(0x10, 0xA.8p1, 1e2, "10" + 5, "3" * "4", 10 .. 20, #"héllo", 5 & 3, 5 | 3, 5 ~ 3, ~0, 1 << 62, 256 >> 4)
print(tostring(nil), tostring(true), tonumber("0x1F"), tonumber("10", 2), tonumber("z", 36), tonumber("  12  "), tonumber("1e1"))
print(math.type(1), math.type(1.0), math.type("1"), math.tointeger(3.0), 3 == 3.0, math.huge, -math.huge)
print(string.format("%5.2f|%-5d|%x|%X|%o|%e|%g|%q|%s|%c|%%", 3.14159, 42, 255, 255, 8, 12345.678, 0.0001, "a\nb", {} ~= nil, 65))
local t = {10, 20, 30, nil, x = 1}
print(#"abc", select("#", 1, nil, 3), select(2, "a", "b", "c"))
local a, b, c = (function() return 1, 2, 3 end)()
print(a, b, c, (function() return 1, 2, 3 end)())
