-- Arrow.lua and the Now line's arrow against the fake client. The fake maps are flat
-- rectangles (WowStubs.maps); the real direction, against the minimap's quest arrow, is on the
-- in-game checklist.

local PI = math.pi

local function near(expected, actual, what)
    assert(type(actual) == "number", (what or "turn") .. ": expected a number, got " .. tostring(actual))
    assert(math.abs(expected - actual) < 1e-9, (what or "turn") .. ": expected " .. expected .. ", got " .. actual)
end

describe("Arrow", function()
    local ns, Arrow

    -- Quest 214 in the fake log with its marker on `marker` = { mapID, x, y }.
    local function quest(marker, fields)
        local entry = fields or {}
        entry.questID = entry.questID or 214
        entry.title = "The Hunt Continues"
        entry.marker = marker
        entry.objectives = entry.objectives or {
            { text = "3/10 Mountain Cougar Pelt", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
        }
        return WowStubs.addLogQuest(entry)
    end

    before_each(function()
        WowStubs.reset()
        _G.MonkeDB = {}
        ns = WowStubs.load()
        WowStubs.login()
        Arrow = ns.Arrow
        Arrow.Forget()
    end)

    describe("the turn", function()
        it("is 0 ahead, positive to the left and negative to the right, facing north", function()
            near(0, Arrow.Rotation(0, -100, 0), "north")
            near(PI / 2, Arrow.Rotation(-100, 0, 0), "west")
            near(-PI / 2, Arrow.Rotation(100, 0, 0), "east")
            near(PI, math.abs(Arrow.Rotation(0, 100, 0)), "south")
        end)

        it("counts from the way the player faces", function()
            near(0, Arrow.Rotation(100, 0, 3 * PI / 2), "facing east, spot east")
            near(-PI / 2, Arrow.Rotation(0, -100, PI / 2), "facing west, spot north")
            near(-PI / 2, Arrow.Rotation(0, 100, 3 * PI / 2), "facing east, spot south: on the right")
            near(PI / 2, Arrow.Rotation(0, -100, 3 * PI / 2), "facing east, spot north: on the left")
        end)

        it("stays within half a turn either way", function()
            for facing = 0, 6, 0.5 do
                local turn = Arrow.Rotation(70, 40, facing)
                assert.is_true(turn > -PI and turn <= PI)
            end
        end)

        it("is nothing within 30 yards", function()
            assert.is_nil(Arrow.Rotation(20, 20, 0))
            assert.is_not_nil(Arrow.Rotation(30, 0, 0))
        end)
    end)

    describe("where it points", function()
        it("at the quest's marker on the player's map, scaled to yards", function()
            -- Mulgore is 3000 x 2000 yards: 0.1 east is 300 yards, 0.1 south 200 yards.
            quest({ 1412, 0.6, 0.6 })
            near(math.atan2(-300, -200), Arrow.Turn(214))
        end)

        it("at the game's next waypoint first (a boat, a portal)", function()
            quest({ 1412, 0.6, 0.5 }, { nextWaypoint = { 1412, 0.5, 0.4 } })
            near(0, Arrow.Turn(214))
        end)

        it("at a marker on a neighbouring map of the same continent", function()
            -- The Barrens 0.1, 0.5 is world 3400, 2000; the player, Mulgore 0.5, 0.5, is 1500, 1000.
            quest({ 1413, 0.1, 0.5 })
            near(math.atan2(-1900, -1000), Arrow.Turn(214))
        end)

        it("finds a marker listed on a map above the player's", function()
            _G.GetQuestUiMapID = nil
            -- Kalimdor 0.5, 0.4 is world 2000, 0: 500 east and 1000 north of the player.
            quest({ 1414, 0.5, 0.4 })
            near(math.atan2(-500, 1000), Arrow.Turn(214))
        end)

        it("nowhere for a marker on another continent, a quest with no marker, or another quest", function()
            quest({ 1429, 0.5, 0.5 })
            assert.is_nil(Arrow.Turn(214))
            Arrow.Forget()
            WowStubs.log = {}
            quest(nil)
            assert.is_nil(Arrow.Turn(214))
            assert.is_nil(Arrow.Turn(999))
        end)

        it("nowhere inside an instance, or with a position or facing addons may not read", function()
            quest({ 1412, 0.6, 0.5 })
            WowStubs.player.mapID = nil
            assert.is_nil(Arrow.Turn(214))
            WowStubs.player.mapID = 1412
            _G.issecretvalue = function(value)
                return value == WowStubs.player.facing
            end
            WowStubs.player.facing = 1.25
            assert.is_nil(Arrow.Turn(214))
        end)

        it("keeps the spot until Forget, another quest or another map, and reads the player every time", function()
            local entry = quest({ 1412, 0.6, 0.5 })
            near(-PI / 2, Arrow.Turn(214))
            entry.marker = { 1412, 0.5, 0.4 } -- the marker moved on
            near(-PI / 2, Arrow.Turn(214))
            WowStubs.player.facing = PI / 2 -- the player turned west: read at once
            near(PI, math.abs(Arrow.Turn(214)))
            Arrow.Forget()
            near(-PI / 2, Arrow.Turn(214)) -- the new spot: north, with the player facing west
        end)

        it("survives a client with no map API at all", function()
            quest({ 1412, 0.6, 0.5 })
            _G.C_Map, _G.GetPlayerFacing, _G.CreateVector2D, _G.GetQuestUiMapID = nil, nil, nil, nil
            assert.has_no.errors(function()
                assert.is_nil(Arrow.Turn(214))
            end)
        end)
    end)
end)

describe("Now line arrow", function()
    local ns, frame

    local function quest(marker, fields)
        local entry = fields or {}
        entry.questID = 214
        entry.title = "The Hunt Continues"
        entry.marker = marker
        entry.distanceSq = entry.distanceSq or 300 * 300
        entry.objectives = {
            { text = "3/10 Mountain Cougar Pelt", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
        }
        return WowStubs.addLogQuest(entry)
    end

    local function frameTick(seconds)
        assert.is_true(frame.monkeDriver:IsShown(), "the arrow's driver should be running")
        frame.monkeDriver:RunScript("OnUpdate", seconds)
    end

    before_each(function()
        WowStubs.reset()
        _G.MonkeDB = {}
        ns = WowStubs.load()
        WowStubs.login()
        frame = ns.Now.frame
    end)

    it("takes the monke icon's place and points at the quest", function()
        assert.is_true(frame.monkeIcon:IsShown())
        assert.is_false(frame.monkePointer:IsShown())
        assert.are.equal("Interface\\AddOns\\MonkeDo\\Media\\finger.png", frame.monkePointer.path)
        quest({ 1412, 0.6, 0.5 })
        C_SuperTrack.SetSuperTrackedQuestID(214)
        assert.is_true(frame.monkePointer:IsShown())
        assert.is_false(frame.monkeIcon:IsShown())
        near(-PI / 2, frame.monkePointer.rotation)
    end)

    it("turns as the player turns, 25 times a second", function()
        quest({ 1412, 0.6, 0.5 })
        C_SuperTrack.SetSuperTrackedQuestID(214)
        WowStubs.player.facing = 3 * PI / 2 -- now facing east, toward the spot
        frameTick(0.02)
        near(-PI / 2, frame.monkePointer.rotation) -- not yet
        frameTick(0.02)
        near(0, frame.monkePointer.rotation)
    end)

    it("gives way to the monke icon when close, and comes back when the player walks off", function()
        quest({ 1412, 0.6, 0.5 })
        C_SuperTrack.SetSuperTrackedQuestID(214)
        WowStubs.player.x = 0.595 -- 15 yards short of the spot
        frameTick(0.05)
        assert.is_true(frame.monkeIcon:IsShown())
        assert.is_false(frame.monkePointer:IsShown())
        WowStubs.player.x = 0.5
        frameTick(0.05)
        assert.is_true(frame.monkePointer:IsShown())
    end)

    it("looks the spot up again once a second", function()
        local entry = quest({ 1412, 0.6, 0.5 })
        C_SuperTrack.SetSuperTrackedQuestID(214)
        entry.marker = { 1412, 0.5, 0.4 }
        frameTick(0.05)
        near(-PI / 2, frame.monkePointer.rotation)
        WowStubs.advance(1)
        frameTick(0.05)
        near(0, frame.monkePointer.rotation)
    end)

    it("is the monke finger, or the gold arrow from the settings or /monke pointer", function()
        local FINGER = "Interface\\AddOns\\MonkeDo\\Media\\finger.png"
        local ARROW = "Interface\\AddOns\\MonkeDo\\Media\\arrow.png"
        assert.are.equal(FINGER, frame.monkePointer.path)
        assert.are.same({ 26, 26 }, frame.monkePointer.size)
        SlashCmdList["MONKEDO"]("pointer arrow")
        assert.are.equal(ARROW, frame.monkePointer.path)
        assert.are.same({ 20, 20 }, frame.monkePointer.size)
        SlashCmdList["MONKEDO"]("pointer finger")
        assert.are.equal(FINGER, frame.monkePointer.path)
        ns.Core.Set("goldArrow", true)
        assert.are.equal(ARROW, frame.monkePointer.path)
    end)

    it("rests with nothing tracked, with the line off, and shows the icon in an instance", function()
        quest({ 1412, 0.6, 0.5 })
        assert.is_false(frame.monkeDriver:IsShown())
        C_SuperTrack.SetSuperTrackedQuestID(214)
        assert.is_true(frame.monkeDriver:IsShown())
        WowStubs.player.mapID = nil
        frameTick(0.05)
        assert.is_true(frame.monkeIcon:IsShown())
        assert.is_false(frame.monkePointer:IsShown())
        SlashCmdList["MONKEDO"]("now off")
        assert.is_false(frame.monkeDriver:IsShown())
        SlashCmdList["MONKEDO"]("now on")
        C_SuperTrack.SetSuperTrackedQuestID(0)
        assert.is_false(frame.monkeDriver:IsShown())
        assert.is_true(frame.monkeIcon:IsShown())
    end)
end)
