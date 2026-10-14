-- Pick.lua: Monke pick, "which quest now?" in one keypress.
-- Ranks the quest log (ready to hand in first, then nearest first) and super-tracks the
-- winner, so Blizzard's own arrow and waypoint point there. Pressing again means "not that
-- one, another": it moves on to the next quest in the ranking and wraps at the end.
-- Super-tracking is an ordinary call, not a protected one, so this works in combat too.

local _, ns = ...

local Core = ns.Core
local Voice = ns.Voice

local Pick = {}
ns.Pick = Pick

-- The last quest Monke pick chose. On a client without C_SuperTrack nothing else remembers
-- the choice, so the Now line falls back to this.
Pick.lastPicked = nil

-- Midnight-era clients can hand out secret values, which addon code must not compare or do
-- arithmetic on. Nothing read here is flagged secret, but asking costs nothing.
function Pick.IsSecret(value)
    if issecretvalue then
        return issecretvalue(value) and true or false
    end
    return false
end

-- A squared distance this code may use: a real, finite, non-negative number. Anything else
-- (nil, a string, NaN, a secret value) means "distance unknown".
function Pick.UsableDistance(distanceSq)
    if Pick.IsSecret(distanceSq) or type(distanceSq) ~= "number" then
        return nil
    end
    if distanceSq ~= distanceSq or distanceSq < 0 or distanceSq == math.huge then
        return nil
    end
    return distanceSq
end

-- Squared yards to the quest's next spot, or nil when unknown: the game has no position
-- for it, it is on another continent, or the value is not one addons may read.
function Pick.DistanceSq(questID)
    if not (C_QuestLog and C_QuestLog.GetDistanceSqToQuest) then
        return nil
    end
    local distanceSq, onContinent = C_QuestLog.GetDistanceSqToQuest(questID)
    if Pick.IsSecret(onContinent) or onContinent == false then
        return nil
    end
    return Pick.UsableDistance(distanceSq)
end

-- Ready to hand in: the game says so, or every objective is done.
function Pick.IsReady(questID)
    if not C_QuestLog then
        return false
    end
    if C_QuestLog.ReadyForTurnIn and C_QuestLog.ReadyForTurnIn(questID) then
        return true
    end
    if C_QuestLog.IsComplete and C_QuestLog.IsComplete(questID) then
        return true
    end
    return false
end

local function isFailed(questID)
    return C_QuestLog.IsFailed ~= nil and C_QuestLog.IsFailed(questID) and true or false
end

-- A quest-log entry the player can work on. Headers, hidden entries, world and bonus
-- objectives (tasks), bounties and internal quests are not.
local function isQuest(info)
    return type(info) == "table" and not info.isHeader and not info.isHidden and not info.isTask
        and not info.isBounty and not info.isInternalOnly
        and type(info.questID) == "number" and info.questID > 0
end

-- Every quest Monke pick could choose, in quest-log order:
-- { questID, title, ready, distanceSq }, distanceSq nil when unknown.
function Pick.Candidates()
    local list = {}
    if not (C_QuestLog and C_QuestLog.GetNumQuestLogEntries and C_QuestLog.GetInfo) then
        return list
    end
    local numEntries = C_QuestLog.GetNumQuestLogEntries()
    if type(numEntries) ~= "number" then
        return list
    end
    for index = 1, numEntries do
        local info = C_QuestLog.GetInfo(index)
        if isQuest(info) and not isFailed(info.questID) then
            list[#list + 1] = {
                questID = info.questID,
                title = info.title,
                ready = Pick.IsReady(info.questID),
                distanceSq = Pick.DistanceSq(info.questID),
            }
        end
    end
    return list
end

-- Best first, as a new list; the input is not touched. Ready quests with a known distance
-- come first, nearest first; then unfinished ones, nearest first; then every quest with no
-- known distance, ready before unfinished. Ties keep quest-log order (the input order).
function Pick.Rank(candidates)
    local rows = {}
    for position, candidate in ipairs(candidates or {}) do
        local distanceSq = Pick.UsableDistance(candidate.distanceSq)
        local band
        if distanceSq then
            band = candidate.ready and 1 or 2
        else
            band = candidate.ready and 3 or 4
        end
        rows[position] = { candidate = candidate, position = position, band = band, distanceSq = distanceSq }
    end
    table.sort(rows, function(a, b)
        if a.band ~= b.band then
            return a.band < b.band
        end
        if a.distanceSq and b.distanceSq and a.distanceSq ~= b.distanceSq then
            return a.distanceSq < b.distanceSq
        end
        return a.position < b.position
    end)
    local ranked = {}
    for i, row in ipairs(rows) do
        ranked[i] = row.candidate
    end
    return ranked
end

function Pick.SuperTracked()
    if C_SuperTrack and C_SuperTrack.GetSuperTrackedQuestID then
        return C_SuperTrack.GetSuperTrackedQuestID()
    end
    return Pick.lastPicked
end

local function playSound()
    if PlaySound and SOUNDKIT and SOUNDKIT.IG_QUEST_LIST_SELECT then
        PlaySound(SOUNDKIT.IG_QUEST_LIST_SELECT)
    end
end

-- Super-track one quest (0: none), with the short select sound. Monke pick and a click on the
-- Monke Do list both come through here.
function Pick.Track(questID)
    Pick.lastPicked = questID
    local Now = ns.Now
    local nowUp = Now ~= nil and Now.IsActive()
    if nowUp then
        Now.ClearMessage()
    end
    if C_SuperTrack and C_SuperTrack.SetSuperTrackedQuestID then
        C_SuperTrack.SetSuperTrackedQuestID(questID) -- the Now line follows the event; 0 clears
    end
    playSound()
    if nowUp then
        -- Also when no SUPER_TRACKING_CHANGED is coming: no C_SuperTrack, or the same quest
        -- again. An unchanged line costs nothing to redraw.
        Now.Refresh()
    end
    if ns.List then
        ns.List.Refresh()
    end
end

-- Monke pick. Super-tracks the best quest, or the one after the quest already
-- super-tracked. After the last one it tracks nothing (Blizzard's arrow and the Now line go
-- quiet), and the click after that starts from the best quest again. Returns the chosen quest
-- ID, 0 for "nothing", or nil when there is nothing to pick.
function Pick.Next()
    local voice = Core.Get("voice")
    local Now = ns.Now
    local nowUp = Now ~= nil and Now.IsActive()
    local ranked = Pick.Rank(Pick.Candidates())
    if #ranked == 0 then
        local text = Voice.Get("pick_none", voice)
        if not (nowUp and Now.Say(text)) then
            Core.Print(text)
        end
        return nil
    end

    local current = Pick.SuperTracked()
    local choice = ranked[1]
    for position, candidate in ipairs(ranked) do
        if candidate.questID == current then
            choice = ranked[position + 1] -- nil after the last: track nothing
            break
        end
    end
    local questID = choice and choice.questID or 0
    Pick.Track(questID)
    if nowUp then
        return questID
    elseif not choice then
        Core.Print(Voice.Get("pick_cleared", voice))
    elseif Now then
        -- The Now line is off: one chat line says what was picked and what to do there.
        Core.Print(Voice.Format("pick_chat", voice, {
            title = choice.title or "",
            task = Now.Describe(choice.questID, voice),
        }))
    end
    return questID
end
