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
-- Returns name, have, need, slain. have and need are nil when the text holds no count;
-- slain says whether the text was a kill line ("Kobold Vermin slain").
function Rules.ParseObjectiveText(text)
    if type(text) ~= "string" then
        return "", nil, nil, false
    end
    text = trim(text)
    local have, need, name = text:match("^(%d+)%s*/%s*(%d+)%s+(.+)$")
    if not name then
        name, have, need = text:match("^(.-)%s*:%s*(%d+)%s*/%s*(%d+)$")
    end
    if not name then
        name = text
    end
    local stripped, slain = trim(name):gsub("%s+[Ss]lain$", "")
    return stripped, tonumber(have), tonumber(need), slain > 0
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

-- Objective types whose numRequired is a count of things. For the others (reputation,
-- progress bars) the number is a threshold or a percentage.
Rules.COUNTED = { monster = true, item = true, object = true }

-- The game's own words, with one full stop. Text that brought its own "!" or "?" keeps it;
-- pipeline/rules.py builds the same string.
local function eventLine(text, voice)
    local line = Voice.Format("event", voice, { text = text })
    if text:find("[!?]$") then
        line = (line:gsub("%.$", ""))
    end
    return line
end

-- One bullet, without progress.
function Rules.Line(objective, voice)
    local kind = objective.type
    local text = objective.text or ""
    local name, _, parsedNeed, slain = Rules.ParseObjectiveText(text)
    name = stripFinalStop(name)
    if kind == "monster" and not slain then
        -- A credit objective with its own wording ("Find Mankrik's Wife", "Heal and fortify
        -- Sentinel Shaya"): the target is not something to kill.
        return eventLine(name, voice)
    end
    if Rules.COUNTED[kind] then
        local need = objective.numRequired or parsedNeed or 1
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
    return eventLine(name, voice)
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

-- `other` is true when the quest is handed in to someone the player was not sent back to
-- (a different NPC, or a mailbox): "Go see" rather than "Go back to".
function Rules.TurnIn(npc, voice, other)
    if npc and npc ~= "" then
        return Voice.Format(other and "turnin_other" or "turnin", voice, { npc = npc })
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
