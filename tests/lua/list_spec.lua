-- List.lua: the Monke Do list against the fake quest log. List.Order is pure and tested on its
-- own; the rest goes through C_QuestLog and C_SuperTrack the way the game would.

describe("Monke Do list", function()
    local ns, List, frame
    local DOT = " \194\183 "
    local GREY = "|cffb3b3b3"

    local function ids(list)
        local out = {}
        for i, candidate in ipairs(list) do
            out[i] = candidate.questID
        end
        return out
    end

    -- A quest in the fake log, `yards` away (nil: no known distance).
    local function quest(questID, yards, fields)
        local entry = fields or {}
        entry.questID = questID
        entry.title = entry.title or ("Quest " .. questID)
        entry.objectives = entry.objectives or {
            { text = "0/5 Thing", type = "item", finished = false, numFulfilled = 0, numRequired = 5 },
        }
        if yards then
            entry.distanceSq = yards * yards
        end
        return WowStubs.addLogQuest(entry)
    end

    -- The quest IDs on the shown lines, top to bottom.
    local function shownQuests()
        local out = {}
        for _, row in ipairs(frame.monkeRows or {}) do
            if row:IsShown() and row.monkeQuest then
                out[#out + 1] = row.monkeQuest
            end
        end
        return out
    end

    local function rowFor(questID)
        for _, row in ipairs(frame.monkeRows) do
            if row:IsShown() and row.monkeQuest == questID then
                return row
            end
        end
    end

    before_each(function()
        WowStubs.reset()
        ns = WowStubs.load()
        WowStubs.login()
        List = ns.List
        frame = List.frame
    end)

    it("orders nearest first, quests with no known distance last in log order", function()
        local order = List.Order({
            { questID = 1 }, { questID = 2, distanceSq = 400 ^ 2 }, { questID = 3, distanceSq = 50 ^ 2 },
            { questID = 4 }, { questID = 5, distanceSq = 50 ^ 2 },
        })
        assert.are.same({ 3, 5, 2, 1, 4 }, ids(order))
        assert.are.same({}, List.Order(nil))
    end)

    it("is off by default and hidden with no quests", function()
        quest(30, 200)
        assert.is_false(ns.Core.Get("monkeList"))
        assert.is_false(frame:IsShown())
        assert.is_false(List.IsActive())
        WowStubs.log = {}
        SlashCmdList["MONKEDO"]("list on")
        assert.is_true(List.IsActive())
        assert.is_false(frame:IsShown()) -- nothing to list
    end)

    it("lists every quest's next step and distance, nearest first", function()
        quest(30, 200)
        quest(31, 50, { objectives = {
            { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
        } })
        quest(32, nil)
        SlashCmdList["MONKEDO"]("list on")
        assert.is_true(frame:IsShown())
        assert.are.equal("Monke Do list", frame.monkeTitle:GetText())
        assert.are.same({ 31, 30, 32 }, shownQuests())
        assert.are.equal("Grab 7 more Red Silk Bandana" .. GREY .. DOT .. "50 yd|r", rowFor(31).monkeText:GetText())
        assert.are.equal("Grab 5 Thing.", rowFor(32).monkeText:GetText()) -- no distance known

        WowStubs.log[1].distanceSq = 20 ^ 2 -- the player walked toward quest 30
        WowStubs.advance(2)
        assert.are.same({ 30, 31, 32 }, shownQuests())
        assert.are.equal("Grab 5 Thing" .. GREY .. DOT .. "close|r", rowFor(30).monkeText:GetText())
    end)

    it("holds its order under the mouse", function()
        quest(30, 200)
        quest(31, 50)
        SlashCmdList["MONKEDO"]("list on")
        rowFor(31).scripts.OnEnter(rowFor(31))
        WowStubs.log[1].distanceSq = 10 ^ 2
        WowStubs.advance(4)
        assert.are.same({ 31, 30 }, shownQuests())
        rowFor(31).scripts.OnLeave(rowFor(31))
        WowStubs.advance(2)
        assert.are.same({ 30, 31 }, shownQuests())
    end)

    it("a click tracks that quest: the Now line follows and the line is marked", function()
        quest(30, 200, { title = "Far" })
        quest(31, 50, { title = "Near" })
        SlashCmdList["MONKEDO"]("list on")
        WowStubs.click(rowFor(30), "LeftButton")
        assert.are.equal(30, WowStubs.superTracked)
        assert.are.same({ 875 }, WowStubs.sounds)
        assert.are.equal("Grab 5 Thing" .. GREY .. DOT .. "200 yd|r", ns.Now.frame.monkeLine:GetText())
        assert.is_true(rowFor(30).monkeMark:IsShown())
        assert.is_false(rowFor(31).monkeMark:IsShown())
        assert.are.same({ 1, 0.82, 0 }, { rowFor(30).monkeText:GetTextColor() })
        assert.are.same({ 1, 1, 1 }, { rowFor(31).monkeText:GetTextColor() })
    end)

    it("shows ten lines and says how many more there are", function()
        for id = 1, 13 do
            quest(id, id * 10)
        end
        SlashCmdList["MONKEDO"]("list on")
        assert.are.equal(10, #shownQuests())
        local more = frame.monkeRows[11]
        assert.is_true(more:IsShown())
        assert.are.equal("+3 more", more.monkeText:GetText())
        WowStubs.log = { WowStubs.log[1] }
        WowStubs.fire("QUEST_LOG_UPDATE")
        WowStubs.advance(1)
        assert.are.same({ 1 }, shownQuests())
        assert.is_false(more:IsShown())
    end)

    it("hides with the original-text toggle and comes back with Monke Do text", function()
        quest(30, 200)
        SlashCmdList["MONKEDO"]("list on")
        ns.Core.ToggleOriginal()
        assert.is_false(frame:IsShown())
        ns.Core.ToggleOriginal()
        assert.is_true(frame:IsShown())
        SlashCmdList["MONKEDO"]("list off")
        assert.is_false(frame:IsShown())
    end)

    it("fades in a fight, moves with a drag of its title, and resets", function()
        quest(30, 200)
        SlashCmdList["MONKEDO"]("list on")
        WowStubs.fire("PLAYER_REGEN_DISABLED")
        assert.are.equal(0.35, frame:GetAlpha())
        WowStubs.fire("PLAYER_REGEN_ENABLED")
        assert.are.equal(1, frame:GetAlpha())

        assert.is_true(frame.movable)
        assert.are.same({ "LeftButton" }, frame.dragButtons)
        frame.scripts.OnDragStart(frame)
        frame.center = { 300, 500 }
        frame.scripts.OnDragStop(frame)
        local saved = ns.Core.Get("listPoint")
        assert.are.equal(math.floor(300 - frame:GetWidth() / 2 + 0.5), saved.x)
        assert.are.equal(math.floor(500 + frame:GetHeight() / 2 + 0.5), saved.y)
        assert.are.same({ "TOPLEFT", UIParent, "BOTTOMLEFT", saved.x, saved.y }, { frame:GetPoint() })
        SlashCmdList["MONKEDO"]("list reset")
        assert.is_nil(ns.Core.Get("listPoint"))
        assert.are.same({ "TOPLEFT", UIParent, "LEFT", 24, 160 }, { frame:GetPoint() })
    end)

    it("speaks plain English too", function()
        quest(30, 200)
        SlashCmdList["MONKEDO"]("list on")
        SlashCmdList["MONKEDO"]("voice plain")
        assert.are.equal("Quest to-do list", frame.monkeTitle:GetText())
        assert.are.equal("Collect 5 Thing" .. GREY .. DOT .. "200 yd|r", rowFor(30).monkeText:GetText())
    end)
end)
