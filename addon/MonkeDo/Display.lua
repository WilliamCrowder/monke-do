-- Display.lua: quest frame hooks. Kept thin on purpose: read the API, call Compose, set
-- text. This is the one file CI cannot exercise, so every frame access is guarded and a
-- missing global means "do nothing", never an error.
--
-- Why QuestInfo_Display and not QuestInfo_ShowDescriptionText: the quest templates store
-- direct references to the QuestInfo_Show* functions, so hooksecurefunc on those globals
-- never fires from the quest frame. QuestInfo_Display is looked up by name on every call.

local _, ns = ...

local Core = ns.Core
local Compose = ns.Compose
local Voice = ns.Voice

local Display = {}
ns.Display = Display

local enabled = false
local buttons = {}

local MEDIA = "Interface\\AddOns\\MonkeDo\\Media\\"
local ICON_TO_ORIGINAL = MEDIA .. "toggle.png"    -- Wrinkle Brain: click for Blizzard's text
local ICON_TO_MONKE = MEDIA .. "toggle_monke.png" -- fist and club: click for Monke Do text

-- Quest tags that mean "bring friends" (Enum.QuestTag values; stable since Legion).
local GROUP_TAGS = { [1] = true, [62] = true, [81] = true, [88] = true, [89] = true }

local function currentQuestID()
    local info = QuestInfoFrame
    if info and info.questLog and C_QuestLog and C_QuestLog.GetSelectedQuest then
        return C_QuestLog.GetSelectedQuest(), true
    end
    if GetQuestID then
        return GetQuestID(), false
    end
    return nil, false
end

local function isOnQuest(questID)
    if C_QuestLog and C_QuestLog.IsOnQuest then
        return C_QuestLog.IsOnQuest(questID) and true or false
    end
    return false
end

local function groupInfo(questID, fromLog)
    local size = 0
    if fromLog and C_QuestLog and C_QuestLog.GetSuggestedGroupSize then
        size = C_QuestLog.GetSuggestedGroupSize(questID) or 0
    elseif GetSuggestedGroupSize then
        size = GetSuggestedGroupSize() or 0
    end
    local tagged = false
    if C_QuestLog and C_QuestLog.GetQuestTagInfo then
        local tag = C_QuestLog.GetQuestTagInfo(questID)
        if type(tag) == "table" then
            tagged = (tag.isElite and true) or GROUP_TAGS[tag.tagID] or false
        end
    end
    return size, tagged
end

local function questGiverRewards()
    local rewards = { items = {}, choices = {} }
    rewards.xp = GetRewardXP and GetRewardXP() or 0
    rewards.money = GetRewardMoney and GetRewardMoney() or 0
    if GetQuestItemInfo then
        for i = 1, (GetNumQuestRewards and GetNumQuestRewards() or 0) do
            local name = GetQuestItemInfo("reward", i)
            if name and name ~= "" then
                rewards.items[#rewards.items + 1] = name
            end
        end
        for i = 1, (GetNumQuestChoices and GetNumQuestChoices() or 0) do
            local name = GetQuestItemInfo("choice", i)
            if name and name ~= "" then
                rewards.choices[#rewards.choices + 1] = name
            end
        end
    end
    return rewards
end

local function questLogRewards(questID)
    local rewards = { items = {}, choices = {} }
    rewards.xp = GetQuestLogRewardXP and GetQuestLogRewardXP(questID) or 0
    rewards.money = GetQuestLogRewardMoney and GetQuestLogRewardMoney(questID) or 0
    if GetQuestLogRewardInfo then
        for i = 1, (GetNumQuestLogRewards and GetNumQuestLogRewards(questID) or 0) do
            local name = GetQuestLogRewardInfo(i, questID)
            if name and name ~= "" then
                rewards.items[#rewards.items + 1] = name
            end
        end
    end
    if GetQuestLogChoiceInfo then
        for i = 1, (GetNumQuestLogChoices and GetNumQuestLogChoices(questID) or 0) do
            local name = GetQuestLogChoiceInfo(i, questID)
            if name and name ~= "" then
                rewards.choices[#rewards.choices + 1] = name
            end
        end
    end
    return rewards
end

-- The "which way" line Blizzard puts at the top of its objective list (a boat, a portal).
-- MayReturnNothing in Blizzard's documentation.
local function waypointText(questID)
    if C_QuestLog and C_QuestLog.GetNextWaypointText then
        local text = C_QuestLog.GetNextWaypointText(questID)
        if type(text) == "string" and text ~= "" then
            return text
        end
    end
    return nil
end

-- Everything Compose needs for one quest.
local function textColour(fontString)
    if fontString and fontString.GetTextColor then
        local r, g, b = fontString:GetTextColor()
        if type(r) == "number" and type(g) == "number" and type(b) == "number" then
            return { r, g, b }
        end
    end
    return nil
end

-- Blizzard colours the quest frame's body text and headers for the page material and the
-- Quest Text Contrast option before it lays the page out, so by the time our hook runs these
-- are the colours of the page on screen.
local function framePalette()
    return Compose.Palette(textColour(QuestInfoObjectivesText), textColour(QuestInfoDescriptionHeader))
end

function Display.BuildSections(questID, fromLog)
    local objectives
    if C_QuestLog and C_QuestLog.GetQuestObjectives then
        objectives = C_QuestLog.GetQuestObjectives(questID)
    end
    local size, tagged = groupInfo(questID, fromLog)
    return Compose.Build({
        palette = framePalette(),
        record = Core.GetRecord(questID),
        objectives = objectives,
        voice = Core.Get("voice"),
        showLore = Core.Get("showLore"),
        showGroup = Core.Get("groupWarning"),
        showProgress = isOnQuest(questID),
        groupSize = size,
        groupTag = tagged,
        rewards = fromLog and questLogRewards(questID) or questGiverRewards(),
        waypoint = fromLog and waypointText(questID) or nil,
    })
end

-- True when Blizzard wrote the fontstring's text after our last swap (or we never swapped
-- it). GetText() answers nil for an empty string on the real client, so `current` is always
-- a string ("" for empty) and everything is compared as strings.
local function isFresh(fontString, current)
    return fontString.monkeText == nil or current ~= fontString.monkeText
end

-- Blizzard's text for a fontstring: what it shows now, unless that is our own text, in which
-- case the string swap() remembered. Safe to call before swap() and on every redraw.
local function blizzardText(fontString)
    if not (fontString and fontString.GetText) then
        return ""
    end
    local current = fontString:GetText() or ""
    if isFresh(fontString, current) then
        return current
    end
    return fontString.monkeOriginal or ""
end

-- Swap a fontstring's text, remembering Blizzard's string so the toggle can put it back
-- byte for byte without asking the server again. newText nil (or the original-text toggle)
-- puts Blizzard's string back when we had changed it, and otherwise leaves it alone.
local function swap(fontString, newText)
    if not (fontString and fontString.GetText and fontString.SetText) then
        return
    end
    local current = fontString:GetText() or ""
    if isFresh(fontString, current) then
        fontString.monkeOriginal = current -- Blizzard wrote a fresh string since our last swap
    end
    if ns.state.showOriginal or newText == nil then
        if fontString.monkeText ~= nil and current ~= fontString.monkeOriginal then
            fontString:SetText(fontString.monkeOriginal)
        end
        fontString.monkeText = nil
        return
    end
    fontString.monkeText = newText
    fontString:SetText(newText)
end

local function refreshScroll()
    for _, name in ipairs({ "QuestDetailScrollFrame", "QuestProgressScrollFrame", "QuestRewardScrollFrame" }) do
        local scroll = _G[name]
        if scroll and scroll.IsShown and scroll:IsShown() and scroll.UpdateScrollChildRect then
            scroll:UpdateScrollChildRect()
        end
    end
end

local function shown(widget)
    return widget and widget.IsShown and widget:IsShown()
end

-- The quest giver page fades its description in (QuestFrameDetailPanel_OnUpdate moves an alpha
-- gradient 70 characters a second). QuestInfo_Display runs before the fade starts, so the fade
-- plays over our text. Blizzard never clears the gradient when the fade ends, though, so a longer
-- text put into the same fontstring later (the toggle, or the map's quest details) would stay
-- cut off where the fade stopped. With no fade running, show all of it, as Instant Quest Text does.
local function revealAll(fontString)
    local panel = QuestFrameDetailPanel
    if (panel and panel.fading) or not (fontString and fontString.SetAlphaGradient) then
        return -- a running fade reaches the end of whatever text is there by itself
    end
    local text = fontString:GetText() or ""
    fontString:SetAlphaGradient(#text + 1024, QUEST_DESCRIPTION_GRADIENT_LENGTH or 30)
end

-- Runs after every QuestInfo_Display: quest giver detail and reward pages, the map quest
-- details and the quest log popup all come through here.
--
-- Quest giver page: lore in the description slot; "Quest Objectives" relabelled to the tasks
-- header; bullets and the rewards line in the objectives slot.
-- Log views (quest log popup, map details; QuestInfoFrame.questLog): the objectives slot is
-- the one task list, header line first; Blizzard's own objective list under it is emptied
-- line by line; the lore sits under Blizzard's "Description" header.
function Display.ApplyQuestInfo()
    if not enabled then
        return
    end
    local questID, fromLog = currentQuestID()
    if not questID or questID == 0 then
        return
    end
    local sections = Display.BuildSections(questID, fromLog)
    local logView = QuestInfoFrame and QuestInfoFrame.questLog and true or false

    -- Blizzard's objectives sentence stands in for missing lore, so read it before our
    -- bullets replace it (and from memory once they have).
    local sentence = ""
    if shown(QuestInfoObjectivesText) then
        sentence = blizzardText(QuestInfoObjectivesText)
    end
    local description = QuestInfoDescriptionText
    if shown(description) then
        swap(description, Compose.DescriptionText(sections, blizzardText(description), sentence))
        revealAll(description)
    end
    if shown(QuestInfoObjectivesText) then
        if logView then
            swap(QuestInfoObjectivesText, Compose.LogObjectivesText(sections))
        else
            swap(QuestInfoObjectivesText, Compose.ObjectivesText(sections))
        end
    end

    -- Blizzard never resets header text, so the header is swapped on every pass: relabelled
    -- for the quest giver page, put back everywhere else, and no view is left holding ours.
    local header
    if not logView then
        header = Voice.Get("tasks_header", sections.voice)
    end
    swap(QuestInfoObjectivesHeader, header)

    -- Blizzard's own objective list repeats ours in the log views. Empty each shown line
    -- rather than hide it: a hidden line keeps its place, and Blizzard shows the lines again
    -- on every redraw anyway. Any other view gets them back.
    local objectivesFrame = QuestInfoObjectivesFrame
    if objectivesFrame and type(objectivesFrame.Objectives) == "table" then
        for _, line in ipairs(objectivesFrame.Objectives) do
            if logView and shown(line) then
                if line.SetHeight then
                    line:SetHeight(0) -- as Blizzard does before reusing a line: no stale height
                end
                swap(line, "")
            else
                swap(line, nil)
            end
        end
    end

    if shown(QuestInfoRewardText) then
        swap(QuestInfoRewardText, Compose.CompleteText(sections))
    end
    refreshScroll()
    Display.UpdateButtons()
end

-- The "bring me 10 bandanas... got them yet?" page is not built by QuestInfo_Display.
function Display.ApplyProgress()
    if not enabled or not shown(QuestProgressText) then
        return
    end
    local questID = GetQuestID and GetQuestID()
    if not questID or questID == 0 then
        return
    end
    local sections = Display.BuildSections(questID, false)
    local ready = IsQuestCompletable and IsQuestCompletable() and true or false
    swap(QuestProgressText, Compose.ProgressText(sections, ready))
    refreshScroll()
    Display.UpdateButtons()
end

function Display.Refresh()
    if shown(QuestInfoDescriptionText) or shown(QuestInfoObjectivesText) or shown(QuestInfoRewardText) then
        Display.ApplyQuestInfo()
    end
    Display.ApplyProgress()
    Display.UpdateButtons()
end

function Display.UpdateButtons()
    local voice = Core.Get("voice")
    for _, button in ipairs(buttons) do
        if ns.state.showOriginal then
            button:SetText(Voice.Get("toggle_to_monke", voice))
            button.monkeTip = Voice.Get("toggle_tip_monke", voice)
            button.monkeIcon:SetTexture(ICON_TO_MONKE)
        else
            button:SetText(Voice.Get("toggle_to_original", voice))
            button.monkeTip = Voice.Get("toggle_tip_original", voice)
            button.monkeIcon:SetTexture(ICON_TO_ORIGINAL)
        end
    end
end

-- The Wrinkle Brain toggle: a small header button, one click back to Blizzard's text.
local function createToggle(parent, point, relativePoint, x, y)
    if not (parent and CreateFrame) then
        return nil
    end
    local button = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    button:SetSize(74, 20)
    button:SetPoint(point, parent, relativePoint, x, y)
    if button.SetFrameLevel and parent.GetFrameLevel then
        button:SetFrameLevel(parent:GetFrameLevel() + 10)
    end
    local icon = button:CreateTexture(nil, "OVERLAY")
    icon:SetSize(20, 20)
    icon:SetPoint("RIGHT", button, "LEFT", -2, 0)
    button.monkeIcon = icon -- UpdateButtons picks the texture for the current state
    button:SetScript("OnClick", function()
        Core.ToggleOriginal()
    end)
    button:SetScript("OnEnter", function(self)
        if GameTooltip and self.monkeTip then
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:SetText(self.monkeTip)
            GameTooltip:Show()
        end
    end)
    button:SetScript("OnLeave", function()
        if GameTooltip then
            GameTooltip:Hide()
        end
    end)
    buttons[#buttons + 1] = button
    return button
end

-- Immersion and Storyline replace the quest giver window with their own. Hooking their
-- widgets is an open question in the plan, so for now say what still works and carry on:
-- the quest log, map details and tracker are untouched by them.
local function replacementUI()
    if not (C_AddOns and C_AddOns.IsAddOnLoaded) then
        return nil
    end
    for _, name in ipairs({ "Immersion", "Storyline" }) do
        if C_AddOns.IsAddOnLoaded(name) then
            return name
        end
    end
    return nil
end

function Display.Enable()
    if enabled then
        return
    end
    enabled = true

    if hooksecurefunc and QuestInfo_Display then
        hooksecurefunc("QuestInfo_Display", function()
            Display.ApplyQuestInfo()
        end)
    end
    if QuestFrameProgressPanel and QuestFrameProgressPanel.HookScript then
        QuestFrameProgressPanel:HookScript("OnShow", function()
            Display.ApplyProgress()
        end)
    end

    createToggle(QuestFrame, "TOPRIGHT", "TOPRIGHT", -30, -30)
    local details = QuestMapFrame and QuestMapFrame.DetailsFrame
    createToggle(details, "TOPRIGHT", "TOPRIGHT", -8, 22)
    Display.UpdateButtons()

    Core.OnChange(Display.Refresh)

    local other = replacementUI()
    if other then
        Core.Print(other .. " is drawing the quest window, so Monke Do text shows in the quest log and tracker only.")
    end
end
