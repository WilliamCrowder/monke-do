-- Now.lua: the Now line. One small frame above the objective tracker that says the ONE next
-- thing to do for the super-tracked quest, and how far away it is, on one line:
--     Now: Grab 10 Red Silk Bandana (3/10) · 120 yards
-- The tooltip adds the full line (in case it was cut), the game's route ("Way: Take the boat to
-- Menethil Harbor") and the actions. Left-click is Monke pick, left-drag moves it.
-- It is the addon's own frame, not a hook into Blizzard's tracker, and it is not secure.
-- It never calls Blizzard's map code (QuestMapFrame_*): doing that from addon code leaves the
-- map and tracker state tainted, and Blizzard's next redraw of them in combat is blocked. The
-- quest is super-tracked, so the M key and Blizzard's arrow already show it.

local _, ns = ...

local Core = ns.Core
local Compose = ns.Compose
local Rules = ns.Rules
local Voice = ns.Voice
local Pick = ns.Pick

local Now = {}
ns.Now = Now

local WIDTH = 260          -- when the objective tracker cannot tell us its width
local MIN_HEIGHT = 20
local PAD = 3
-- Between the line's bottom edge and the tracker's top. The frames Edit Mode stacks above the
-- tracker (durability figure, boss frames) can leave as little as 25 px, so the line stays one
-- line and hugs the tracker.
local TRACKER_GAP = 1
local REFRESH_DELAY = 0.2  -- QUEST_LOG_UPDATE comes in bursts; redraw once per burst
local TICK_SECONDS = 1     -- how often the distance is read while a quest is on the line
local MESSAGE_SECONDS = 3  -- how long a message ("after the fight") stays up
local CUE_DELAY = 1        -- let the loading screen fade out before the resume cue
local CLOSE_YARDS = 30
local SEPARATOR = " \194\183 " -- a middle dot between the task and the distance

local EVENTS = {
    "SUPER_TRACKING_CHANGED", "QUEST_LOG_UPDATE", "QUEST_WATCH_LIST_CHANGED", "QUEST_ACCEPTED",
    "QUEST_REMOVED", "QUEST_TURNED_IN", "ZONE_CHANGED_NEW_AREA", "PLAYER_ENTERING_WORLD",
    "PLAYER_REGEN_ENABLED",
}

local POINTS = {
    TOPLEFT = true, TOP = true, TOPRIGHT = true, LEFT = true, CENTER = true, RIGHT = true,
    BOTTOMLEFT = true, BOTTOM = true, BOTTOMRIGHT = true,
}

local enabled = false
local frame
local questShown          -- the quest on the line; nil while it shows the invitation
local stepShown           -- that quest's next step, without the distance
local lineShown           -- the text on screen, so an unchanged redraw costs nothing
local refreshPending = false
local ticker
local message, messageUntil

-- Words -------------------------------------------------------------------------------------

-- "close" under 30 yards, then the nearest 10 yards, the nearest 100 from 1000 on.
-- nil when the distance is unknown.
function Now.FormatDistance(distanceSq, voice)
    distanceSq = Pick.UsableDistance(distanceSq)
    if not distanceSq then
        return nil
    end
    local yards = math.sqrt(distanceSq)
    if yards < CLOSE_YARDS then
        return Voice.Get("now_close", voice)
    end
    local step = yards < 1000 and 10 or 100
    return Voice.Format("now_yards", voice, { n = math.floor(yards / step + 0.5) * step })
end

-- The one next thing for a quest in the log: the bullet of the first unfinished objective,
-- with its live progress, or the turn-in line once the quest is ready or every objective is
-- done. The bullets come from Compose, so the DB wording and both voices apply here too.
function Now.NextStep(questID, voice)
    local objectives
    if C_QuestLog and C_QuestLog.GetQuestObjectives then
        objectives = C_QuestLog.GetQuestObjectives(questID)
    end
    if type(objectives) ~= "table" then
        objectives = nil
    end
    local sections = Compose.Build({
        record = Core.GetRecord(questID),
        objectives = objectives,
        voice = voice,
        showProgress = true,
    })
    local tasks = sections.tasks
    local turnIn = tasks[#tasks] -- Compose always ends with the turn-in line
    if Pick.IsReady(questID) then
        return turnIn
    end
    -- tasks[i] pairs with the i-th visible objective, up to numObjectiveTasks.
    local live = Rules.Visible(objectives)
    for i = 1, math.min(sections.numObjectiveTasks or 0, #live) do
        if not live[i].finished then
            return tasks[i]
        end
    end
    return turnIn
end

local function waypointText(questID)
    if not (C_QuestLog and C_QuestLog.GetNextWaypointText) then
        return nil
    end
    local text = C_QuestLog.GetNextWaypointText(questID)
    if Pick.IsSecret(text) or type(text) ~= "string" or text == "" then
        return nil
    end
    return text
end

local function withDistance(step, questID, voice)
    local distance = Now.FormatDistance(Pick.DistanceSq(questID), voice)
    if not distance then
        return step
    end
    return (step:gsub("[%.%s]+$", "")) .. SEPARATOR .. distance
end

-- "Grab 10 Red Silk Bandana (3/10) · 120 yards". Monke pick uses this for its chat line
-- when the Now line is off.
function Now.Describe(questID, voice)
    voice = voice or Core.Get("voice")
    return withDistance(Now.NextStep(questID, voice), questID, voice)
end

-- The quest the line is about: the super-tracked quest, when it is in the quest log.
local function trackedQuest()
    local questID = Pick.SuperTracked()
    if type(questID) ~= "number" or questID <= 0 then
        return nil
    end
    if not (C_QuestLog and C_QuestLog.GetLogIndexForQuestID and C_QuestLog.GetLogIndexForQuestID(questID)) then
        return nil
    end
    return questID
end

local function questTitle(questID)
    if C_QuestLog and C_QuestLog.GetTitleForQuestID then
        local title = C_QuestLog.GetTitleForQuestID(questID)
        if type(title) == "string" and title ~= "" then
            return title
        end
    end
    return nil
end

-- Drawing -----------------------------------------------------------------------------------

-- One line, never wrapped: a second line would grow up into the frames above the tracker.
local function setLine(line)
    if line == lineShown then
        return
    end
    lineShown = line
    frame.monkeLine:SetText(line)
    frame:SetHeight(math.max(MIN_HEIGHT, PAD * 2 + (frame.monkeLine:GetStringHeight() or 0)))
end

-- "Now: <next step> · <distance>".
local function drawQuest(voice)
    setLine(Voice.Get("now_prefix", voice) .. withDistance(stepShown, questShown, voice))
end

local function messageUp()
    if message and messageUntil and GetTime and GetTime() < messageUntil then
        return true
    end
    message, messageUntil = nil, nil
    return false
end

-- The distance is read once a second, and only while the line is shown with a quest on it.
local function updateTicker()
    local wanted = frame ~= nil and frame:IsShown() and questShown ~= nil
    if wanted and not ticker and C_Timer and C_Timer.NewTicker then
        ticker = C_Timer.NewTicker(TICK_SECONDS, function()
            Now.Tick()
        end)
    elseif not wanted and ticker then
        ticker:Cancel()
        ticker = nil
    end
end

function Now.IsActive()
    return frame ~= nil and Core.Get("nowLine") and true or false
end

function Now.Refresh()
    if not frame then
        return
    end
    if not Core.Get("nowLine") then
        frame:Hide()
        questShown, stepShown = nil, nil
        updateTicker()
        return
    end
    local voice = Core.Get("voice")
    questShown = trackedQuest()
    stepShown = questShown and Now.NextStep(questShown, voice) or nil
    if messageUp() then
        setLine(message)
    elseif questShown then
        drawQuest(voice)
    else
        setLine(Voice.Get("now_nothing", voice))
    end
    frame:Show()
    updateTicker()
end

-- Between events only the distance moves, so the ticker redraws just that.
function Now.Tick()
    if not (frame and frame:IsShown() and questShown and stepShown) or messageUp() then
        return
    end
    drawQuest(Core.Get("voice"))
end

local function refreshSoon()
    if refreshPending then
        return
    end
    if not (C_Timer and C_Timer.After) then
        Now.Refresh()
        return
    end
    refreshPending = true
    C_Timer.After(REFRESH_DELAY, function()
        refreshPending = false
        Now.Refresh()
    end)
end

-- A new pick makes any message stale.
function Now.ClearMessage()
    message, messageUntil = nil, nil
end

-- A short message in place of the line for a few seconds. Returns false when the line is
-- not up, so the caller can use chat instead.
function Now.Say(text)
    if not (Now.IsActive() and GetTime) then
        return false
    end
    message = text
    messageUntil = GetTime() + MESSAGE_SECONDS - 0.1
    Now.Refresh()
    if C_Timer and C_Timer.After then
        C_Timer.After(MESSAGE_SECONDS, function()
            Now.Refresh()
        end)
    end
    return true
end

-- The resume cue: after a loading screen or a fight, two soft pulses (about two seconds)
-- draw the eye back to what the player was doing. Never in combat, and only when there is
-- a quest on the line.
function Now.Cue()
    if not (frame and frame:IsShown() and questShown and frame.monkePulse) then
        return false
    end
    if InCombatLockdown and InCombatLockdown() then
        return false
    end
    frame.monkePulse:Stop()
    frame.monkePulse:Play()
    return true
end

-- Position ----------------------------------------------------------------------------------

local function savedPoint()
    local saved = Core.Get("nowPoint")
    if type(saved) ~= "table" or not (POINTS[saved.point] and POINTS[saved.relativePoint]) then
        return nil
    end
    if type(saved.x) ~= "number" or type(saved.y) ~= "number" then
        return nil
    end
    return saved
end

local function lineWidth()
    local tracker = ObjectiveTrackerFrame
    local width = tracker and tracker.GetWidth and tracker:GetWidth()
    if type(width) == "number" and width >= 180 and width <= 420 then
        return width
    end
    return WIDTH
end

-- The saved spot, else just above the objective tracker, left edges lined up, else under
-- the minimap where the tracker usually is.
function Now.PlaceFrame()
    if not frame then
        return
    end
    local width = lineWidth()
    frame:SetWidth(width)
    frame.monkeLine:SetWidth(width - PAD * 2)
    lineShown = nil -- measure the height again on the next draw

    frame:ClearAllPoints()
    local saved = savedPoint()
    if saved then
        frame:SetPoint(saved.point, UIParent, saved.relativePoint, saved.x, saved.y)
    elseif ObjectiveTrackerFrame then
        frame:SetPoint("BOTTOMLEFT", ObjectiveTrackerFrame, "TOPLEFT", 0, TRACKER_GAP)
    else
        frame:SetPoint("TOPRIGHT", UIParent, "TOPRIGHT", -100, -240)
    end
end

function Now.ResetPosition()
    Core.Store("nowPoint", nil)
    Now.PlaceFrame()
    Now.Refresh()
end

local function savePosition(self)
    local point, relativeTo, relativePoint, x, y = self:GetPoint()
    if not POINTS[point] or type(x) ~= "number" or type(y) ~= "number" then
        return
    end
    if relativeTo ~= nil and relativeTo ~= UIParent then
        return -- still hanging off another frame: keep the old spot rather than guess
    end
    Core.Store("nowPoint", { point = point, relativePoint = POINTS[relativePoint] and relativePoint or point,
        x = x, y = y })
end

-- The frame ---------------------------------------------------------------------------------

local function showTooltip(self)
    if not (GameTooltip and GameTooltip.SetOwner) then
        return
    end
    local voice = Core.Get("voice")
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText(questShown and questTitle(questShown) or "Monke Do")
    if GameTooltip.AddLine then
        if questShown and stepShown then
            -- The whole line, which a narrow tracker may have cut, and the game's route.
            GameTooltip:AddLine(withDistance(stepShown, questShown, voice), 1, 0.82, 0, true)
            local way = waypointText(questShown)
            if way then
                GameTooltip:AddLine(Voice.Format("now_way", voice, { text = way }), 0.8, 0.8, 0.8, true)
            end
        end
        GameTooltip:AddLine(Voice.Get("now_tip_click", voice), 1, 1, 1)
        GameTooltip:AddLine(Voice.Get("now_tip_drag", voice), 1, 1, 1)
    end
    GameTooltip:Show()
end

local function hideTooltip()
    if GameTooltip then
        GameTooltip:Hide()
    end
end

-- Two soft pulses of the glow, about two seconds in all.
local function createPulse(glow)
    local pulse = glow:CreateAnimationGroup()
    for i = 1, 2 do
        local up = pulse:CreateAnimation("Alpha")
        up:SetFromAlpha(0)
        up:SetToAlpha(1)
        up:SetDuration(0.5)
        up:SetOrder(i * 2 - 1)
        up:SetSmoothing("IN_OUT")
        local down = pulse:CreateAnimation("Alpha")
        down:SetFromAlpha(1)
        down:SetToAlpha(0)
        down:SetDuration(0.5)
        down:SetOrder(i * 2)
        down:SetSmoothing("IN_OUT")
    end
    return pulse
end

local function fill(child, parent)
    child:SetPoint("TOPLEFT", parent, "TOPLEFT", 0, 0)
    child:SetPoint("BOTTOMRIGHT", parent, "BOTTOMRIGHT", 0, 0)
end

local function createFrame()
    if not (CreateFrame and UIParent) then
        return nil
    end
    local f = CreateFrame("Button", "MonkeDoNowFrame", UIParent)
    f:SetWidth(WIDTH)
    f:SetHeight(MIN_HEIGHT)
    f:SetFrameStrata("LOW")
    f:SetClampedToScreen(true)
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForClicks("LeftButtonUp")
    f:RegisterForDrag("LeftButton")

    local background = f:CreateTexture(nil, "BACKGROUND")
    background:SetAllPoints()
    background:SetColorTexture(0, 0, 0, 0.5)

    -- Layers: the dark background, then the glow for the resume cue, then the text on its
    -- own frame so the glow never covers the words. Neither child takes the mouse.
    local glow = CreateFrame("Frame", nil, f)
    fill(glow, f)
    glow:SetFrameLevel(f:GetFrameLevel() + 1)
    glow:SetAlpha(0)
    local shine = glow:CreateTexture(nil, "ARTWORK")
    shine:SetAllPoints()
    shine:SetColorTexture(1, 0.78, 0.25, 0.4)
    f.monkePulse = createPulse(glow)

    local body = CreateFrame("Frame", nil, f)
    fill(body, f)
    body:SetFrameLevel(f:GetFrameLevel() + 2)
    local line = body:CreateFontString(nil, "OVERLAY", "GameFontHighlightMedium") -- a size up from the tracker
    line:SetPoint("TOPLEFT", f, "TOPLEFT", PAD, -PAD)
    line:SetJustifyH("LEFT")
    line:SetWordWrap(false) -- one line; the tooltip has the rest
    if line.SetMaxLines then
        line:SetMaxLines(1)
    end
    f.monkeLine = line

    f:SetScript("OnClick", function(self, button)
        -- The mouse-up that ends a drag is not a click.
        if self.monkeDragging or (self.monkeDraggedAt and GetTime and GetTime() - self.monkeDraggedAt < 0.3) then
            return
        end
        if button == "LeftButton" then
            Pick.Next()
        end
    end)
    f:SetScript("OnMouseDown", function(self)
        self.monkeDragging = false -- a new press; a drag that never saw OnDragStop is over
    end)
    f:SetScript("OnDragStart", function(self)
        self.monkeDragging = true
        hideTooltip()
        self:StartMoving()
    end)
    f:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        self:SetUserPlaced(false) -- the settings hold the position, not the client's layout cache
        self.monkeDragging = false
        self.monkeDraggedAt = GetTime and GetTime() or nil
        savePosition(self)
    end)
    f:SetScript("OnHide", function(self)
        if self.monkeDragging then
            self:StopMovingOrSizing() -- hidden mid-drag: do not stay stuck to the cursor
            self.monkeDragging = false
        end
    end)
    f:SetScript("OnEnter", showTooltip)
    f:SetScript("OnLeave", hideTooltip)
    return f
end

local function onEvent(_, event)
    if event == "SUPER_TRACKING_CHANGED" then
        Now.Refresh()
    elseif event == "PLAYER_ENTERING_WORLD" then
        Now.Refresh()
        if C_Timer and C_Timer.After then
            C_Timer.After(CUE_DELAY, function()
                Now.Cue()
            end)
        else
            Now.Cue()
        end
    elseif event == "PLAYER_REGEN_ENABLED" then
        Now.Cue()
    else
        refreshSoon()
    end
end

function Now.Enable()
    if enabled then
        return
    end
    enabled = true
    frame = createFrame()
    if not frame then
        return
    end
    Now.frame = frame
    Now.PlaceFrame()
    for _, event in ipairs(EVENTS) do
        pcall(frame.RegisterEvent, frame, event) -- an event this build lacks costs one update path
    end
    frame:SetScript("OnEvent", onEvent)
    Core.OnChange(Now.Refresh)
    Now.Refresh()
end
