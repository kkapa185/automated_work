local co = coroutine.wrap(function() coroutine.yield(1) end)
assert(co() == 1)
print("coroutine ok")
