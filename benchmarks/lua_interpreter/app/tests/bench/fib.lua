-- limit: 5
-- R23: recursive fib(25) in a few seconds
local function fib(n) if n < 2 then return n end return fib(n - 1) + fib(n - 2) end
assert(fib(25) == 75025)
assert(fib(30) == 832040)
