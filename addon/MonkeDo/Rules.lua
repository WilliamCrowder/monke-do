-- Rules.lua: turns live quest objectives into task bullets.
-- Input is the table C_QuestLog.GetQuestObjectives returns:
--   { text, type, finished, numFulfilled, numRequired }
-- Every quest gets bullets from here, even with no MonkeDB entry, and progress
-- counts always come from here because only the live API knows them.

local _, ns = ...

local Voice = ns.Voice

local Rules = {}
ns.Rules = Rules

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- Objective text arrives as "3/10 Red Silk Bandana" on Retail-style clients and as
-- "Red Silk Bandana: 3/10" on Classic-style ones, with " slain" added for kills.
-- Returns name, have, need. have and need are nil when the text holds no count.
function Rules.ParseObjectiveText(text)
    if type(text) ~= "string" then
        return "", nil, nil
    end
    text = trim(text)
    local have, need, name = text:match("^(%d+)%s*/%s*(%d+)%s+(.+)$")
    if not name then
        name, have, need = text:match("^(.-)%s*:%s*(%d+)%s*/%s*(%d+)$")
    end
    if not name then
        return text, nil, nil
    end
    name = trim(name)
    name = name:gsub("%s+slain$", "")
    return name, tonumber(have), tonumber(need)
end

local function stripFinalStop(s)
    return (s:gsub("[%.%s]+$", ""))
end

-- "Argent Dawn: Neutral / Friendly" -> "Argent Dawn", "Friendly"
local function parseReputation(text)
    local faction, rest = text:match("^(.-)%s*:%s*(.+)$")
    if not faction or faction == "" then
        return stripFinalStop(text), nil
    end
    local standing = rest:match("/%s*([^/]+)$") or rest
    standing = trim(standing)
    if standing == "" or standing:find("%d") then
        standing = nil
    end
    return faction, standing
end

local COUNTED = { monster = true, item = true, object = true }

-- One bullet, without progress.
function Rules.Line(objective, voice)
    local kind = objective.type
    local text = objective.text or ""
    if COUNTED[kind] then
        local name, _, need = Rules.ParseObjectiveText(text)
        need = objective.numRequired or need or 1
        name = stripFinalStop(name)
        if need > 1 then
            return Voice.Format(kind, voice, { n = need, name = name })
        end
        return Voice.Format(kind .. "_one", voice, { name = name })
    end
    if kind == "reputation" then
        local faction, standing = parseReputation(text)
        if standing then
            return Voice.Format("reputation", voice, { faction = faction, standing = standing })
        end
        return Voice.Format("reputation_unknown", voice, { faction = faction })
    end
    -- event, spell, log, player, progressbar and anything new: keep the game's words.
    local name = Rules.ParseObjectiveText(text)
    return Voice.Format("event", voice, { text = stripFinalStop(name) })
end

-- "(3/15)", "(45%)", "(done)" or nil. Reputation is left out: raw standing numbers
-- read as noise.
function Rules.Progress(objective, voice)
    if objective.type == "reputation" then
        return objective.finished and Voice.Get("done", voice) or nil
    end
    if objective.percent then
        return ("(%d%%)"):format(objective.percent)
    end
    local need = objective.numRequired
    local have = objective.numFulfilled
    if need == nil or have == nil then
        local _, parsedHave, parsedNeed = Rules.ParseObjectiveText(objective.text)
        have, need = have or parsedHave, need or parsedNeed
    end
    if need and need > 1 and have then
        if have > need then
            have = need
        end
        return ("(%d/%d)"):format(have, need)
    end
    if objective.finished then
        return Voice.Get("done", voice)
    end
    return nil
end

function Rules.TurnIn(npc, voice)
    if npc and npc ~= "" then
        return Voice.Format("turnin", voice, { npc = npc })
    end
    return Voice.Get("turnin_unknown", voice)
end

-- The API can return objectives with empty text (hidden or not yet loaded). Everything
-- downstream works on this filtered list so bullets and progress stay aligned.
function Rules.Visible(objectives)
    local visible = {}
    for _, objective in ipairs(objectives or {}) do
        if type(objective) == "table" and objective.text and objective.text ~= "" then
            visible[#visible + 1] = objective
        end
    end
    return visible
end

-- All objective bullets for a quest, in API order. No turn-in line; Compose adds it.
function Rules.BuildTasks(objectives, voice)
    local lines = {}
    for i, objective in ipairs(Rules.Visible(objectives)) do
        lines[i] = Rules.Line(objective, voice)
    end
    return lines
end
