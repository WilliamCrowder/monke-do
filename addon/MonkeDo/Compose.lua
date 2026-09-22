-- Compose.lua: pure function from quest inputs to the text Monke Do shows.
-- No WoW API calls in here, so busted covers all of it. Display.lua gathers the
-- inputs and puts the output on screen.
-- Rendering rules: docs/DATA_CONTRACT.md section 2.

local _, ns = ...

local Voice = ns.Voice
local Rules = ns.Rules

local Compose = {}
ns.Compose = Compose

Compose.SCHEMA = 3
Compose.GROUP_COLOR = "|cffff2020"

local function stripFinalStop(s)
    return (s:gsub("[%.%s]+$", ""))
end

-- A record from a newer schema, or a malformed one, is ignored rather than trusted.
function Compose.UsableRecord(record)
    if type(record) ~= "table" then
        return nil
    end
    if type(record.v) ~= "number" or record.v > Compose.SCHEMA then
        return nil
    end
    if record.l ~= nil and type(record.l) ~= "string" then
        return nil
    end
    if record.p ~= nil and type(record.p) ~= "string" then
        return nil
    end
    if record.t ~= nil then
        if type(record.t) ~= "table" then
            return nil
        end
        for _, line in ipairs(record.t) do
            if type(line) ~= "string" then
                return nil
            end
        end
    end
    if record.n ~= nil then
        if type(record.n) ~= "number" or record.n < 0 or record.n > #(record.t or {}) then
            return nil
        end
    end
    return record
end

-- Does `needle` occur in `haystack` as whole words? Plain find, then a look at the
-- characters either side, so "Rockjaw Trogg" is not found inside "Burly Rockjaw Trogg"
-- and "Ore" is not found inside "Orebender".
local function containsWords(haystack, needle)
    local from = 1
    while true do
        local i, j = haystack:find(needle, from, true)
        if not i then
            return false
        end
        local before = i > 1 and haystack:sub(i - 1, i - 1) or " "
        local after = haystack:sub(j + 1, j + 1)
        if not before:match("[%w']") and not after:match("[%w]") then
            return true
        end
        from = i + 1
    end
end

-- What a live objective is called, lower case, for matching against DB lines.
local function needleOf(objective)
    local name = Rules.ParseObjectiveText(objective.text)
    return stripFinalStop(name):lower()
end

-- 0 = this DB line cannot be this objective, 1 = plausible, 2 = names it.
local function score(line, objective, needle)
    if Rules.COUNTED[objective.type] then
        local _, _, parsedNeed = Rules.ParseObjectiveText(objective.text)
        local need = objective.numRequired or parsedNeed
        if need and need > 1 then
            local found = false
            for number in line:gmatch("%d+") do
                if tonumber(number) == need then
                    found = true
                end
            end
            if not found then
                return 0
            end
        end
    end
    local haystack = line:lower()
    if needle ~= "" then
        if containsWords(haystack, needle) then
            return 2
        end
        local singular = needle:gsub("s$", "")
        if singular ~= needle and containsWords(haystack, singular) then
            return 2
        end
    end
    return 1
end

-- The pipeline orders t[1..n] like the game's objectives, but the two orders come from
-- different data. Pair every DB line with a live objective by name and count first, take
-- the same-position line only when nothing contradicts it, and give up (rule-based
-- bullets) rather than show "Bonk 8 Kobold (3/10)" or progress on the wrong line.
local function assign(lines, n, live)
    local needles, scores = {}, {}
    for i, objective in ipairs(live) do
        needles[i] = needleOf(objective)
        scores[i] = {}
        for j = 1, n do
            scores[i][j] = score(lines[j], objective, needles[i])
        end
    end

    local used, order = {}, {}
    -- Pass 1: lines that name an objective, longest name first so "Burly Rockjaw Trogg"
    -- takes its line before "Rockjaw Trogg" looks.
    local byLength = {}
    for i = 1, #live do
        byLength[i] = i
    end
    table.sort(byLength, function(a, b)
        if #needles[a] ~= #needles[b] then
            return #needles[a] > #needles[b]
        end
        return a < b
    end)
    for _, i in ipairs(byLength) do
        local named = {}
        for j = 1, n do
            if not used[j] and scores[i][j] == 2 then
                named[#named + 1] = j
            end
        end
        if #named == 1 then
            used[named[1]] = true
            order[i] = named[1]
        elseif #named > 1 then
            local same = false
            for _, j in ipairs(named) do
                if j == i then
                    same = true
                end
            end
            if not same then
                return nil
            end
            used[i] = true
            order[i] = i
        end
    end
    -- Pass 2: the rest keep their position, but only when that line names no live
    -- objective and nothing rules it out.
    local unbound = {}
    for i = 1, #live do
        if not order[i] then
            local positional = not used[i] and scores[i][i] >= 1
            for k = 1, #live do
                if k ~= i and scores[k][i] == 2 then
                    positional = false
                end
            end
            if positional then
                used[i] = true
                order[i] = i
            else
                unbound[#unbound + 1] = i
            end
        end
    end
    -- Pass 3: one objective and one line left is not a guess, unless that line names
    -- some other objective.
    if #unbound == 1 then
        local i = unbound[1]
        local free
        for j = 1, n do
            if not used[j] then
                free = free and -1 or j
            end
        end
        local clean = free and free > 0 and scores[i][free] >= 1
        for k = 1, #live do
            if clean and k ~= i and scores[k][free] == 2 then
                clean = false
            end
        end
        if clean then
            used[free] = true
            order[i] = free
            unbound = {}
        end
    end
    if #unbound > 0 then
        return nil
    end
    return order
end

function Compose.Money(copper)
    copper = math.floor(tonumber(copper) or 0)
    if copper <= 0 then
        return nil
    end
    local gold = math.floor(copper / 10000)
    local silver = math.floor(copper / 100) % 100
    local rest = copper % 100
    local parts = {}
    if gold > 0 then
        parts[#parts + 1] = gold .. "g"
    end
    if silver > 0 then
        parts[#parts + 1] = silver .. "s"
    end
    if rest > 0 then
        parts[#parts + 1] = rest .. "c"
    end
    return table.concat(parts, " ")
end

function Compose.RewardsLine(rewards, voice)
    if type(rewards) ~= "table" then
        return nil
    end
    local list = {}
    if rewards.xp and rewards.xp > 0 then
        list[#list + 1] = rewards.xp .. " XP"
    end
    local money = Compose.Money(rewards.money)
    if money then
        list[#list + 1] = money
    end
    for _, name in ipairs(rewards.items or {}) do
        list[#list + 1] = name
    end
    if rewards.choices and #rewards.choices > 0 then
        list[#list + 1] = Voice.Format("rewards_choice", voice, { list = table.concat(rewards.choices, " / ") })
    end
    if #list == 0 then
        return nil
    end
    return Voice.Format("rewards", voice, { list = table.concat(list, ", ") })
end

local function groupLine(input, record, voice)
    if input.showGroup == false then
        return nil
    end
    local size = input.groupSize or 0
    if size <= 1 and not input.groupTag then
        return nil
    end
    if voice == "monke" and record and type(record.g) == "string" and record.g ~= "" then
        return record.g
    end
    if size > 2 then
        return Voice.Format("group", voice, { n = size, friends = size - 1 })
    elseif size == 2 then
        return Voice.Format("group_one", voice, { n = size, friends = 1 })
    end
    return Voice.Get("group_tag", voice)
end

-- input = {
--   record        MonkeDB entry or nil
--   objectives    C_QuestLog.GetQuestObjectives result, or nil
--   voice         "monke" | "plain"
--   showLore, showGroup   settings, default true
--   showProgress  true when the quest is in the log
--   groupSize, groupTag
--   rewards       { xp, money, items = {names}, choices = {names} } or nil
-- }
-- Returns { voice, group, lore, loreMissing, tasks = {...}, rewards }.
function Compose.Build(input)
    input = input or {}
    local voice = Voice.IsVoice(input.voice) and input.voice or Voice.DEFAULT
    local record = Compose.UsableRecord(input.record)
    local live = Rules.Visible(input.objectives)
    local out = { voice = voice, tasks = {} }

    out.group = groupLine(input, record, voice)

    if input.showLore ~= false then
        local lore
        if record then
            if voice == "plain" then
                lore = record.p or record.l
            else
                lore = record.l or record.p
            end
        end
        if lore and lore ~= "" then
            out.lore = lore
        else
            out.loreMissing = true
        end
    end

    local n = record and record.t and (record.n or 0) or 0
    local lines
    if voice == "monke" and record and record.t and n > 0 then
        if #live == 0 then
            -- Offered but not yet accepted, or not loaded yet: nothing to pair with, so the
            -- DB bullets stand on their own.
            lines = {}
            for i = 1, n do
                lines[i] = record.t[i]
            end
        elseif n == #live then
            local order = assign(record.t, n, live)
            if order then
                lines = {}
                for i = 1, n do
                    lines[i] = record.t[order[i]]
                end
            end
        end
    end
    if not lines then
        lines = Rules.BuildTasks(live, voice)
    end
    for i, line in ipairs(lines) do
        local progress = input.showProgress and live[i] and Rules.Progress(live[i], voice)
        if progress then
            line = stripFinalStop(line) .. " " .. progress
        end
        out.tasks[#out.tasks + 1] = line
    end
    out.numObjectiveTasks = #out.tasks -- the rest are hints and the turn-in line

    if voice == "monke" and record and record.t and #record.t > n then
        for i = n + 1, #record.t do
            out.tasks[#out.tasks + 1] = record.t[i]
        end
    else
        out.tasks[#out.tasks + 1] = Rules.TurnIn(record and record.e, voice, record and record.d == true)
    end

    out.rewards = Compose.RewardsLine(input.rewards, voice)
    return out
end

-- Text for the description slot: group warning, then lore. With no lore yet, say so and
-- keep Blizzard's own text underneath so the player loses nothing.
function Compose.DescriptionText(sections, originalText)
    local parts = {}
    if sections.group then
        parts[#parts + 1] = Compose.GROUP_COLOR .. sections.group .. "|r"
    end
    if sections.lore then
        parts[#parts + 1] = sections.lore
    elseif sections.loreMissing then
        parts[#parts + 1] = Voice.Get("no_lore", sections.voice)
        if originalText and originalText ~= "" then
            parts[#parts + 1] = originalText
        end
    end
    return table.concat(parts, "\n\n")
end

local function bullets(tasks)
    local lines = {}
    for i, task in ipairs(tasks) do
        lines[i] = Voice.BULLET .. task
    end
    return table.concat(lines, "\n")
end

-- Text for the objectives slot: bullets, then the rewards line.
function Compose.ObjectivesText(sections)
    local text = bullets(sections.tasks)
    if sections.rewards then
        text = text .. "\n\n" .. sections.rewards
    end
    return text
end

-- Text for the "are you done yet?" panel. The player is already standing at the NPC, so
-- only objective bullets are listed. Returns nil when there is nothing better to say than
-- Blizzard's own text.
function Compose.ProgressText(sections, isReady)
    if isReady then
        return Voice.Get("progress_ready", sections.voice)
    end
    local count = sections.numObjectiveTasks or 0
    if count == 0 then
        return nil
    end
    local todo = {}
    for i = 1, count do
        todo[i] = sections.tasks[i]
    end
    return Voice.Get("progress_todo", sections.voice) .. "\n\n" .. bullets(todo)
end

function Compose.CompleteText(sections)
    local text = Voice.Get("complete", sections.voice)
    if sections.rewards then
        text = text .. "\n\n" .. sections.rewards
    end
    return text
end
