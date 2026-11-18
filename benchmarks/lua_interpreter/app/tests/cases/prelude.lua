-- shared helpers (loaded via dofile); uses only the base library
maxint = 9223372036854775807
minint = -9223372036854775807 - 1
function eq(a, b, msg)
  local bad = false
  if a ~= b and not (a ~= a and b ~= b) then bad = true end
  if not bad and type(a) == "number" and a == a and tostring(a) ~= tostring(b) then bad = true end
  if bad then
    error("expected " .. tostring(b) .. " got " .. tostring(a) .. " " .. tostring(msg or ""), 2)
  end
end
-- run a source snippet as chunk "c" and return the error message
function err(src, ...)
  local f = assert(load(src, "=c"))
  local ok, e = pcall(f, ...)
  assert(not ok, "expected an error from: " .. src)
  return e
end
-- compile a snippet that must fail to compile; return the message
function cerr(src)
  local f, e = load(src, "=c")
  assert(not f, "expected a compile error from: " .. src)
  return e
end
