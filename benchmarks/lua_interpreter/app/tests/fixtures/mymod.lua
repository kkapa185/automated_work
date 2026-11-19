local M = {}
M.name = ...
M.loaded_from = select(2, ...)
function M.add(a, b) return a + b end
return M
