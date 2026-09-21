-- Tracker.lua: the same short wording in the objective tracker.
-- The tracker lays its lines out before this hook runs, so a rewritten line is kept only
-- when it is no taller than Blizzard's. Anything unexpected means "leave it alone".

local _, ns = ...

local Core = ns.Core
local Rules = ns.Rules

local Tracker = {}
ns.Tracker = Tracker

local enabled = false
local MODULES = { "QuestObjectiveTracker", "CampaignQuestObjectiveTracker" }

local function active()
    return enabled and Core.Get("tracker") and not ns.state.showOriginal
end

-- Rewrite one tracker line. Returns true when the new text was kept.
function Tracker.RewriteLine(line, objective, voice)
    local text = line and line.Text
    if not (text and text.GetText and text.SetText and objective) then
        return false
    end
    local old = text:GetText()
    if not old or old == "" then
        return false
    end
    local new = Rules.Line(objective, voice)
    local progress = Rules.Progress(objective, voice)
    if progress then
        new = new:gsub("[%.%s]+$", "") .. " " .. progress
    end
    if new == old then
        return true
    end
    local before = text.GetStringHeight and text:GetStringHeight() or 0
    text:SetText(new)
    local after = text.GetStringHeight and text:GetStringHeight() or 0
    if after > before + 0.5 then
        text:SetText(old) -- would wrap onto a line the layout did not leave room for
        return false
    end
    return true
end

function Tracker.ApplyToBlock(block, questID)
    if not (block and type(block.usedLines) == "table") then
        return
    end
    if not (C_QuestLog and C_QuestLog.GetQuestObjectives) then
        return
    end
    local objectives = C_QuestLog.GetQuestObjectives(questID)
    if type(objectives) ~= "table" then
        return
    end
    local voice = Core.Get("voice")
    for index, objective in ipairs(objectives) do
        local line = block.usedLines[index]
        if line and objective.text and objective.text ~= "" and not objective.finished then
            Tracker.RewriteLine(line, objective, voice)
        end
    end
end

local function onUpdateSingle(module, quest)
    if not active() then
        return
    end
    local questID = quest and quest.GetID and quest:GetID()
    if not questID or not module.GetExistingBlock then
        return
    end
    Tracker.ApplyToBlock(module:GetExistingBlock(questID), questID)
end

function Tracker.MarkDirty()
    for _, name in ipairs(MODULES) do
        local module = _G[name]
        if module and module.MarkDirty then
            module:MarkDirty()
        end
    end
end

function Tracker.Enable()
    if enabled then
        return
    end
    enabled = true
    if not hooksecurefunc then
        return
    end
    for _, name in ipairs(MODULES) do
        local module = _G[name]
        if module and type(module.UpdateSingle) == "function" then
            hooksecurefunc(module, "UpdateSingle", onUpdateSingle)
        end
    end
    Core.OnChange(Tracker.MarkDirty)
end
