-- Pick.lua: Monke pick against the fake quest log. Pick.Rank is pure and tested on its own;
-- the rest goes through C_QuestLog and C_SuperTrack the way the game would.

describe("Monke pick", function()
    local ns, Pick
    local DOT = " \194\183 "
    local DASH = " \226\128\148 "
    local GREY = "|cffb3b3b3" -- the Now line draws the distance in grey

    local function ids(list)
        local out = {}
        for i, candidate in ipairs(list) do
            out[i] = candidate.questID
        end
        return out
    end

    -- A quest in the fake log, `yards` away (nil: no distance unless `fields` gives one).
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

    local function nowLine()
        return ns.Now.frame.monkeLine:GetText()
    end

    before_each(function()
        WowStubs.reset()
        ns = WowStubs.load()
        WowStubs.login()
        Pick = ns.Pick
    end)

    describe("Rank", function()
        it("puts ready quests first, then unfinished ones, nearest first, unknown distance last", function()
            local ranked = Pick.Rank({
                { questID = 1, distanceSq = 400 },
                { questID = 2, distanceSq = 100, ready = true },
                { questID = 3 },
                { questID = 4, distanceSq = 25 },
                { questID = 5, ready = true },
                { questID = 6, distanceSq = 900, ready = true },
                { questID = 7 },
                { questID = 8, ready = true },
            })
            assert.are.same({ 2, 6, 4, 1, 5, 8, 3, 7 }, ids(ranked))
        end)

        it("keeps quest-log order between equal distances", function()
            local ranked = Pick.Rank({
                { questID = 1, distanceSq = 100 },
                { questID = 2, distanceSq = 100 },
                { questID = 3, distanceSq = 100 },
                { questID = 4, distanceSq = 100 },
                { questID = 5, distanceSq = 100 },
                { questID = 6, distanceSq = 100 },
                { questID = 7, distanceSq = 100 },
                { questID = 8, distanceSq = 100 },
                { questID = 9, distanceSq = 100 },
                { questID = 10, distanceSq = 100 },
            })
            assert.are.same({ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 }, ids(ranked))
        end)

        it("returns a new list and leaves its input alone", function()
            local input = { { questID = 1, distanceSq = 900 }, { questID = 2, distanceSq = 100 } }
            local ranked = Pick.Rank(input)
            assert.are.same({ 2, 1 }, ids(ranked))
            assert.are.same({ 1, 2 }, ids(input))
            assert.is_true(ranked ~= input)
            assert.are.same({}, Pick.Rank({}))
            assert.are.same({}, Pick.Rank(nil))
        end)

        it("treats a non-number, NaN, negative or secret distance as unknown", function()
            _G.issecretvalue = function(value)
                return value == 4
            end
            local ranked = Pick.Rank({
                { questID = 1, distanceSq = "near" },
                { questID = 2, distanceSq = 0 / 0 },
                { questID = 3, distanceSq = -1 },
                { questID = 4, distanceSq = 4 },
                { questID = 5, distanceSq = 10000 },
            })
            assert.are.same({ 5, 1, 2, 3, 4 }, ids(ranked))
        end)
    end)

    describe("Candidates", function()
        it("skip headers, hidden entries, world and bonus objectives, bounties, internal and failed quests", function()
            WowStubs.addLogQuest({ title = "Elwynn Forest", isHeader = true })
            quest(10, 50)
            quest(11, 50, { isHidden = true })
            quest(12, 50, { isTask = true })
            quest(13, 50, { isBounty = true })
            quest(14, 50, { isInternalOnly = true })
            quest(15, 50, { failed = true })
            quest(16, nil, { ready = true })
            quest(17, 50, { complete = true })
            local list = Pick.Candidates()
            assert.are.same({ 10, 16, 17 }, ids(list))
            assert.are.equal("Quest 10", list[1].title)
            assert.are.equal(2500, list[1].distanceSq)
            assert.is_false(list[1].ready)
            assert.is_nil(list[2].distanceSq)
            assert.is_true(list[2].ready)
            assert.is_true(list[3].ready)
        end)

        it("treat no position, another continent, a non-number and a secret distance as unknown", function()
            _G.issecretvalue = function(value)
                return value == 4096
            end
            quest(20)
            quest(21, nil, { distanceSq = 100, onContinent = false })
            quest(22, nil, { distanceSq = "far" })
            quest(23, nil, { distanceSq = 4096 })
            quest(24, 10)
            local list = Pick.Candidates()
            assert.are.same({ 20, 21, 22, 23, 24 }, ids(list))
            for i = 1, 4 do
                assert.is_nil(list[i].distanceSq)
            end
            assert.are.equal(100, list[5].distanceSq)
        end)

        it("never compares a secret onContinent", function()
            _G.issecretvalue = function(value)
                return value == true
            end
            quest(25, 10)
            assert.is_nil(Pick.Candidates()[1].distanceSq)
        end)

        it("are empty on a client without the quest log API", function()
            _G.C_QuestLog = nil
            assert.are.same({}, Pick.Candidates())
            assert.is_false(Pick.IsReady(1))
            assert.is_nil(Pick.DistanceSq(1))
        end)
    end)

    describe("Next", function()
        it("super-tracks the best quest, so Blizzard's arrow points there, with a short sound", function()
            quest(30, 200)
            quest(31, 50)
            quest(32, 400, { ready = true })
            assert.are.equal(32, Pick.Next())
            assert.are.equal(32, WowStubs.superTracked)
            assert.are.same({ 875 }, WowStubs.sounds)
        end)

        it("moves on from the quest already super-tracked, then tracks nothing, then starts over", function()
            quest(30, 200)
            quest(31, 50)
            quest(32, 400, { ready = true }) -- ranking: 32, 31, 30
            WowStubs.superTracked = 31
            assert.are.equal(30, Pick.Next())
            assert.are.equal(0, Pick.Next()) -- after the last: nothing, so Blizzard's arrow goes away
            assert.are.equal(0, WowStubs.superTracked)
            assert.are.equal("Nothing now. Click: Monke pick.", nowLine())
            assert.are.equal(32, Pick.Next())
            assert.are.equal(31, Pick.Next())
            assert.are.equal(4, #WowStubs.sounds)
        end)

        it("starts at the top when the super-tracked quest is not one it would pick", function()
            quest(30, 200)
            quest(31, 50)
            quest(99, 1, { isTask = true })
            WowStubs.superTracked = 99
            assert.are.equal(31, Pick.Next())
        end)

        it("with one quest, swaps between it and nothing", function()
            quest(30, 200)
            assert.are.equal(30, Pick.Next())
            assert.are.equal(0, Pick.Next())
            assert.are.equal(30, Pick.Next())
        end)

        it("the Now line follows the pick through SUPER_TRACKING_CHANGED", function()
            quest(214, 123, { title = "Red Silk Bandanas", objectives = {
                { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
            } })
            WowStubs.printed = {}
            Pick.Next()
            assert.are.equal("Grab 7 more Red Silk Bandana" .. GREY .. DOT .. "120 yd|r", nowLine())
            assert.are.same({}, WowStubs.printed) -- the line shows it; no chat
        end)

        it("says so on the Now line when there is nothing to pick", function()
            assert.is_nil(Pick.Next())
            assert.are.equal("No quest. Monke go find quest giver.", nowLine())
            assert.are.equal(0, WowStubs.superTracked)
            assert.are.same({}, WowStubs.sounds)
            WowStubs.advance(3)
            assert.are.equal("Nothing now. Click: Monke pick.", nowLine())
        end)

        it("says so in one chat line, in the player's voice, when the Now line is off", function()
            ns.Core.Set("nowLine", false)
            ns.Core.Set("voice", "plain")
            WowStubs.printed = {}
            assert.is_nil(Pick.Next())
            assert.are.same({ "|cffd2a679Monke Do|r: No quests to pick. Find a quest giver." }, WowStubs.printed)
        end)

        it("reports the pick in one chat line when the Now line is off", function()
            ns.Core.Set("nowLine", false)
            quest(214, 123, { title = "Red Silk Bandanas", objectives = {
                { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
            } })
            WowStubs.printed = {}
            assert.are.equal(214, Pick.Next())
            assert.are.same({ "|cffd2a679Monke Do|r: Monke pick: Red Silk Bandanas" .. DASH ..
                "Grab 7 more Red Silk Bandana" .. DOT .. "120 yd" }, WowStubs.printed)
            WowStubs.printed = {}
            assert.are.equal(0, Pick.Next())
            assert.are.same({ "|cffd2a679Monke Do|r: Monke pick: nothing. Monke rest." }, WowStubs.printed)
            ns.Core.Set("voice", "plain")
            WowStubs.printed = {}
            Pick.Next()
            assert.are.same({ "|cffd2a679Monke Do|r: Picked: Red Silk Bandanas" .. DASH ..
                "Collect 7 more Red Silk Bandana" .. DOT .. "120 yd" }, WowStubs.printed)
        end)

        it("works on a client without C_SuperTrack: the Now line shows the pick", function()
            WowStubs.reset()
            _G.C_SuperTrack = nil
            ns = WowStubs.load()
            WowStubs.login()
            Pick = ns.Pick
            quest(30, 200)
            quest(31, 50)
            assert.are.equal(31, Pick.Next())
            assert.are.equal("Grab 5 Thing" .. GREY .. DOT .. "50 yd|r", nowLine())
            assert.are.equal(30, Pick.Next()) -- cycling goes on from the remembered pick
            assert.are.equal("Grab 5 Thing" .. GREY .. DOT .. "200 yd|r", nowLine())
        end)

        it("stays quiet without PlaySound or SOUNDKIT", function()
            quest(30, 200)
            _G.SOUNDKIT = nil
            assert.has_no.errors(function() Pick.Next() end)
            _G.PlaySound = nil
            assert.has_no.errors(function() Pick.Next() end)
            assert.are.same({}, WowStubs.sounds)
        end)

        it("does not break with no quest log API at all", function()
            _G.C_QuestLog = nil
            assert.has_no.errors(function() Pick.Next() end)
        end)
    end)

    describe("wiring", function()
        it("the key binding, /monke pick and a left-click on the Now line all pick", function()
            quest(30, 200)
            quest(31, 50)
            assert.are.equal(31, MonkeDo_Pick())
            SlashCmdList["MONKEDO"]("pick")
            assert.are.equal(30, WowStubs.superTracked)
            WowStubs.click(ns.Now.frame, "LeftButton")
            assert.are.equal(0, WowStubs.superTracked)
            WowStubs.click(ns.Now.frame, "LeftButton")
            assert.are.equal(31, WowStubs.superTracked)
        end)

        it("Bindings.xml files MONKEDO_PICK under AddOns and calls MonkeDo_Pick", function()
            local file = assert(io.open("addon/MonkeDo/Bindings.xml", "r"))
            local xml = file:read("*a")
            file:close()
            assert.is_not_nil(xml:find("^<Bindings>"))
            assert.is_not_nil(xml:find('<Binding name="MONKEDO_PICK" category="ADDONS">', 1, true))
            assert.is_nil(xml:find("header=", 1, true)) -- the keybinding screen draws headers as blank rows
            assert.is_not_nil(xml:find("%s+MonkeDo_Pick%(%)%s+</Binding>"))
            assert.is_not_nil(xml:find("</Bindings>%s*$"))
            assert.are.equal("Monke Do: which quest now?", BINDING_NAME_MONKEDO_PICK)
        end)
    end)
end)
