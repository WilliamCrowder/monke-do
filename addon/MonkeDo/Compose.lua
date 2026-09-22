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
Compose.HEADER_COLOR = "|cffffd100" -- NORMAL_FONT_COLOR, Blizzard's gold: the log view's list header
Compose.DONE_COLOR = "|cff808080"   -- grey: objectives the game reports finished
Compose.HINT_COLOR = "|cff808080"   -- grey: the "long story? use the toggle" line

local function hex(r, g, b)
    local function byte(v)
        v = tonumber(v) or 0
        if v < 0 then
            v = 0
        elseif v > 1 then
            v = 1
        end
        return math.floor(v * 255 + 0.5)
    end
    return ("|cff%02x%02x%02x"):format(byte(r), byte(g), byte(b))
end

-- The colours above are defaults. On every redraw Blizzard recolours the quest frame's text
-- for the page it sits on (dark on parchment, light on stone and with Quest Text Contrast), so
-- gold or mid-grey text we add can end up nearly invisible. Display passes the frame's own
-- body and header colours ({r, g, b} each) and gets colours that stay readable on that page:
-- the header exactly like Blizzard's headers, and a grey and a red matched to light or dark text.
function Compose.Palette(body, header)
    local palette = { header = Compose.HEADER_COLOR, done = Compose.DONE_COLOR,
        hint = Compose.HINT_COLOR, group = Compose.GROUP_COLOR }
    if type(header) == "table" and type(header[1]) == "number" then
        palette.header = hex(header[1], header[2], header[3])
    end
    if type(body) == "table" and type(body[1]) == "number" then
        local light = 0.299 * body[1] + 0.587 * (body[2] or 0) + 0.114 * (body[3] or 0) > 0.5
        palette.done = light and "|cff9d9d9d" or "|cff4d4d4d"
        palette.hint = palette.done
        palette.group = light and "|cffff4040" or "|cffb01010"
    end
    return palette
end

local function colour(sections, key)
    local palette = sections and sections.palette
    return (type(palette) == "table" and palette[key]) or Compose[key:upper() .. "_COLOR"]
end
Compose.OPENING_CHARS = 160         -- the most of a description shown in place of missing lore
Compose.ELLIPSIS = "\226\128\166"   -- U+2026

local function stripFinalStop(s)
    return (s:gsub("[%.%s]+$", ""))
end

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- One line, runs of whitespace (paragraph breaks included) down to single spaces.
local function squash(s)
    return trim((s:gsub("%s+", " ")))
end

local function isStringList(value)
    if type(value) ~= "table" then
        return false
    end
    for i = 1, #value do
        if type(value[i]) ~= "string" then
            return false
        end
    end
    return true
end

-- A record from a newer schema, or a malformed one, is ignored rather than trusted. `tp` is
-- the exception: it only helps plain voice before a quest is accepted, so a malformed `tp`
-- costs the record that field and nothing else (the DB table itself is left untouched).
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
    if record.t ~= nil and not isStringList(record.t) then
        return nil
    end
    if record.n ~= nil then
        if type(record.n) ~= "number" or record.n < 0 or record.n > #(record.t or {}) then
            return nil
        end
    end
    if record.tp ~= nil and not isStringList(record.tp) then
        local copy = {}
        for key, value in pairs(record) do
            copy[key] = value
        end
        copy.tp = nil
        return copy
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

-- A voice template around a piece of the game's own text, with one final full stop: text
-- that brought its own "!" or "?" keeps it (Rules.lua does the same for objective lines).
local function sentenceLine(key, voice, text)
    text = stripFinalStop(text)
    local line = Voice.Format(key, voice, { text = text })
    if text:find("[!?]$") then
        line = (line:gsub("%.$", ""))
    end
    return line
end

-- input = {
--   record        MonkeDB entry or nil
--   objectives    C_QuestLog.GetQuestObjectives result, or nil
--   voice         "monke" | "plain"
--   showLore, showGroup   settings, default true
--   showProgress  true when the quest is in the log
--   groupSize, groupTag
--   rewards       { xp, money, items = {names}, choices = {names} } or nil
--   waypoint      C_QuestLog.GetNextWaypointText, or nil (the log views pass it)
-- }
-- Returns { voice, group, lore, loreMissing, tasks = {...}, numObjectiveTasks, finished,
-- waypoint, rewards }. Everything is plain text: colours are added by the *Text functions
-- below, so other readers of `tasks` (the Now line) get clean strings.
-- finished[i] is true when tasks[i] is an objective the game reports finished.
function Compose.Build(input)
    input = input or {}
    local voice = Voice.IsVoice(input.voice) and input.voice or Voice.DEFAULT
    local record = Compose.UsableRecord(input.record)
    local live = Rules.Visible(input.objectives)
    local out = { voice = voice, tasks = {}, finished = {}, palette = input.palette }

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
    if n > 0 then
        if #live == 0 then
            -- Offered but not yet accepted, or not loaded yet: nothing to pair with, so the
            -- DB bullets stand on their own. Plain voice has its own copy in `tp`.
            local source = record.t
            if voice == "plain" then
                source = record.tp
            end
            if source and #source >= n then
                lines = {}
                for i = 1, n do
                    lines[i] = source[i]
                end
            end
        elseif voice == "monke" and n == #live then
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
        local objective = input.showProgress and live[i]
        local progress = objective and Rules.Progress(objective, voice)
        if progress then
            line = stripFinalStop(line) .. " " .. progress
        end
        out.tasks[#out.tasks + 1] = line
        if objective and objective.finished then
            out.finished[i] = true
        end
    end
    out.numObjectiveTasks = #out.tasks -- the rest are hints and the turn-in line

    if type(input.waypoint) == "string" and trim(input.waypoint) ~= "" then
        out.waypoint = sentenceLine("waypoint", voice, trim(input.waypoint))
    end

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

-- Byte length of the first `count` UTF-8 characters of s (all of s when it is shorter), so a
-- cut never splits a character.
local function charsToBytes(s, count)
    local seen = 0
    for i = 1, #s do
        local byte = s:byte(i)
        if byte < 128 or byte >= 192 then -- the first byte of a character
            if seen == count then
                return i - 1
            end
            seen = seen + 1
        end
    end
    return #s
end

-- Where each sentence ends (the byte index of its last character): ".", "!" or "?", any
-- closing quotes or brackets, then a space or the end of the text.
local function sentenceEnds(text)
    local ends = {}
    local from = 1
    while true do
        local _, last = text:find("[%.!?]+[\"'%)%]]*", from)
        if not last then
            return ends
        end
        local after = text:sub(last + 1, last + 1)
        if after == "" or after == " " then
            ends[#ends + 1] = last
        end
        from = last + 1
    end
end

-- The start of a long text, on one line: its first sentence or two when they end within
-- `limit` characters, else the words that fit and "…". Never more than `limit` characters.
function Compose.Opening(text, limit)
    limit = limit or Compose.OPENING_CHARS
    if type(text) ~= "string" then
        return ""
    end
    text = squash(text)
    local fits = charsToBytes(text, limit)
    local cut
    for count, last in ipairs(sentenceEnds(text)) do
        if last > fits then
            break
        end
        cut = last
        if count == 2 then
            break
        end
    end
    if cut then
        return text:sub(1, cut)
    end
    if fits >= #text then
        return text
    end
    local room = charsToBytes(text, limit - 1) -- one character is left for the ellipsis
    local head = text:sub(1, room)
    if text:sub(room + 1, room + 1) ~= " " then
        local space = head:match("^.*() ") -- the last space: drop the word it would split
        if space then
            head = head:sub(1, space - 1)
        end
    end
    head = (head:gsub("[%s,;:%-]+$", ""))
    if head == "" then
        head = text:sub(1, room)
    end
    return head .. Compose.ELLIPSIS
end

-- What the description slot shows for a quest with no lore yet: Blizzard's own short
-- objectives sentence, or for a talk quest that has none, the opening of the description.
-- When that leaves some of Blizzard's story unseen, a grey line points at the toggle.
-- The whole long description is exactly what this addon is for, so it never comes back here.
function Compose.LoreStandIn(voice, description, sentence, palette)
    local full = type(description) == "string" and squash(description) or ""
    local text = type(sentence) == "string" and trim(sentence) or ""
    if text == "" then
        text = Compose.Opening(full)
    end
    if text == "" then
        return nil
    end
    if full ~= "" and squash(text) ~= full then
        local hint = Voice.Format("toggle_hint", voice, { button = Voice.Get("toggle_to_original", voice) })
        text = text .. "\n" .. colour({ palette = palette }, "hint") .. hint .. "|r"
    end
    return text
end

-- Text for the description slot: group warning, then lore, or with no lore yet the stand-in
-- built from Blizzard's own text. `originalText` is Blizzard's description and
-- `objectivesText` Blizzard's objectives sentence, as the game wrote them.
function Compose.DescriptionText(sections, originalText, objectivesText)
    local parts = {}
    if sections.group then
        parts[#parts + 1] = colour(sections, "group") .. sections.group .. "|r"
    end
    if sections.lore then
        parts[#parts + 1] = sections.lore
    elseif sections.loreMissing then
        parts[#parts + 1] = Compose.LoreStandIn(sections.voice, originalText, objectivesText, sections.palette)
    end
    return table.concat(parts, "\n\n")
end

-- One bullet per task, tasks[1..last] (all of them by default), finished objectives grey.
local function bullets(sections, last)
    local finished = sections.finished or {}
    local done = colour(sections, "done")
    local lines = {}
    for i = 1, last or #sections.tasks do
        local line = Voice.BULLET .. sections.tasks[i]
        if finished[i] then
            line = done .. line .. "|r"
        end
        lines[i] = line
    end
    return table.concat(lines, "\n")
end

-- Text for the objectives slot on the quest giver page: bullets, then the rewards line. The
-- page's own "Quest Objectives" header above it is relabelled by Display.
function Compose.ObjectivesText(sections)
    local text = bullets(sections)
    if sections.rewards then
        text = text .. "\n\n" .. sections.rewards
    end
    return text
end

-- Text for the objectives slot in the quest log and the map's quest details, where it is the
-- one task list: a header line, the game's "which way" line when it has one, the bullets. No
-- rewards line: both views draw their own rewards panel.
function Compose.LogObjectivesText(sections)
    local lines = { colour(sections, "header") .. Voice.Get("tasks_header", sections.voice) .. "|r" }
    if sections.waypoint then
        lines[#lines + 1] = Voice.BULLET .. sections.waypoint
    end
    lines[#lines + 1] = bullets(sections)
    return table.concat(lines, "\n")
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
    return Voice.Get("progress_todo", sections.voice) .. "\n\n" .. bullets(sections, count)
end

function Compose.CompleteText(sections)
    local text = Voice.Get("complete", sections.voice)
    if sections.rewards then
        text = text .. "\n\n" .. sections.rewards
    end
    return text
end
