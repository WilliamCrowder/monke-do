-- mini_busted.lua: the small part of busted + luassert the specs use, for machines with no
-- Lua toolchain (tests/lua/run_specs.py runs it on the Lua 5.1 bundled with lupa).
-- CI runs the same specs with real busted. Keep specs inside this subset:
--   describe, it, pending, before_each, after_each
--   assert(cond, msg), assert.are.equal, assert.are.same, assert.is_true, assert.is_false,
--   assert.is_nil, assert.is_not_nil, assert.has_no.errors, assert.has_error

MiniBusted = { passed = 0, failed = 0, pending = 0, failures = {} }

local print = print -- the WoW stubs replace the global print to capture addon output

local stack = { { name = "", before = {}, after = {} } }

local function fullName(name)
    local parts = {}
    for _, ctx in ipairs(stack) do
        if ctx.name ~= "" then
            parts[#parts + 1] = ctx.name
        end
    end
    parts[#parts + 1] = name
    return table.concat(parts, " ")
end

function describe(name, body)
    stack[#stack + 1] = { name = name, before = {}, after = {} }
    body()
    stack[#stack] = nil
end

function before_each(fn)
    local ctx = stack[#stack]
    ctx.before[#ctx.before + 1] = fn
end

function after_each(fn)
    local ctx = stack[#stack]
    ctx.after[#ctx.after + 1] = fn
end

function pending(name)
    MiniBusted.pending = MiniBusted.pending + 1
    print("PENDING  " .. fullName(name))
end

function it(name, body)
    local label = fullName(name)
    local ok, err = xpcall(function()
        for _, ctx in ipairs(stack) do
            for _, fn in ipairs(ctx.before) do
                fn()
            end
        end
        body()
        for i = #stack, 1, -1 do
            for _, fn in ipairs(stack[i].after) do
                fn()
            end
        end
    end, function(message)
        return debug.traceback(tostring(message), 2)
    end)
    if ok then
        MiniBusted.passed = MiniBusted.passed + 1
    else
        MiniBusted.failed = MiniBusted.failed + 1
        MiniBusted.failures[#MiniBusted.failures + 1] = label .. "\n" .. tostring(err)
        print("FAIL     " .. label)
    end
end

local function show(value)
    if type(value) == "string" then
        return ("%q"):format(value)
    end
    if type(value) ~= "table" then
        return tostring(value)
    end
    local keys = {}
    for k in pairs(value) do
        keys[#keys + 1] = k
    end
    table.sort(keys, function(a, b)
        return tostring(a) < tostring(b)
    end)
    local parts = {}
    for _, k in ipairs(keys) do
        parts[#parts + 1] = "[" .. show(k) .. "] = " .. show(value[k])
    end
    return "{ " .. table.concat(parts, ", ") .. " }"
end

local function same(a, b)
    if type(a) ~= "table" or type(b) ~= "table" then
        return a == b
    end
    for k, v in pairs(a) do
        if not same(v, b[k]) then
            return false
        end
    end
    for k in pairs(b) do
        if a[k] == nil then
            return false
        end
    end
    return true
end

local function fail(message, extra)
    if extra ~= nil then
        message = message .. "\n" .. tostring(extra)
    end
    error(message, 3)
end

local are = {}
function are.equal(expected, actual, message)
    if expected ~= actual then
        fail("expected: " .. show(expected) .. "\n  actual: " .. show(actual), message)
    end
end
function are.same(expected, actual, message)
    if not same(expected, actual) then
        fail("expected same: " .. show(expected) .. "\n       actual: " .. show(actual), message)
    end
end

local has_no = {}
function has_no.errors(fn)
    local ok, err = pcall(fn)
    if not ok then
        fail("expected no error, got: " .. tostring(err))
    end
end

local lib = { are = are, has_no = has_no }
function lib.is_true(value, message)
    if value ~= true then
        fail("expected true, got " .. show(value), message)
    end
end
function lib.is_false(value, message)
    if value ~= false then
        fail("expected false, got " .. show(value), message)
    end
end
function lib.is_nil(value, message)
    if value ~= nil then
        fail("expected nil, got " .. show(value), message)
    end
end
function lib.is_not_nil(value, message)
    if value == nil then
        fail("expected a value, got nil", message)
    end
end
function lib.has_error(fn)
    if pcall(fn) then
        fail("expected an error")
    end
end

local plainAssert = assert
assert = setmetatable(lib, {
    __call = function(_, ...)
        return plainAssert(...)
    end,
})

-- Real busted runs each spec file in a sandbox: reads fall through to _G, but a bare
-- global assignment lands in a private table the addon never sees. Do the same here, so a
-- spec that forgets to write through _G fails on this machine and not only in CI.
local function sandboxed(chunk)
    setfenv(chunk, setmetatable({}, { __index = _G }))
    return chunk
end

function MiniBusted.runFiles(paths)
    for _, path in ipairs(paths) do
        local chunk, err = loadfile(path)
        if not chunk then
            MiniBusted.failed = MiniBusted.failed + 1
            MiniBusted.failures[#MiniBusted.failures + 1] = path .. "\n" .. tostring(err)
        else
            sandboxed(chunk)()
        end
    end
    for _, failure in ipairs(MiniBusted.failures) do
        print("\n" .. failure)
    end
    print(("\n%d passed, %d failed, %d pending"):format(MiniBusted.passed, MiniBusted.failed, MiniBusted.pending))
    return MiniBusted.failed
end
