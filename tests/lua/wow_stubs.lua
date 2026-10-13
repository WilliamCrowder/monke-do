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
    -- 6 px per character; colour codes take no room, as on the real client.
    function fs:GetStringWidth()
        local plain = (self.text or ""):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")
        local widest = 0
        for line in (plain .. "\n"):gmatch("(.-)\n") do
            widest = math.max(widest, 6 * #line)
        end
        return widest
    end
    fs.GetUnboundedStringWidth = fs.GetStringWidth -- the fake never cuts, so both agree
    function fs:SetTextColor(r, g, b, a)
        self.color = { r, g, b, a }
    end
    function fs:GetTextColor()
        return unpack(self.color or { 1, 1, 1, 1 })
    end
    function fs:SetPoint(...)
        self.point = { ... }
    end
    function fs:ClearAllPoints()
        self.point = nil
    end
    function fs:SetWidth(width)
        self.width = width
    end
    function fs:GetWidth()
        return self.width or 0
    end
    function fs:SetHeight(height)
        self.height = height
    end
    function fs:GetHeight()
        return self.height or self:GetStringHeight()
    end
    function fs:SetAlpha(alpha)
        self.alpha = alpha
    end
    function fs:GetAlpha()
        return self.alpha or 1
    end
    function fs:SetFontObject(font)
        self.font = font
    end
    function fs:SetFont() end
    function fs:SetJustifyH() end
    function fs:SetJustifyV() end
    function fs:SetWordWrap(wrap)
        self.wordWrap = wrap
    end
    function fs:SetMaxLines(lines)
        self.maxLines = lines
    end
    function fs:SetShadowOffset() end
    -- Characters before `start` are solid, the next `length` fade out, the rest are hidden.
    -- Answers whether `start` is still inside the text (Blizzard's fade stops when it is not).
    -- Whether SetText clears the gradient on the real client is not known; the fake keeps it,
    -- which is the worse case.
    function fs:SetAlphaGradient(start, length)
        self.gradient = { start, length }
        return start < #(self.text or "")
    end
    return fs
end
WowStubs.newFontString = newFontString

-- How many characters of a fontstring's text are not fully visible under its alpha gradient.
function WowStubs.hiddenCharacters(fontString)
    local text = fontString.text or ""
    if not fontString.gradient then
        return 0
    end
    return math.max(0, #text - math.floor(fontString.gradient[1]))
end

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
        function texture:SetSize(width, height)
            self.size = { width, height }
        end
        function texture:SetPoint() end
        function texture:SetAllPoints() end
        function texture:SetColorTexture(r, g, b, a)
            self.color = { r, g, b, a }
        end
        function texture:SetTexture(path)
            self.path = path
        end
        function texture:SetAlpha(alpha)
            self.alpha = alpha
        end
        function texture:SetRotation(radians)
            self.rotation = radians
        end
        texture.shown = true
        function texture:Show()
            self.shown = true
        end
        function texture:Hide()
            self.shown = false
        end
        function texture:IsShown()
            return self.shown
        end
        return texture
    end
    function frame:CreateFontString()
        local fs = newFontString(nil)
        fs.parent = self
        return fs
    end
    function frame:UpdateScrollChildRect()
        self.scrollUpdates = (self.scrollUpdates or 0) + 1
    end
    -- Geometry, mouse and movement: recorded, never simulated.
    function frame:ClearAllPoints()
        self.point = nil
    end
    function frame:GetPoint()
        if self.point then
            return unpack(self.point)
        end
    end
    function frame:SetWidth(width)
        self.width = width
    end
    function frame:SetHeight(height)
        self.height = height
    end
    function frame:GetWidth()
        return self.width or 0
    end
    function frame:GetHeight()
        return self.height or 0
    end
    -- Where a frame is on screen is not simulated: a spec sets `center` (and UIParent has one).
    function frame:GetCenter()
        if self.center then
            return self.center[1], self.center[2]
        end
    end
    function frame:GetBottom()
        return self.bottom
    end
    function frame:SetAlpha(alpha)
        self.alpha = alpha
    end
    function frame:GetAlpha()
        return self.alpha or 1
    end
    function frame:SetShown(show)
        if show then
            self:Show()
        else
            self:Hide()
        end
    end
    function frame:SetMovable(movable)
        self.movable = movable
    end
    function frame:IsMovable()
        return self.movable or false
    end
    function frame:EnableMouse(enable)
        self.mouse = enable
    end
    function frame:RegisterForDrag(...)
        self.dragButtons = { ... }
    end
    function frame:RegisterForClicks(...)
        self.clickButtons = { ... }
    end
    function frame:SetClampedToScreen(clamped)
        self.clamped = clamped
    end
    function frame:StartMoving()
        self.moving = true
    end
    function frame:StopMovingOrSizing()
        self.moving = false
    end
    function frame:SetUserPlaced() end
    function frame:SetFrameStrata(strata)
        self.strata = strata
    end
    function frame:SetToplevel() end
    function frame:IsMouseOver()
        return false
    end
    function frame:UnregisterEvent(event)
        self.events[event] = nil
    end
    function frame:UnregisterAllEvents()
        self.events = {}
    end
    function frame:SetBackdrop(backdrop)
        self.backdrop = backdrop
    end
    function frame:SetBackdropColor() end
    function frame:SetBackdropBorderColor() end
    function frame:CreateAnimationGroup()
        local group = { animations = {}, playing = false }
        function group:CreateAnimation(kind)
            local anim = { kind = kind }
            for _, setter in ipairs({ "SetFromAlpha", "SetToAlpha", "SetDuration", "SetOrder", "SetStartDelay",
                "SetSmoothing" }) do
                anim[setter] = function() end
            end
            table.insert(self.animations, anim)
            return anim
        end
        function group:SetLooping() end
        function group:SetScript(kind, fn)
            self[kind] = fn
        end
        function group:Play()
            self.playing = true
            self.plays = (self.plays or 0) + 1
        end
        function group:Stop()
            self.playing = false
        end
        function group:IsPlaying()
            return self.playing
        end
        return group
    end
    table.insert(WowStubs.frames, frame)
    return frame
end

-- The fake quest -----------------------------------------------------------------------

local function defaultQuest()
    return {
        id = 214,
        title = "Red Silk Bandanas",
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
    "QuestFrameDetailPanel", "QUEST_DESCRIPTION_GRADIENT_LENGTH", "QUEST_DESCRIPTION_GRADIENT_CPS",
    -- quest log view pieces
    "QuestInfoObjectivesFrame", "QuestInfoObjectivesHeader", "QuestInfoDescriptionHeader",
    "GetObjectiveText", "GetQuestLogQuestText", "GetNumQuestLeaderBoards", "GetQuestLogLeaderBoard",
    "WAYPOINT_OBJECTIVE_FORMAT_OPTIONAL",
    -- Now line and Monke pick
    "C_SuperTrack", "C_Timer", "GetTime", "InCombatLockdown", "UIParent", "ObjectiveTrackerFrame",
    "PlaySound", "SOUNDKIT", "issecretvalue", "QuestMapFrame_OpenToQuestDetails",
    "MonkeDo_Pick", "BINDING_NAME_MONKEDO_PICK", "MonkeDoNowFrame",
    -- the Now line's arrow
    "C_Map", "GetPlayerFacing", "GetQuestUiMapID", "CreateVector2D",
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
    WowStubs.log = {}           -- quest log entries; see WowStubs.addLogQuest
    WowStubs.superTracked = 0   -- C_SuperTrack.GetSuperTrackedQuestID()
    WowStubs.now = 1000         -- GetTime() and the timer clock, in seconds; see WowStubs.advance
    WowStubs.timers = {}
    WowStubs.inCombat = false
    WowStubs.sounds = {}
    WowStubs.openedQuest = nil  -- last QuestMapFrame_OpenToQuestDetails(questID)
    WowStubs.instantQuestText = false -- the instantQuestText CVar; off means the description fades in
    -- Where the player is: a map, a spot on it (x east, y south, 0..1) and facing (0 north,
    -- counter-clockwise). mapID nil = inside an instance: no map, no position, no facing.
    WowStubs.player = { mapID = 1412, x = 0.5, y = 0.5, facing = 0 }
    -- Fake maps: size in yards and where the top left corner sits in a flat world per continent.
    WowStubs.maps = {
        [1412] = { name = "Mulgore", width = 3000, height = 2000, left = 0, top = 0, continent = 1, parent = 1414 },
        [1413] = { name = "The Barrens", width = 4000, height = 6000, left = 3000, top = -1000, continent = 1, parent = 1414 },
        [1414] = { name = "Kalimdor", width = 20000, height = 30000, left = -8000, top = -12000, continent = 1, parent = 947 },
        [1429] = { name = "Elwynn Forest", width = 3500, height = 2300, left = 0, top = 0, continent = 0, parent = 1415 },
    }

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

    -- A quest is described by a table: WowStubs.quest (the one open in the quest frame) or an
    -- entry of WowStubs.log. Fields read below: objectives, title, distanceSq, onContinent,
    -- waypoint, ready, complete, failed.
    local function entryFor(questID)
        for _, entry in ipairs(WowStubs.log) do
            if entry.questID == questID and not entry.isHeader then
                return entry
            end
        end
        if questID == WowStubs.quest.id then
            return WowStubs.quest
        end
        return nil
    end
    WowStubs.entryFor = entryFor

    C_QuestLog = {
        GetQuestObjectives = function(questID)
            local entry = entryFor(questID)
            return entry and entry.objectives or {}
        end,
        GetSelectedQuest = function()
            return WowStubs.quest.id
        end,
        IsOnQuest = function(questID)
            local entry = entryFor(questID)
            if entry == WowStubs.quest then
                return WowStubs.quest.onQuest
            end
            return entry ~= nil
        end,
        GetSuggestedGroupSize = function()
            return WowStubs.quest.groupSize
        end,
        GetQuestTagInfo = function()
            return WowStubs.quest.tag
        end,
        GetNumQuestLogEntries = function()
            local quests = 0
            for _, entry in ipairs(WowStubs.log) do
                if not entry.isHeader then
                    quests = quests + 1
                end
            end
            return #WowStubs.log, quests
        end,
        GetInfo = function(index)
            local e = WowStubs.log[index]
            if not e then
                return nil
            end
            return {
                title = e.title, questID = e.questID or 0, questLogIndex = index,
                isHeader = e.isHeader or false, isHidden = e.isHidden or false, isTask = e.isTask or false,
                isBounty = e.isBounty or false, isInternalOnly = e.isInternalOnly or false,
                isOnMap = e.isOnMap ~= false, frequency = e.frequency or 0,
            }
        end,
        GetLogIndexForQuestID = function(questID)
            for index, entry in ipairs(WowStubs.log) do
                if entry.questID == questID and not entry.isHeader then
                    return index
                end
            end
            return nil
        end,
        GetTitleForQuestID = function(questID)
            local entry = entryFor(questID)
            return entry and entry.title or nil
        end,
        -- MayReturnNothing in Blizzard's documentation: nil when the game has no position.
        GetDistanceSqToQuest = function(questID)
            local entry = entryFor(questID)
            if not entry or entry.distanceSq == nil then
                return nil
            end
            return entry.distanceSq, entry.onContinent ~= false
        end,
        GetNextWaypointText = function(questID)
            local entry = entryFor(questID)
            return entry and entry.waypoint or nil
        end,
        -- entry.nextWaypoint = { mapID, x, y }: a boat or a portal on the way. MayReturnNothing.
        GetNextWaypoint = function(questID)
            local entry = entryFor(questID)
            local way = entry and entry.nextWaypoint
            if way then
                return way[1], way[2], way[3]
            end
        end,
        -- entry.marker = { mapID, x, y }: the quest's map marker, listed on that map only.
        GetQuestsOnMap = function(mapID)
            local markers = {}
            for _, entry in ipairs(WowStubs.log) do
                local m = entry.marker
                if m and m[1] == mapID then
                    markers[#markers + 1] = { questID = entry.questID, mapID = m[1], x = m[2], y = m[3],
                        numObjectives = #(entry.objectives or {}), isQuestStart = false, isDaily = false }
                end
            end
            return markers
        end,
        ReadyForTurnIn = function(questID)
            local entry = entryFor(questID)
            return entry and entry.ready or false
        end,
        IsComplete = function(questID)
            local entry = entryFor(questID)
            return entry and (entry.complete or entry.ready) or false
        end,
        IsFailed = function(questID)
            local entry = entryFor(questID)
            return entry and entry.failed or false
        end,
    }

    CreateVector2D = function(x, y)
        local vector = { x = x, y = y }
        function vector:GetXY()
            return self.x, self.y
        end
        return vector
    end
    GetQuestUiMapID = function(questID)
        local entry = entryFor(questID)
        return entry and entry.marker and entry.marker[1] or 0
    end
    GetPlayerFacing = function()
        if WowStubs.player.mapID then
            return WowStubs.player.facing
        end
    end
    C_Map = {
        GetBestMapForUnit = function(unit)
            if unit == "player" then
                return WowStubs.player.mapID
            end
        end,
        GetPlayerMapPosition = function(mapID, unit)
            local player = WowStubs.player
            if unit == "player" and player.mapID and mapID == player.mapID and player.x then
                return CreateVector2D(player.x, player.y)
            end
        end,
        GetMapWorldSize = function(mapID)
            local map = WowStubs.maps[mapID]
            if map then
                return map.width, map.height
            end
            return 0, 0
        end,
        GetMapInfo = function(mapID)
            local map = WowStubs.maps[mapID]
            if map then
                return { mapID = mapID, name = map.name, mapType = 3, parentMapID = map.parent or 0, flags = 0 }
            end
        end,
        GetWorldPosFromMapPos = function(mapID, position)
            local map = WowStubs.maps[mapID]
            if map then
                return map.continent, CreateVector2D(map.left + position.x * map.width, map.top + position.y * map.height)
            end
        end,
        GetMapPosFromWorldPos = function(continent, world, overrideMapID)
            local map = WowStubs.maps[overrideMapID]
            if map and map.continent == continent then
                return overrideMapID,
                    CreateVector2D((world.x - map.left) / map.width, (world.y - map.top) / map.height)
            end
        end,
    }

    C_SuperTrack = {
        GetSuperTrackedQuestID = function()
            return WowStubs.superTracked or 0
        end,
        SetSuperTrackedQuestID = function(questID)
            WowStubs.superTracked = questID
            WowStubs.fire("SUPER_TRACKING_CHANGED")
        end,
    }

    -- Timers run only when a spec calls WowStubs.advance(seconds).
    local function schedule(delay, fn, every, iterations)
        local handle = { cancelled = false }
        function handle:Cancel()
            self.cancelled = true
        end
        function handle:IsCancelled()
            return self.cancelled
        end
        table.insert(WowStubs.timers, { at = WowStubs.now + delay, fn = fn, every = every,
            left = iterations, handle = handle })
        return handle
    end
    C_Timer = {
        After = function(delay, fn)
            schedule(delay, fn)
        end,
        NewTimer = function(delay, fn)
            return schedule(delay, fn)
        end,
        NewTicker = function(every, fn, iterations)
            return schedule(every, fn, every, iterations)
        end,
    }
    GetTime = function()
        return WowStubs.now
    end
    InCombatLockdown = function()
        return WowStubs.inCombat == true
    end
    UIParent = newFrame("Frame", "UIParent")
    UIParent.shown = true
    UIParent:SetWidth(1024)
    UIParent:SetHeight(768)
    UIParent.center = { 512, 384 }
    UIParent.bottom = 0
    ObjectiveTrackerFrame = newFrame("Frame", "ObjectiveTrackerFrame")
    ObjectiveTrackerFrame.shown = true
    PlaySound = function(kit)
        table.insert(WowStubs.sounds, kit)
    end
    SOUNDKIT = { IG_QUEST_LIST_SELECT = 875, IG_MAINMENU_OPTION_CHECKBOX_ON = 856 }
    issecretvalue = function()
        return false
    end
    QuestMapFrame_OpenToQuestDetails = function(questID)
        WowStubs.openedQuest = questID
    end
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
    QuestFrameDetailPanel = newFrame("Frame", "QuestFrameDetailPanel")
    QuestFrameProgressPanel = newFrame("Frame", "QuestFrameProgressPanel")
    QUEST_DESCRIPTION_GRADIENT_LENGTH = 30 -- QuestFrame.lua, build 1.60.1.70338
    QUEST_DESCRIPTION_GRADIENT_CPS = 70
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
    -- Headers get their text once, from XML, like the real ones: QuestInfo_Display never
    -- sets it again, so a header text an addon changed stays changed until it changes it back.
    QuestInfoObjectivesHeader = newFontString("Quest Objectives")
    QuestInfoDescriptionHeader = newFontString("Description")
    QuestInfoObjectivesHeader:Hide()
    QuestInfoDescriptionHeader:Hide()
    -- The quest frame on parchment, as QuestInfo_Display colours it (GetMaterialTextColors):
    -- dark brown body text and black headers. WowStubs.stone() switches to the stone page.
    WowStubs.parchment()
    QuestInfoObjectivesFrame = newFrame("Frame", "QuestInfoObjectivesFrame")
    QuestInfoObjectivesFrame.Objectives = {}
    WAYPOINT_OBJECTIVE_FORMAT_OPTIONAL = "Optional: %s" -- the real client has its own wording
    GetObjectiveText = function()
        return WowStubs.quest.objectivesText
    end
    GetQuestLogQuestText = function()
        return WowStubs.quest.description, WowStubs.quest.objectivesText
    end
    GetNumQuestLeaderBoards = function()
        return #(WowStubs.quest.objectives or {})
    end
    GetQuestLogLeaderBoard = function(index)
        local objective = (WowStubs.quest.objectives or {})[index]
        if objective then
            return objective.text, objective.type, objective.finished
        end
    end

    -- Blizzard's part: write the server's strings into the shared fontstrings, with the pieces
    -- and in the order of the real templates (QuestInfo.lua, QUEST_TEMPLATE_DETAIL for the
    -- quest giver, QUEST_TEMPLATE_LOG / QUEST_TEMPLATE_MAP_DETAILS for the log and the map).
    QuestInfo_Display = function(template)
        local quest = WowStubs.quest
        QuestInfoFrame.questLog = template.questLog
        for _, region in ipairs({ QuestInfoDescriptionText, QuestInfoObjectivesText, QuestInfoRewardText,
            QuestInfoObjectivesHeader, QuestInfoDescriptionHeader }) do
            region:Hide()
        end
        QuestInfoObjectivesFrame:Hide()
        if template.reward then
            QuestInfoRewardText:SetText(quest.rewardText)
            QuestInfoRewardText:Show()
        elseif template.questLog then
            -- objectives sentence, Blizzard's own objective list, "Description", description
            QuestInfoObjectivesText:SetText(quest.objectivesText)
            QuestInfoObjectivesText:Show()
            WowStubs.showObjectiveLines(quest)
            QuestInfoDescriptionHeader:Show()
            QuestInfoDescriptionText:SetText(quest.description)
            QuestInfoDescriptionText:Show()
        else
            -- description, "Quest Objectives", objectives sentence
            QuestInfoDescriptionText:SetText(quest.description)
            QuestInfoDescriptionText:Show()
            QuestInfoObjectivesHeader:Show()
            QuestInfoObjectivesText:SetText(quest.objectivesText)
            QuestInfoObjectivesText:Show()
        end
    end
end

-- QuestInfo_ShowObjectives in the log and map views: an optional waypoint line, then one
-- fontstring per objective (spell and log objectives are left out), " (Complete)" on finished
-- ones; unused lines are hidden and the frame is shown only when a line is.
function WowStubs.showObjectiveLines(quest)
    local lines = QuestInfoObjectivesFrame.Objectives
    local count = 0
    local function acquire()
        count = count + 1
        lines[count] = lines[count] or newFontString(nil)
        return lines[count]
    end
    if quest.waypoint then
        local line = acquire()
        line:SetText(WAYPOINT_OBJECTIVE_FORMAT_OPTIONAL:format(quest.waypoint))
        line:Show()
    end
    for _, objective in ipairs(quest.objectives or {}) do
        if objective.type ~= "spell" and objective.type ~= "log" then
            local line = acquire()
            local text = (objective.text and objective.text ~= "") and objective.text or objective.type
            if objective.finished then
                text = text .. " (Complete)"
            end
            line:SetText(text)
            line:Show()
        end
    end
    for i = count + 1, #lines do
        lines[i]:Hide()
    end
    if count > 0 then
        QuestInfoObjectivesFrame:Show()
    else
        QuestInfoObjectivesFrame:Hide()
    end
end

-- Put a quest in the fake quest log. `entry` = { questID, title, objectives, distanceSq,
-- onContinent, waypoint, ready, complete, failed, isHeader, isHidden, isTask, ... }.
function WowStubs.addLogQuest(entry)
    table.insert(WowStubs.log, entry)
    return entry
end

-- Move the fake clock forward, running every timer that falls due, in time order.
function WowStubs.advance(seconds)
    local target = WowStubs.now + seconds
    while true do
        local due, dueIndex
        for index, timer in ipairs(WowStubs.timers) do
            if not timer.handle.cancelled and timer.at <= target and (not due or timer.at < due.at) then
                due, dueIndex = timer, index
            end
        end
        if not due then
            break
        end
        table.remove(WowStubs.timers, dueIndex)
        WowStubs.now = due.at
        due.fn(due.handle)
        if due.every and not due.handle.cancelled then
            local left = due.left and due.left - 1
            if left == nil or left > 0 then
                due.at = due.at + due.every
                due.left = left
                table.insert(WowStubs.timers, due)
            end
        end
    end
    WowStubs.now = target
end

-- A click as the client delivers it: OnClick for buttons, OnMouseDown/OnMouseUp otherwise.
function WowStubs.click(frame, button)
    button = button or "LeftButton"
    if frame.scripts.OnClick or (frame.hooks.OnClick and #frame.hooks.OnClick > 0) then
        frame:RunScript("OnClick", button, true)
    else
        frame:RunScript("OnMouseDown", button)
        frame:RunScript("OnMouseUp", button, true)
    end
end

-- The quest giver's panels take turns; hiding the detail panel ends its fade (OnHide).
local function hideDetailPanel()
    QuestFrameDetailPanel:Hide()
    QuestFrameDetailPanel.fading = nil
end

function WowStubs.showQuest(kind)
    if kind == "progress" then
        hideDetailPanel()
        QuestProgressText:SetText(WowStubs.quest.progressText)
        QuestProgressText:Show()
        QuestFrameProgressPanel:Show()
        return
    end
    if kind == "log" then
        QuestInfo_Display({ questLog = true })
        return
    end
    if kind == "reward" then
        hideDetailPanel()
        QuestInfo_Display({ reward = true })
        return
    end
    -- QuestFrameDetailPanel_OnShow: QuestInfo_Display first, then the description fade starts
    -- at the first character (unless Instant Quest Text is on).
    hideDetailPanel()
    QuestFrameDetailPanel:Show()
    QuestInfo_Display({ questLog = false, reward = false })
    QuestFrameDetailPanel.fading = 1
    QuestFrameDetailPanel.fadingProgress = 0
    QuestInfoDescriptionText:SetAlphaGradient(0, QUEST_DESCRIPTION_GRADIENT_LENGTH)
    if WowStubs.instantQuestText then
        QuestFrameDetailPanel.fadingProgress = 1024
    end
end

-- QuestFrameDetailPanel_OnUpdate at 60 frames a second, for `seconds` or until the fade ends.
function WowStubs.fadeQuestText(seconds)
    local panel = QuestFrameDetailPanel
    local step, elapsed = 1 / 60, 0
    while panel.fading and (seconds == nil or elapsed < seconds) do
        elapsed = elapsed + step
        panel.fadingProgress = panel.fadingProgress + step * QUEST_DESCRIPTION_GRADIENT_CPS
        if not QuestInfoDescriptionText:SetAlphaGradient(panel.fadingProgress, QUEST_DESCRIPTION_GRADIENT_LENGTH) then
            panel.fading = nil
        end
    end
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

-- Page colours QuestInfo_Display gives the quest frame's text (GetMaterialTextColors):
-- parchment is the default page; stone is the one Quest Text Contrast switches to.
local function paint(body, header)
    for _, fs in ipairs({ QuestInfoDescriptionText, QuestInfoObjectivesText, QuestInfoRewardText, QuestProgressText }) do
        fs:SetTextColor(body[1], body[2], body[3])
    end
    for _, fs in ipairs({ QuestInfoObjectivesHeader, QuestInfoDescriptionHeader }) do
        fs:SetTextColor(header[1], header[2], header[3])
    end
end

function WowStubs.parchment()
    paint({ 0.18, 0.12, 0.06 }, { 0, 0, 0 })
end

function WowStubs.stone()
    paint({ 1, 1, 1 }, { 0.93, 0.82, 0 })
end

WowStubs.realPrint = realPrint
WowStubs.reset()
