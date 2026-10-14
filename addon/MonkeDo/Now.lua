-- Now.lua: the Now line. A small strip at the bottom middle of the screen, where the eyes
-- already are, that says the ONE next thing to do for the super-tracked quest and how far away
-- it is:
--     [pointer] Take 7 more Red Silk Bandana off bad men · 120 yd
-- The pointer, a monke finger (or a gold arrow, a setting), turns toward the quest (Arrow.lua);
-- where it cannot (close by, an instance, a quest with no map marker) the monke icon stands in
-- its place. The strip sits under the player
-- and target frames, as wide as its words, fades during a fight and glows when one ends. The
-- tooltip adds the quest, the game's route ("Way: Take the boat to Menethil Harbor") and the
-- actions. Left-click is Monke pick, left-drag moves it.
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
local Arrow = ns.Arrow

local Now = {}
ns.Now = Now

local MIN_HEIGHT = 24
local PAD = 5              -- inside the strip, around the icon and the words
local ICON_SIZE = 18       -- the icon's slot; the finger hangs a little over it
local ICON_GAP = 9         -- room for the turned finger's tip before the words
local ICON = "Interface\\AddOns\\MonkeDo\\Media\\icon.png"
local FINGER = "Interface\\AddOns\\MonkeDo\\Media\\finger.png" -- both drawn pointing up
local ARROW = "Interface\\AddOns\\MonkeDo\\Media\\arrow.png"
local FINGER_SIZE = 32     -- the picture includes its gold rim, so the hand itself is about 27
local BACKGROUND_ALPHA = 0.6 -- dark enough that the world behind does not show through the finger
local EDGE_COLOUR = { 1, 0.82, 0, 0.5 } -- a gold hairline round the strip, the glow's colour
local ARROW_SIZE = 20
local ARROW_SECONDS = 0.04 -- the arrow turns 25 times a second while a quest is on the line
-- The longest the words get before they are cut (the tooltip has them whole). The gamepad
-- preset leaves 370 between the player and target frames; this keeps the strip inside that.
local MAX_TEXT_WIDTH = 310
-- The strip's centre, above the bottom middle of the screen: over the action bars and the cast
-- bar, under the player and target frames (Blizzard's preset layouts put their bottom edges
-- 250 and 295 up, and Forever's own layout looks the same).
local DEFAULT_Y = 230
local COMBAT_ALPHA = 0.35  -- faded, not gone: a kill count still moves during the fight
local REFRESH_DELAY = 0.2  -- QUEST_LOG_UPDATE comes in bursts; redraw once per burst
local TICK_SECONDS = 1     -- how often the distance is read while a quest is on the line
local MESSAGE_SECONDS = 3  -- how long a message ("No quest...") stays up
local CUE_DELAY = 1        -- let the loading screen fade out before the resume cue
local CLOSE_YARDS = 30
local SEPARATOR = " \194\183 " -- a middle dot between the task and the distance
local DISTANCE_COLOUR = "|cffb3b3b3" -- the distance in grey: the task is what to read first

local EVENTS = {
    "SUPER_TRACKING_CHANGED", "QUEST_LOG_UPDATE", "QUEST_WATCH_LIST_CHANGED", "QUEST_ACCEPTED",
    "QUEST_REMOVED", "QUEST_TURNED_IN", "ZONE_CHANGED_NEW_AREA", "PLAYER_ENTERING_WORLD",
    "PLAYER_REGEN_DISABLED", "PLAYER_REGEN_ENABLED",
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
local fighting = false    -- between PLAYER_REGEN_DISABLED and PLAYER_REGEN_ENABLED

local function stripFinalStop(s)
    return (s:gsub("[%.%s]+$", ""))
end

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

-- An objective with a count says what is still to do: "Take 10 Red Silk Bandana off bad men"
-- with 3 of 10 done reads "Take 7 more Red Silk Bandana off bad men". The amount is swapped
-- inside the bullet (the validator makes every bullet carry its amount), so the DB wording
-- stays. Anything else keeps the game's progress, "(45%)", as does a bullet with no amount to
-- swap ("(3/10)").
local function stillToDo(task, objective, voice)
    local need, have = objective.numRequired, objective.numFulfilled
    if need == nil or have == nil then
        local _, parsedHave, parsedNeed = Rules.ParseObjectiveText(objective.text)
        have, need = have or parsedHave, need or parsedNeed
    end
    if Rules.COUNTED[objective.type] and type(need) == "number" and type(have) == "number" and need > 1 then
        if have <= 0 then
            return task -- nothing done yet: the bullet's own amount is what is left
        end
        if have < need then
            local more = Voice.Format("now_more", voice, { n = need - have })
            local swapped, swaps = task:gsub("%f[%d]" .. need .. "%f[%D]", more, 1)
            if swaps == 1 then
                return swapped
            end
        end
    end
    local progress = Rules.Progress(objective, voice)
    if not progress then
        return task
    end
    return stripFinalStop(task) .. " " .. progress
end

-- The one next thing for a quest in the log: the bullet of the first unfinished objective,
-- saying what is left of it, or the turn-in line once the quest is ready or every objective
-- is done. The bullets come from Compose, so the DB wording and both voices apply here too.
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
            return stillToDo(tasks[i], live[i], voice)
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

local function withDistance(step, questID, voice, colour)
    local distance = Now.FormatDistance(Pick.DistanceSq(questID), voice)
    if not distance then
        return step
    end
    if colour then
        return stripFinalStop(step) .. colour .. SEPARATOR .. distance .. "|r"
    end
    return stripFinalStop(step) .. SEPARATOR .. distance
end

-- "Take 7 more Red Silk Bandana off bad men · 120 yd". Monke pick uses this for its chat line
-- when the Now line is off; the Monke Do list asks for the distance in grey.
function Now.Describe(questID, voice, greyDistance)
    voice = voice or Core.Get("voice")
    return withDistance(Now.NextStep(questID, voice), questID, voice, greyDistance and DISTANCE_COLOUR or nil)
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

-- One line, as wide as its words up to MAX_TEXT_WIDTH; past that it is cut and the tooltip has
-- it whole. The strip hangs by its centre, so a longer line grows both ways and stays centred.
local function setLine(text)
    if text == lineShown then
        return
    end
    lineShown = text
    local line = frame.monkeLine
    line:SetText(text)
    -- The unbounded width: GetStringWidth can answer the cut width of a line that was cut before.
    local natural = line.GetUnboundedStringWidth and line:GetUnboundedStringWidth() or line:GetStringWidth()
    local width = math.min(MAX_TEXT_WIDTH, math.ceil(tonumber(natural) or MAX_TEXT_WIDTH) + 1)
    line:SetWidth(width)
    frame:SetWidth(PAD + ICON_SIZE + ICON_GAP + width + PAD)
    frame:SetHeight(math.max(MIN_HEIGHT, PAD * 2 + (line:GetStringHeight() or 0)))
end

-- "<next step> · <distance>", the distance in grey.
local function drawQuest(voice)
    setLine(withDistance(stepShown, questShown, voice, DISTANCE_COLOUR))
end

local function messageUp()
    if message and messageUntil and GetTime and GetTime() < messageUntil then
        return true
    end
    message, messageUntil = nil, nil
    return false
end

-- The pointer in the icon's place while it knows the way; the monke icon otherwise.
function Now.PointArrow()
    if not frame then
        return
    end
    local turn = questShown and Arrow.Turn(questShown)
    if turn then
        frame.monkePointer:SetRotation(turn)
        frame.monkePointer:Show()
        frame.monkeIcon:Hide()
    else
        frame.monkePointer:Hide()
        frame.monkeIcon:Show()
    end
end

-- The monke finger, or the gold arrow for whoever reads an arrow more easily.
local function pointerStyle()
    local gold = Core.Get("goldArrow") and true or false
    if frame.monkeGold ~= gold then
        frame.monkeGold = gold
        local size = gold and ARROW_SIZE or FINGER_SIZE
        frame.monkePointer:SetTexture(gold and ARROW or FINGER)
        frame.monkePointer:SetSize(size, size)
    end
end

-- Faded during a fight, whole again under the mouse and when the fight ends.
local function applyAlpha()
    if frame then
        frame:SetAlpha((fighting and not frame.monkeHover) and COMBAT_ALPHA or 1)
    end
end

-- The distance is read once a second and the arrow turned 25 times a second, and both only
-- while the line is shown with a quest on it.
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
    if frame then
        frame.monkeDriver:SetShown(wanted) -- its OnUpdate runs only while it is shown
        Now.PointArrow()
    end
end

-- Off with its setting, and while the original-text toggle is on ("Monke don't" means the
-- stock interface).
local function wanted()
    return Core.Get("nowLine") and not ns.state.showOriginal
end

function Now.IsActive()
    return frame ~= nil and wanted() and true or false
end

function Now.Refresh()
    if not frame then
        return
    end
    if not wanted() then
        frame:Hide()
        questShown, stepShown = nil, nil
        updateTicker()
        return
    end
    local voice = Core.Get("voice")
    pointerStyle()
    Arrow.Forget() -- the quest or its step may have changed
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

-- Between events only the distance moves, so the ticker redraws just that, and has the arrow
-- look its spot up again (waypoints and markers move on as the quest does).
function Now.Tick()
    Arrow.Forget()
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
    if fighting or (InCombatLockdown and InCombatLockdown()) then
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

-- The saved spot, else the bottom middle of the screen (DEFAULT_Y).
function Now.PlaceFrame()
    if not frame then
        return
    end
    lineShown = nil -- size the strip again on the next draw
    frame:ClearAllPoints()
    local saved = savedPoint()
    if saved then
        frame:SetPoint(saved.point, UIParent, saved.relativePoint, saved.x, saved.y)
    else
        frame:SetPoint("CENTER", UIParent, "BOTTOM", 0, DEFAULT_Y)
    end
end

function Now.ResetPosition()
    Core.Store("nowPoint", nil)
    Now.PlaceFrame()
    Now.Refresh()
end

-- Where a drag left the strip, kept by its centre (from the bottom middle of the screen) so a
-- longer line still grows both ways. A client that cannot tell the centre keeps the anchor the
-- drag left, as long as it hangs off UIParent.
local function savePosition(self)
    local cx, cy
    if self.GetCenter then
        cx, cy = self:GetCenter()
    end
    local ux = UIParent.GetCenter and UIParent:GetCenter()
    local bottom = UIParent.GetBottom and UIParent:GetBottom() or 0
    if type(cx) == "number" and type(cy) == "number" and type(ux) == "number" and type(bottom) == "number" then
        local x, y = math.floor(cx - ux + 0.5), math.floor(cy - bottom + 0.5)
        self:ClearAllPoints()
        self:SetPoint("CENTER", UIParent, "BOTTOM", x, y)
        Core.Store("nowPoint", { point = "CENTER", relativePoint = "BOTTOM", x = x, y = y })
        return
    end
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
    self.monkeHover = true
    applyAlpha()
    if not (GameTooltip and GameTooltip.SetOwner) then
        return
    end
    local voice = Core.Get("voice")
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText(questShown and questTitle(questShown) or "Monke Do")
    if GameTooltip.AddLine then
        if questShown and stepShown then
            -- The whole line, in case it was cut, and the game's route.
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

local function hideTooltip(self)
    if self then
        self.monkeHover = nil
        applyAlpha()
    end
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

-- The dark strip with a gold hairline round it. The Monke Do list wears the same.
function Now.Dress(f)
    local background = f:CreateTexture(nil, "BACKGROUND")
    background:SetAllPoints()
    background:SetColorTexture(0, 0, 0, BACKGROUND_ALPHA)
    f.monkeEdges = {}
    for _, side in ipairs({ { "TOPLEFT", "TOPRIGHT", true }, { "BOTTOMLEFT", "BOTTOMRIGHT", true },
        { "TOPLEFT", "BOTTOMLEFT", false }, { "TOPRIGHT", "BOTTOMRIGHT", false } }) do
        local edge = f:CreateTexture(nil, "BORDER")
        edge:SetPoint(side[1], f, side[1], 0, 0)
        edge:SetPoint(side[2], f, side[2], 0, 0)
        if side[3] then
            edge:SetHeight(1)
        else
            edge:SetWidth(1)
        end
        edge:SetColorTexture(EDGE_COLOUR[1], EDGE_COLOUR[2], EDGE_COLOUR[3], EDGE_COLOUR[4])
        f.monkeEdges[#f.monkeEdges + 1] = edge
    end
end

local function createFrame()
    if not (CreateFrame and UIParent) then
        return nil
    end
    local f = CreateFrame("Button", "MonkeDoNowFrame", UIParent)
    f:SetWidth(PAD * 2 + ICON_SIZE)
    f:SetHeight(MIN_HEIGHT)
    f:SetFrameStrata("LOW")
    f:SetClampedToScreen(true)
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForClicks("LeftButtonUp")
    f:RegisterForDrag("LeftButton")
    Now.Dress(f)

    -- Layers: the dark background, then the glow for the resume cue, then the icon and the text
    -- on their own frame so the glow never covers the words. Neither child takes the mouse.
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
    local icon = body:CreateTexture(nil, "ARTWORK")
    icon:SetSize(ICON_SIZE, ICON_SIZE)
    icon:SetPoint("LEFT", f, "LEFT", PAD, 0)
    icon:SetTexture(ICON) -- the monke says "now"; no word needed
    f.monkeIcon = icon
    local pointer = body:CreateTexture(nil, "ARTWORK") -- its picture and size: pointerStyle
    pointer:SetPoint("CENTER", icon, "CENTER", 0, 0)
    pointer:Hide()
    f.monkePointer = pointer

    -- Turns the pointer while a quest is on the line; hidden, and so idle, otherwise.
    local driver = CreateFrame("Frame", nil, f)
    driver:Hide()
    local sinceTurn = 0
    driver:SetScript("OnUpdate", function(_, elapsed)
        sinceTurn = sinceTurn + (tonumber(elapsed) or 0)
        if sinceTurn >= ARROW_SECONDS then
            sinceTurn = 0
            Now.PointArrow()
        end
    end)
    f.monkeDriver = driver
    local line = body:CreateFontString(nil, "OVERLAY", "GameFontHighlightMedium")
    line:SetPoint("LEFT", icon, "RIGHT", ICON_GAP, 0)
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
        fighting = InCombatLockdown and InCombatLockdown() and true or false
        applyAlpha()
        Now.Refresh()
        if C_Timer and C_Timer.After then
            C_Timer.After(CUE_DELAY, function()
                Now.Cue()
            end)
        else
            Now.Cue()
        end
    elseif event == "PLAYER_REGEN_DISABLED" then
        -- InCombatLockdown() can still say false while this event runs, hence the flag.
        fighting = true
        applyAlpha()
    elseif event == "PLAYER_REGEN_ENABLED" then
        fighting = false
        applyAlpha()
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
    fighting = InCombatLockdown and InCombatLockdown() and true or false
    applyAlpha()
    Now.Refresh()
end
