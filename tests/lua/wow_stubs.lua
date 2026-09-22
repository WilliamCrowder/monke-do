-- wow_stubs.lua: a fake WoW client, just big enough to load the addon outside the game.
-- busted loads this as its helper (see .busted); run_specs.py loads it the same way.
-- Run from the repo root.
--
-- WowStubs.reset()         fresh fake client, returns nothing
-- WowStubs.load()          loads the addon's Lua files in TOC order, returns its namespace
-- WowStubs.quest           the quest the fake API describes (see defaultQuest)
-- WowStubs.fire(event,...) delivers an event to every frame registered for it
-- WowStubs.showQuest(kind) plays Blizzard's part: "detail", "log", "reward" or "progress"

WowStubs = {}

local ADDON = "MonkeDo"
local ADDON_DIR = "addon/MonkeDo/"
local realPrint = print

local function fileExists(path)
    local handle = io.open(path, "r")
    if handle then
        handle:close()
        return true
    end
    return false
end

local function tocFiles()
    local files = {}
    for line in io.lines(ADDON_DIR .. ADDON .. ".toc") do
        line = line:gsub("\r", ""):gsub("^%s+", ""):gsub("%s+$", "")
        if line ~= "" and line:sub(1, 1) ~= "#" and line:match("%.lua$") then
            files[#files + 1] = (line:gsub("\\", "/"))
        end
    end
    return files
end

-- Widgets ------------------------------------------------------------------------------

local function newFontString(text)
    local fs = { text = text, shown = true }
    function fs:GetText()
        if self.text == "" then
            return nil -- the real client answers nil for an empty string
        end
        return self.text
    end
    function fs:SetText(value)
        self.text = value
        self.setCount = (self.setCount or 0) + 1
    end
    function fs:IsShown()
        return self.shown
    end
    function fs:Show()
        self.shown = true
    end
    function fs:Hide()
        self.shown = false
    end
    -- 10 px per line, wrapping every 40 characters: enough to test "did it get taller".
    function fs:GetStringHeight()
        local height = 0
        for line in ((self.text or "") .. "\n"):gmatch("(.-)\n") do
            height = height + 10 * math.max(1, math.ceil(#line / 40))
        end
        return height
    end
    return fs
end
WowStubs.newFontString = newFontString

local function newFrame(frameType, name, parent, template)
    local frame = {
        frameType = frameType, name = name, parent = parent, template = template,
        events = {}, scripts = {}, hooks = {}, shown = false, text = nil,
    }
    function frame:RegisterEvent(event)
        self.events[event] = true
    end
    function frame:SetScript(kind, fn)
        self.scripts[kind] = fn
    end
    function frame:GetScript(kind)
        return self.scripts[kind]
    end
    function frame:HookScript(kind, fn)
        self.hooks[kind] = self.hooks[kind] or {}
        table.insert(self.hooks[kind], fn)
    end
    function frame:RunScript(kind, ...)
        if self.scripts[kind] then
            self.scripts[kind](self, ...)
        end
        for _, fn in ipairs(self.hooks[kind] or {}) do
            fn(self, ...)
        end
    end
    function frame:Show()
        self.shown = true
        self:RunScript("OnShow")
    end
    function frame:Hide()
        self.shown = false
    end
    function frame:IsShown()
        return self.shown
    end
    function frame:SetSize() end
    function frame:SetPoint(...)
        self.point = { ... }
    end
    function frame:SetFrameLevel() end
    function frame:GetFrameLevel()
        return 1
    end
    function frame:SetText(value)
        self.text = value
    end
    function frame:GetText()
        return self.text
    end
    function frame:CreateTexture()
        local texture = {}
        function texture:SetSize() end
        function texture:SetPoint() end
        function texture:SetTexture(path)
            self.path = path
        end
        return texture
    end
    function frame:UpdateScrollChildRect()
        self.scrollUpdates = (self.scrollUpdates or 0) + 1
    end
    table.insert(WowStubs.frames, frame)
    return frame
end

-- The fake quest -----------------------------------------------------------------------

local function defaultQuest()
    return {
        id = 214,
        description = "The Defias wear red bandanas. Bring me 10 of them, $n.",
        objectivesText = "Scout Riell at the Sentinel Hill Tower wants you to bring her 10 Red Silk Bandanas.",
        progressText = "Do you have the bandanas?",
        rewardText = "Well done. Westfall is safer.",
        objectives = {
            { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
        },
        onQuest = true,
        groupSize = 0,
        tag = nil,
        xp = 875,
        money = 400,
        items = {},
        choices = {},
        completable = false,
    }
end

-- Globals the addon defines or the fake client provides, so reset can clear them.
local OWNED = {
    "MonkeDB", "MonkeDB_Meta", "MonkeDoDB", "MonkeDo_OnAddonCompartmentClick",
    "SLASH_MONKEDO1", "SLASH_MONKEDO2", "SlashCmdList",
    "CreateFrame", "hooksecurefunc", "GameTooltip", "LibStub", "Settings", "C_AddOns", "C_QuestLog",
    "GetQuestID", "GetSuggestedGroupSize", "IsQuestCompletable",
    "GetRewardXP", "GetRewardMoney", "GetNumQuestRewards", "GetNumQuestChoices", "GetQuestItemInfo",
    "GetQuestLogRewardXP", "GetQuestLogRewardMoney", "GetNumQuestLogRewards", "GetQuestLogRewardInfo",
    "GetNumQuestLogChoices", "GetQuestLogChoiceInfo",
    "QuestFrame", "QuestFrameProgressPanel", "QuestInfoFrame", "QuestInfo_Display",
    "QuestInfoDescriptionText", "QuestInfoObjectivesText", "QuestInfoRewardText", "QuestProgressText",
    "QuestMapFrame", "QuestDetailScrollFrame", "QuestObjectiveTracker", "CampaignQuestObjectiveTracker",
}

function WowStubs.reset()
    for _, name in ipairs(OWNED) do
        _G[name] = nil
    end
    WowStubs.frames = {}
    WowStubs.printed = {}
    WowStubs.loadedAddons = {}
    WowStubs.openedCategory = nil
    WowStubs.quest = defaultQuest()

    print = function(...)
        local parts = {}
        for i = 1, select("#", ...) do
            parts[i] = tostring((select(i, ...)))
        end
        table.insert(WowStubs.printed, table.concat(parts, " "))
    end

    SlashCmdList = {}
    CreateFrame = newFrame
    GameTooltip = { SetOwner = function() end, SetText = function() end, Show = function() end, Hide = function() end }

    -- Same contract as the real one: the hook runs after the original, return values are
    -- the original's, and a function captured before the hook was installed never sees it.
    hooksecurefunc = function(a, b, c)
        local tbl, key, hook = _G, a, b
        if type(a) == "table" then
            tbl, key, hook = a, b, c
        end
        local original = tbl[key]
        assert(type(original) == "function", "hooksecurefunc: no function named " .. tostring(key))
        tbl[key] = function(...)
            local results = { original(...) }
            hook(...)
            return unpack(results)
        end
    end

    C_AddOns = {
        GetAddOnMetadata = function(_, field)
            return field == "Version" and "1.2.3" or nil
        end,
        IsAddOnLoaded = function(name)
            return WowStubs.loadedAddons[name] or false
        end,
    }

    C_QuestLog = {
        GetQuestObjectives = function(questID)
            return questID == WowStubs.quest.id and WowStubs.quest.objectives or {}
        end,
        GetSelectedQuest = function()
            return WowStubs.quest.id
        end,
        IsOnQuest = function(questID)
            return questID == WowStubs.quest.id and WowStubs.quest.onQuest
        end,
        GetSuggestedGroupSize = function()
            return WowStubs.quest.groupSize
        end,
        GetQuestTagInfo = function()
            return WowStubs.quest.tag
        end,
    }
    GetQuestID = function()
        return WowStubs.quest.id
    end
    GetSuggestedGroupSize = function()
        return WowStubs.quest.groupSize
    end
    IsQuestCompletable = function()
        return WowStubs.quest.completable
    end
    GetRewardXP = function()
        return WowStubs.quest.xp
    end
    GetRewardMoney = function()
        return WowStubs.quest.money
    end
    GetNumQuestRewards = function()
        return #WowStubs.quest.items
    end
    GetNumQuestChoices = function()
        return #WowStubs.quest.choices
    end
    GetQuestItemInfo = function(kind, index)
        local list = kind == "choice" and WowStubs.quest.choices or WowStubs.quest.items
        return list[index]
    end
    GetQuestLogRewardXP = GetRewardXP
    GetQuestLogRewardMoney = GetRewardMoney
    GetNumQuestLogRewards = GetNumQuestRewards
    GetQuestLogRewardInfo = function(index)
        return WowStubs.quest.items[index]
    end
    GetNumQuestLogChoices = GetNumQuestChoices
    GetQuestLogChoiceInfo = function(index)
        return WowStubs.quest.choices[index]
    end

    QuestFrame = newFrame("Frame", "QuestFrame")
    QuestFrameProgressPanel = newFrame("Frame", "QuestFrameProgressPanel")
    QuestDetailScrollFrame = newFrame("ScrollFrame", "QuestDetailScrollFrame")
    QuestDetailScrollFrame.shown = true
    QuestMapFrame = { DetailsFrame = newFrame("Frame", "QuestMapDetails") }
    QuestInfoFrame = { questLog = false }
    QuestInfoDescriptionText = newFontString(nil)
    QuestInfoObjectivesText = newFontString(nil)
    QuestInfoRewardText = newFontString(nil)
    QuestProgressText = newFontString(nil)
    for _, fs in ipairs({ QuestInfoDescriptionText, QuestInfoObjectivesText, QuestInfoRewardText, QuestProgressText }) do
        fs:Hide()
    end

    -- Blizzard's part: write the server's strings into the shared fontstrings.
    QuestInfo_Display = function(template)
        local quest = WowStubs.quest
        QuestInfoFrame.questLog = template.questLog
        QuestInfoDescriptionText:Hide()
        QuestInfoObjectivesText:Hide()
        QuestInfoRewardText:Hide()
        if template.reward then
            QuestInfoRewardText:SetText(quest.rewardText)
            QuestInfoRewardText:Show()
        else
            QuestInfoDescriptionText:SetText(quest.description)
            QuestInfoDescriptionText:Show()
            QuestInfoObjectivesText:SetText(quest.objectivesText)
            QuestInfoObjectivesText:Show()
        end
    end
end

function WowStubs.showQuest(kind)
    if kind == "progress" then
        QuestProgressText:SetText(WowStubs.quest.progressText)
        QuestProgressText:Show()
        QuestFrameProgressPanel:Show()
        return
    end
    QuestInfo_Display({ questLog = (kind == "log"), reward = (kind == "reward") })
end

function WowStubs.fire(event, ...)
    for _, frame in ipairs(WowStubs.frames) do
        if frame.events[event] and frame.scripts.OnEvent then
            frame.scripts.OnEvent(frame, event, ...)
        end
    end
end

-- A Settings API that accepts what Core.lua sends and remembers the essentials.
function WowStubs.installSettings()
    Settings = {
        RegisterVerticalLayoutCategory = function(name)
            return { name = name, GetID = function() return 42 end }
        end,
        RegisterAddOnSetting = function(_, variable, key, tbl, varType, label, default)
            assert(type(tbl) == "table" and type(key) == "string" and type(varType) == "string")
            assert(variable and label and default ~= nil)
            return { SetValueChangedCallback = function(self, fn) self.callback = fn end }
        end,
        CreateControlTextContainer = function()
            local data = {}
            return {
                Add = function(_, value, label) data[#data + 1] = { value = value, label = label } end,
                GetData = function() return data end,
            }
        end,
        CreateDropdown = function(_, _, options) assert(#options() == 2) end,
        CreateCheckbox = function() end,
        RegisterAddOnCategory = function() end,
        OpenToCategory = function(id) WowStubs.openedCategory = id end,
    }
end

-- Load the addon like the client does: TOC order, (addonName, namespace) as varargs.
-- Library and generated data files that are not on disk are skipped, as the client skips them.
function WowStubs.load(options)
    options = options or {}
    local ns = {}
    for _, relative in ipairs(tocFiles()) do
        local isData = relative:match("^Data/") ~= nil
        local path = ADDON_DIR .. relative
        if fileExists(path) and not (isData and not options.withData) then
            local chunk = assert(loadfile(path))
            chunk(ADDON, ns)
        end
    end
    return ns
end

-- Log in: what the client does after loading the files.
function WowStubs.login()
    WowStubs.fire("ADDON_LOADED", ADDON)
    WowStubs.fire("PLAYER_LOGIN")
end

-- Run fn while recording every global that is read while nil. The spec compares the list
-- with .luacheckrc so a typo in a WoW global fails here and not in the game.
function WowStubs.trackGlobals(fn)
    local seen = {}
    local old = getmetatable(_G)
    setmetatable(_G, {
        __index = function(_, key)
            seen[key] = true
            if old and old.__index then
                if type(old.__index) == "function" then
                    return old.__index(_G, key)
                end
                return old.__index[key]
            end
            return nil
        end,
        __newindex = old and old.__newindex or nil,
    })
    local ok, err = pcall(fn)
    setmetatable(_G, old)
    if not ok then
        error(err, 2)
    end
    return seen
end

-- The names .luacheckrc allows the addon to read or write.
function WowStubs.declaredGlobals()
    local env = { files = {} }
    local chunk = assert(loadfile(".luacheckrc"))
    setfenv(chunk, env)
    chunk()
    local declared = {}
    for _, list in ipairs({ env.globals or {}, env.read_globals or {} }) do
        for _, name in ipairs(list) do
            declared[name] = true
        end
    end
    return declared
end

WowStubs.realPrint = realPrint
WowStubs.reset()
