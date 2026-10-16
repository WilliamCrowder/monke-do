-- List.lua: the Monke Do list. Like a honey-do list: every quest in the log with its one next
-- step and how far away it is, nearest first, re-sorted as the player walks.
--     Monke Do list
--     Go see Seer Graytongue · 460 yd
--     Grab 9 more Mountain Cougar Pelt · 520 yd
-- Click a line and that quest is super-tracked: the Now line, its pointer and Blizzard's arrow
-- go there. Drag the title to move it. Off by default (`/monke list`, or the settings), and
-- hidden while the original-text toggle is on, like the Now line.
-- It is the addon's own frame. It never touches Blizzard's tracker or map code, so it has no
-- quest item buttons and a click never opens the map.

local _, ns = ...

local Core = ns.Core
local Voice = ns.Voice
local Pick = ns.Pick

local List = {}
ns.List = List

local MAX_LINES = 10
local PAD = 6
local LINE_HEIGHT = 16
local HEADER_HEIGHT = 18
local MIN_WIDTH = 150
local MAX_TEXT_WIDTH = 330
local MARK_SIZE = 12       -- the monke icon beside the quest being tracked
local MARK_GAP = 4
local ICON = "Interface\\AddOns\\MonkeDo\\Media\\icon.png"
local TICK_SECONDS = 2     -- distances and the order are read again this often
local REFRESH_DELAY = 0.2  -- QUEST_LOG_UPDATE comes in bursts; redraw once per burst
local COMBAT_ALPHA = 0.35
local SELECTED = { 1, 0.82, 0 }
local NORMAL = { 1, 1, 1 }
-- The left edge of the screen, above the middle: clear of the chat box, the unit frames and the
-- objective tracker in Blizzard's layouts.
local DEFAULT_X, DEFAULT_Y = 24, 160

local EVENTS = {
    "SUPER_TRACKING_CHANGED", "QUEST_LOG_UPDATE", "QUEST_WATCH_LIST_CHANGED", "QUEST_ACCEPTED",
    "QUEST_REMOVED", "QUEST_TURNED_IN", "ZONE_CHANGED_NEW_AREA", "PLAYER_ENTERING_WORLD",
    "PLAYER_REGEN_DISABLED", "PLAYER_REGEN_ENABLED",
}

local enabled = false
local frame
local rows = {}
local ticker
local refreshPending = false
local fighting = false

-- Order -------------------------------------------------------------------------------------

-- Nearest first. Quests with no known distance (another continent, no map marker) follow in
-- quest-log order. A new list; the input is not touched.
function List.Order(candidates)
    local sorted = {}
    for position, candidate in ipairs(candidates or {}) do
        sorted[position] = { candidate = candidate, position = position,
            distanceSq = Pick.UsableDistance(candidate.distanceSq) }
    end
    table.sort(sorted, function(a, b)
        if a.distanceSq and b.distanceSq and a.distanceSq ~= b.distanceSq then
            return a.distanceSq < b.distanceSq
        end
        if (a.distanceSq ~= nil) ~= (b.distanceSq ~= nil) then
            return a.distanceSq ~= nil
        end
        return a.position < b.position
    end)
    local ordered = {}
    for i, row in ipairs(sorted) do
        ordered[i] = row.candidate
    end
    return ordered
end

local function wanted()
    return Core.Get("monkeList") and not ns.state.showOriginal
end

function List.IsActive()
    return frame ~= nil and wanted() and true or false
end

-- Drawing -----------------------------------------------------------------------------------

local function hovered()
    if frame.monkeHover then
        return true
    end
    for _, row in ipairs(rows) do
        if row.monkeHover then
            return true
        end
    end
    return false
end

local function applyAlpha()
    if frame then
        frame:SetAlpha((fighting and not hovered()) and COMBAT_ALPHA or 1)
    end
end

local function showRowTooltip(row)
    row.monkeHover = true
    applyAlpha()
    if not (GameTooltip and GameTooltip.SetOwner and row.monkeQuest) then
        return
    end
    local voice = Core.Get("voice")
    GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
    GameTooltip:SetText(row.monkeTitle or "Monke Do")
    if GameTooltip.AddLine then
        GameTooltip:AddLine(ns.Now.Describe(row.monkeQuest, voice), 1, 0.82, 0, true)
        GameTooltip:AddLine(Voice.Get("list_tip_click", voice), 1, 1, 1)
    end
    GameTooltip:Show()
end

local function hideRowTooltip(row)
    row.monkeHover = nil
    applyAlpha()
    if GameTooltip then
        GameTooltip:Hide()
    end
end

local function createRow(index)
    local row = CreateFrame("Button", nil, frame)
    row:SetHeight(LINE_HEIGHT)
    row:SetPoint("TOPLEFT", frame, "TOPLEFT", PAD, -(PAD + HEADER_HEIGHT + (index - 1) * LINE_HEIGHT))
    row:RegisterForClicks("LeftButtonUp")
    local mark = row:CreateTexture(nil, "ARTWORK")
    mark:SetSize(MARK_SIZE, MARK_SIZE)
    mark:SetPoint("LEFT", row, "LEFT", 0, 0)
    mark:SetTexture(ICON)
    mark:Hide()
    row.monkeMark = mark
    local text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    text:SetPoint("LEFT", row, "LEFT", MARK_SIZE + MARK_GAP, 0)
    text:SetJustifyH("LEFT")
    text:SetWordWrap(false)
    if text.SetMaxLines then
        text:SetMaxLines(1)
    end
    row.monkeText = text
    row:SetScript("OnClick", function(self)
        if self.monkeQuest then
            Pick.Track(self.monkeQuest)
        end
    end)
    row:SetScript("OnEnter", showRowTooltip)
    row:SetScript("OnLeave", hideRowTooltip)
    rows[index] = row
    return row
end

local function naturalWidth(fontString)
    local width = fontString.GetUnboundedStringWidth and fontString:GetUnboundedStringWidth()
        or fontString:GetStringWidth()
    return math.ceil(tonumber(width) or 0) + 1
end

-- The lines for these quests, the tracked one marked, the panel as wide as its widest line.
local function draw(ordered)
    local voice = Core.Get("voice")
    local tracked = Pick.SuperTracked()
    frame.monkeTitle:SetText(Voice.Get("list_title", voice))
    local shown = math.min(#ordered, MAX_LINES)
    local widest = naturalWidth(frame.monkeTitle)
    for index = 1, shown do
        local quest = ordered[index]
        local row = rows[index] or createRow(index)
        row.monkeQuest = quest.questID
        row.monkeTitle = quest.title
        row.monkeText:SetText(ns.Now.Describe(quest.questID, voice, true))
        local colour = quest.questID == tracked and SELECTED or NORMAL
        row.monkeText:SetTextColor(colour[1], colour[2], colour[3])
        row.monkeMark:SetShown(quest.questID == tracked)
        widest = math.max(widest, MARK_SIZE + MARK_GAP + naturalWidth(row.monkeText))
        row:Show()
    end
    local extra = #ordered - shown
    local lines = shown
    if extra > 0 then
        local row = rows[shown + 1] or createRow(shown + 1)
        row.monkeQuest, row.monkeTitle = nil, nil
        row.monkeText:SetText(Voice.Format("list_more", voice, { n = extra }))
        row.monkeText:SetTextColor(0.7, 0.7, 0.7)
        row.monkeMark:Hide()
        row:Show()
        lines = shown + 1
    end
    for index = lines + 1, #rows do
        rows[index]:Hide()
        rows[index].monkeQuest = nil
    end
    local width = math.max(MIN_WIDTH, math.min(widest, MAX_TEXT_WIDTH + MARK_SIZE + MARK_GAP))
    for index = 1, lines do
        rows[index]:SetWidth(width)
        rows[index].monkeText:SetWidth(width - MARK_SIZE - MARK_GAP)
    end
    frame:SetWidth(width + PAD * 2)
    frame:SetHeight(PAD * 2 + HEADER_HEIGHT + lines * LINE_HEIGHT)
end

local function updateTicker()
    local want = frame ~= nil and frame:IsShown()
    if want and not ticker and C_Timer and C_Timer.NewTicker then
        ticker = C_Timer.NewTicker(TICK_SECONDS, function()
            List.Tick()
        end)
    elseif not want and ticker then
        ticker:Cancel()
        ticker = nil
    end
end

-- Under the mouse the lines keep their places: quests already shown keep their order and new
-- ones go after them, so a click lands on the quest the tooltip names. Any redraw goes through
-- here (the ticker, quest log updates, a pick, a settings change).
local shownOrder = {}

local function holdOrder(ordered)
    local place = {}
    for index, questID in ipairs(shownOrder) do
        place[questID] = index
    end
    local kept, added = {}, {}
    for _, quest in ipairs(ordered) do
        if place[quest.questID] then
            kept[#kept + 1] = quest
        else
            added[#added + 1] = quest
        end
    end
    table.sort(kept, function(a, b)
        return place[a.questID] < place[b.questID]
    end)
    for _, quest in ipairs(added) do
        kept[#kept + 1] = quest
    end
    return kept
end

function List.Refresh()
    if not frame then
        return
    end
    local ordered = wanted() and List.Order(Pick.Candidates()) or {}
    if hovered() then
        ordered = holdOrder(ordered)
    end
    shownOrder = {}
    for index, quest in ipairs(ordered) do
        shownOrder[index] = quest.questID
    end
    if #ordered == 0 then
        frame:Hide()
    else
        draw(ordered)
        frame:Show()
    end
    updateTicker()
end

-- Distances move with the player. The order holds still under the mouse, so a line does not
-- jump away from a click.
function List.Tick()
    if frame and frame:IsShown() and not hovered() then
        List.Refresh()
    end
end

local function refreshSoon()
    if refreshPending then
        return
    end
    if not (C_Timer and C_Timer.After) then
        List.Refresh()
        return
    end
    refreshPending = true
    C_Timer.After(REFRESH_DELAY, function()
        refreshPending = false
        List.Refresh()
    end)
end

-- Position ----------------------------------------------------------------------------------

-- Hangs by its top-left corner, so more quests grow it downwards.
function List.PlaceFrame()
    if not frame then
        return
    end
    frame:ClearAllPoints()
    local saved = Core.Get("listPoint")
    if type(saved) == "table" and type(saved.x) == "number" and type(saved.y) == "number" then
        frame:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", saved.x, saved.y)
    else
        frame:SetPoint("TOPLEFT", UIParent, "LEFT", DEFAULT_X, DEFAULT_Y)
    end
end

function List.ResetPosition()
    Core.Store("listPoint", nil)
    List.PlaceFrame()
end

-- Where a drag left it, as its top-left corner from the bottom-left of the screen.
local function savePosition(self)
    local cx, cy = self:GetCenter()
    local bottom = UIParent.GetBottom and UIParent:GetBottom() or 0
    if type(cx) ~= "number" or type(cy) ~= "number" or type(bottom) ~= "number" then
        return
    end
    local x = math.floor(cx - self:GetWidth() / 2 + 0.5)
    local y = math.floor(cy + self:GetHeight() / 2 - bottom + 0.5)
    Core.Store("listPoint", { x = x, y = y })
    List.PlaceFrame()
end

-- The frame ---------------------------------------------------------------------------------

local function createFrame()
    if not (CreateFrame and UIParent) then
        return nil
    end
    local f = CreateFrame("Frame", "MonkeDoListFrame", UIParent)
    f:SetFrameStrata("LOW")
    f:SetClampedToScreen(true)
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    if ns.Now and ns.Now.Dress then
        ns.Now.Dress(f)
    end
    local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", f, "TOPLEFT", PAD, -PAD)
    title:SetJustifyH("LEFT")
    f.monkeTitle = title
    f.monkeRows = rows
    f:SetScript("OnDragStart", function(self)
        self.monkeDragging = true
        self:StartMoving()
    end)
    f:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        self:SetUserPlaced(false) -- the settings hold the position, not the client's layout cache
        self.monkeDragging = false
        savePosition(self)
    end)
    f:SetScript("OnHide", function(self)
        if self.monkeDragging then
            self:StopMovingOrSizing()
            self.monkeDragging = false
        end
    end)
    f:SetScript("OnEnter", function(self)
        self.monkeHover = true
        applyAlpha()
        if GameTooltip and GameTooltip.SetOwner then
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:SetText(Voice.Get("list_title", Core.Get("voice")))
            if GameTooltip.AddLine then
                GameTooltip:AddLine(Voice.Get("list_tip_drag", Core.Get("voice")), 1, 1, 1)
            end
            GameTooltip:Show()
        end
    end)
    f:SetScript("OnLeave", function(self)
        self.monkeHover = nil
        applyAlpha()
        if GameTooltip then
            GameTooltip:Hide()
        end
    end)
    f:Hide()
    return f
end

local function onEvent(_, event)
    if event == "PLAYER_REGEN_DISABLED" then
        fighting = true -- InCombatLockdown() can still say false while this event runs
        applyAlpha()
    elseif event == "PLAYER_REGEN_ENABLED" then
        fighting = false
        applyAlpha()
    elseif event == "SUPER_TRACKING_CHANGED" then
        List.Refresh()
    else
        refreshSoon()
    end
end

function List.Enable()
    if enabled then
        return
    end
    enabled = true
    frame = createFrame()
    if not frame then
        return
    end
    List.frame = frame
    List.PlaceFrame()
    for _, event in ipairs(EVENTS) do
        pcall(frame.RegisterEvent, frame, event)
    end
    frame:SetScript("OnEvent", onEvent)
    Core.OnChange(List.Refresh)
    fighting = InCombatLockdown and InCombatLockdown() and true or false
    applyAlpha()
    List.Refresh()
end
