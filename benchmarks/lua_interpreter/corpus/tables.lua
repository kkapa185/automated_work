local t = {}
for i = 1, 10 do t[#t + 1] = i * i end
print(#t, table.concat(t, ","), table.concat(t, "-", 3, 5))
table.insert(t, 1, 0); table.insert(t, 99); print(table.remove(t), table.remove(t, 1), #t)
local words = {"banana", "apple", "Cherry", "date"}
table.sort(words); print(table.concat(words, " "))
table.sort(words, function(a, b) return a:lower() > b:lower() end); print(table.concat(words, " "))
print(table.unpack({1, 2, 3})); local p = table.pack(1, nil, 3); print(p.n, p[1], p[2], p[3])
print(table.concat(table.move({1, 2, 3}, 1, 3, 2, {9}), ","))
local keys = {} for k in pairs({a = 1, b = 2, c = 3}) do keys[#keys + 1] = k end table.sort(keys) print(table.concat(keys))
for i, v in ipairs({"x", "y", nil, "z"}) do io.write(i, v, " ") end print()
local m = setmetatable({}, {__index = function(t, k) return k * 2 end}); print(m[21], rawget(m, 21))
local nested = {a = {b = {c = "deep"}}}; print(nested.a.b.c, next({}), type(next({1})))
