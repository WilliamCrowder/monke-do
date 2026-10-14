-- Now.lua against the fake client: what the line says, when it redraws, the clicks, the
-- resume cue and the setting. Real layout, fonts and the look of the pulse stay on the
-- in-game checklist.

describe("Now line", function()
    local ns, Now, frame
    local DOT = " \194\183 "
    local GREY = "|cffb3b3b3"
    local INVITE = "Nothing now. Click: Monke pick."

    -- Quest 214 with DB wording that differs from the rule-based bullet, so the specs can
    -- tell which one the line used.
    local RECORD_214 = {
        l = "Bad men wear red hankies. Scout lady want them. Take hankies.",
        p = "The Defias wear red bandanas. Scout Riell wants ten of them.",
        t = { "Take 10 Red Silk Bandana off bad men.", "Go back to Scout Riell." },
        n = 1, e = "Scout Riell", v = 3,
    }
    local TAKE = "Take 7 more Red Silk Bandana off bad men" -- 3 of 10 done

    -- The step, then the distance in grey, as the line draws them.
    local function at(step, distance)
        return step .. GREY .. DOT .. distance .. "|r"
    end

    -- Quest 214 in the fake log, 123 yards away unless `fields` says otherwise.
    local function bandanas(fields)
        local entry = fields or {}
        entry.questID = 214
        entry.title = "Red Silk Bandanas"
        entry.objectives = entry.objectives or {
            { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
        }
        entry.distanceSq = entry.distanceSq or 123 * 123
        return WowStubs.addLogQuest(entry)
    end

    local function track(questID)
        C_SuperTrack.SetSuperTrackedQuestID(questID) -- fires SUPER_TRACKING_CHANGED like the game
    end

    local function line()
        return frame.monkeLine:GetText()
    end

    -- A GameTooltip that records its lines, as the Now line fills it on hover.
    local function installTip()
        local tip = { lines = {} }
        function tip:SetOwner(owner, anchor) self.owner, self.anchor = owner, anchor end
        function tip:SetText(text) self.lines = { text } end
        function tip:AddLine(text) self.lines[#self.lines + 1] = text end
        function tip:Show() self.shown = true end
        function tip:Hide() self.shown = false end
        _G.GameTooltip = tip
        return tip
    end

    local function tipLines()
        local tip = installTip()
        frame.scripts.OnEnter(frame)
        return tip.lines
    end

    local function activeTickers()
        local count = 0
        for _, timer in ipairs(WowStubs.timers) do
            if timer.every and not timer.handle.cancelled then
                count = count + 1
            end
        end
        return count
    end

    local function start()
        ns = WowStubs.load()
        WowStubs.login()
        Now = ns.Now
        frame = Now.frame
    end

    -- The default spot: the strip's centre 230 above the bottom middle of the screen.
    local function atHome()
        assert.are.same({ "CENTER", UIParent, "BOTTOM", 0, 230 }, frame.point)
    end

    before_each(function()
        WowStubs.reset()
        _G.MonkeDB = { [214] = RECORD_214 }
        start()
    end)

    describe("the frame", function()
        it("is the addon's own frame, at the bottom middle of the screen", function()
            assert.are.equal("MonkeDoNowFrame", frame.name)
            assert.are.equal("Button", frame.frameType)
            assert.are.equal(UIParent, frame.parent)
            atHome()
            assert.is_true(frame:IsShown())
        end)

        it("moves with a left-drag, stays on screen and takes the left button only", function()
            assert.is_true(frame.movable)
            assert.is_true(frame.clamped)
            assert.is_true(frame.mouse)
            assert.are.same({ "LeftButton" }, frame.dragButtons)
            assert.are.same({ "LeftButtonUp" }, frame.clickButtons)
        end)

        it("is one line that never wraps, after the monke icon", function()
            assert.is_false(frame.monkeLine.wordWrap)
            assert.are.equal(1, frame.monkeLine.maxLines)
            assert.are.equal("Interface\\AddOns\\MonkeDo\\Media\\icon.png", frame.monkeIcon.path)
        end)

        it("is a dark strip with a gold hairline round it", function()
            assert.are.equal(4, #frame.monkeEdges)
            for _, edge in ipairs(frame.monkeEdges) do
                assert.are.same({ 1, 0.82, 0, 0.5 }, edge.color)
                assert.is_true(edge.height == 1 or edge.width == 1)
            end
        end)

        it("is as wide as its words, up to a limit, and stays centred", function()
            local words = frame.monkeLine:GetWidth() -- the invitation
            assert.are.equal(6 * #INVITE + 1, words) -- the fake client: 6 px a character
            assert.are.equal(5 + 18 + 9 + words + 5, frame:GetWidth())
            bandanas()
            track(214) -- the grey colour code takes no room
            assert.are.equal(6 * #(TAKE .. DOT .. "120 yd") + 1, frame.monkeLine:GetWidth())
            Now.Say(("Monke say a very long thing. "):rep(8))
            assert.are.equal(310, frame.monkeLine:GetWidth())
            atHome()
        end)
    end)

    describe("what it says", function()
        it("invites a pick when nothing is tracked, and the click picks", function()
            assert.are.equal(INVITE, line())
            bandanas()
            WowStubs.click(frame, "LeftButton")
            assert.are.equal(214, WowStubs.superTracked)
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("follows the super-tracked quest as soon as the game says it changed", function()
            bandanas()
            WowStubs.superTracked = 214 -- set behind the addon's back: nothing redraws yet
            assert.are.equal(INVITE, line())
            WowStubs.fire("SUPER_TRACKING_CHANGED")
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("ignores a super-tracked quest that is not in the quest log", function()
            track(9999)
            assert.are.equal(INVITE, line())
        end)

        it("uses the DB wording in monke voice and the rules in plain voice, and switches live", function()
            bandanas()
            track(214)
            assert.are.equal(at(TAKE, "120 yd"), line())
            ns.Core.Set("voice", "plain")
            assert.are.equal(at("Collect 7 more Red Silk Bandana", "120 yd"), line())
            ns.Core.Set("voice", "monke")
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("names the first unfinished objective and what is left of it", function()
            WowStubs.addLogQuest({ questID = 300, title = "Kobolds and Gold", distanceSq = 2500, objectives = {
                { text = "Kobold Vermin slain: 10/10", type = "monster", finished = true, numFulfilled = 10, numRequired = 10 },
                { text = "", type = "item", finished = false, numFulfilled = 0, numRequired = 1 }, -- not loaded yet
                { text = "Gold Dust: 2/10", type = "item", finished = false, numFulfilled = 2, numRequired = 10 },
            } })
            track(300)
            assert.are.equal(at("Grab 8 more Gold Dust", "50 yd"), line())
        end)

        it("says the whole amount before the first one, and the game's progress for anything else", function()
            bandanas({ objectives = {
                { text = "0/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 0, numRequired = 10 },
            } })
            track(214)
            assert.are.equal(at("Take 10 Red Silk Bandana off bad men", "120 yd"), line())
            WowStubs.addLogQuest({ questID = 500, title = "Thin the Wolves", objectives = {
                { text = "Wolves culled", type = "progressbar", finished = false, percent = 45 },
            } })
            track(500)
            assert.are.equal("Do the thing: Wolves culled (45%)", line())
        end)

        it("redraws once per burst of QUEST_LOG_UPDATE", function()
            local entry = bandanas()
            track(214)
            entry.objectives[1].text = "4/10 Red Silk Bandana"
            entry.objectives[1].numFulfilled = 4
            local sets = frame.monkeLine.setCount
            for _ = 1, 5 do
                WowStubs.fire("QUEST_LOG_UPDATE")
            end
            assert.are.equal(at(TAKE, "120 yd"), line())
            WowStubs.advance(0.3)
            assert.are.equal(at("Take 6 more Red Silk Bandana off bad men", "120 yd"), line())
            assert.are.equal(sets + 1, frame.monkeLine.setCount)
        end)

        it("shows the turn-in line once the quest is ready", function()
            bandanas({ ready = true })
            track(214)
            assert.are.equal(at("Go back to Scout Riell", "120 yd"), line())
            ns.Core.Set("voice", "plain")
            assert.are.equal(at("Return to Scout Riell", "120 yd"), line())
        end)

        it("shows the turn-in line when every objective is done, before the game says ready", function()
            bandanas({ onContinent = false, objectives = {
                { text = "10/10 Red Silk Bandana", type = "item", finished = true, numFulfilled = 10, numRequired = 10 },
            } })
            track(214)
            assert.are.equal("Go back to Scout Riell.", line())
        end)

        it("shows the turn-in line for a quest with no objectives", function()
            WowStubs.addLogQuest({ questID = 400, title = "A Letter", objectives = {} })
            track(400)
            assert.are.equal("Go back. Get shiny.", line())
        end)

        it("keeps the game's route off the line and in the tooltip, in the player's voice", function()
            bandanas({ waypoint = "Take the boat to Menethil Harbor" })
            track(214)
            assert.are.equal(at(TAKE, "120 yd"), line())
            assert.are.equal("Way: Take the boat to Menethil Harbor", tipLines()[3])
            ns.Core.Set("voice", "plain")
            assert.are.equal("Next: Take the boat to Menethil Harbor", tipLines()[3])
        end)

        it("leaves out a route that is empty or secret", function()
            _G.issecretvalue = function(value)
                return value == "Secret way"
            end
            bandanas({ waypoint = "" })
            track(214)
            assert.are.equal(4, #tipLines()) -- title, whole line, click, drag
            WowStubs.log[1].waypoint = "Secret way"
            assert.are.equal(4, #tipLines())
        end)
    end)

    describe("distance", function()
        it("reads close, then tens of yards, then hundreds", function()
            assert.are.equal("close", Now.FormatDistance(29 * 29, "monke"))
            assert.are.equal("nearby", Now.FormatDistance(0, "plain"))
            assert.are.equal("30 yd", Now.FormatDistance(30 * 30, "monke"))
            assert.are.equal("120 yd", Now.FormatDistance(123 * 123, "monke"))
            assert.are.equal("130 yd", Now.FormatDistance(125 * 125, "plain"))
            assert.are.equal("1000 yd", Now.FormatDistance(996 * 996, "monke"))
            assert.are.equal("1200 yd", Now.FormatDistance(1234 * 1234, "monke"))
        end)

        it("is unknown for nothing, a non-number, NaN, a negative or a secret value", function()
            _G.issecretvalue = function(value)
                return value == 2500
            end
            assert.is_nil(Now.FormatDistance(nil, "monke"))
            assert.is_nil(Now.FormatDistance("far", "monke"))
            assert.is_nil(Now.FormatDistance(0 / 0, "monke"))
            assert.is_nil(Now.FormatDistance(-1, "monke"))
            assert.is_nil(Now.FormatDistance(2500, "monke"))
        end)

        it("is left off the line when unknown", function()
            bandanas({ onContinent = false })
            track(214)
            assert.are.equal(TAKE .. ".", line())
        end)

        it("follows the player once a second", function()
            local entry = bandanas()
            track(214)
            entry.distanceSq = 20 * 20
            WowStubs.advance(0.5)
            assert.are.equal(at(TAKE, "120 yd"), line())
            WowStubs.advance(0.5)
            assert.are.equal(at(TAKE, "close"), line())
            entry.distanceSq = 400 * 400
            WowStubs.advance(1)
            assert.are.equal(at(TAKE, "400 yd"), line())
        end)

        it("runs its ticker only while a quest is on the line", function()
            assert.are.equal(0, activeTickers())
            bandanas()
            track(214)
            assert.are.equal(1, activeTickers())
            track(0)
            assert.are.equal(0, activeTickers())
        end)
    end)

    describe("clicks", function()
        -- Blizzard's map code run from addon code leaves the map and tracker state tainted, and
        -- their next redraw in combat is blocked; the M key shows the super-tracked quest.
        it("right-click does nothing, and the line never calls Blizzard's map code", function()
            _G.QuestMapFrame_OpenToQuestDetails = function()
                error("the Now line must not call Blizzard's map code")
            end
            WowStubs.click(frame, "RightButton")
            assert.are.equal(INVITE, line())
            assert.are.equal(0, WowStubs.superTracked)
            bandanas()
            track(214)
            WowStubs.click(frame, "RightButton")
            assert.are.equal(214, WowStubs.superTracked)
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("a pick replaces a message at once", function()
            bandanas()
            track(214)
            Now.Say("Hello")
            assert.are.equal("Hello", line())
            WowStubs.click(frame, "LeftButton") -- the only quest again: no event from the game
            assert.are.equal(at(TAKE, "120 yd"), line())
            WowStubs.log = {}
            WowStubs.click(frame, "LeftButton") -- nothing left to pick
            assert.are.equal("No quest. Monke go find quest giver.", line())
            WowStubs.addLogQuest({ questID = 400, title = "A Letter", objectives = {} })
            WowStubs.click(frame, "LeftButton") -- a new quest: SUPER_TRACKING_CHANGED
            assert.are.equal(400, WowStubs.superTracked)
            assert.are.equal("Go back. Get shiny.", line())
        end)

        it("the tooltip names the quest, gives the whole line and the actions, above the line", function()
            local tip = installTip()
            frame.scripts.OnEnter(frame)
            assert.are.same({ "Monke Do", "Click: Monke pick quest. Click again: other quest.", "Drag: move line." },
                tip.lines)
            bandanas()
            track(214)
            frame.scripts.OnEnter(frame)
            assert.are.equal(frame, tip.owner)
            assert.are.equal("ANCHOR_TOP", tip.anchor)
            assert.are.same({ "Red Silk Bandanas", TAKE .. DOT .. "120 yd",
                "Click: Monke pick quest. Click again: other quest.", "Drag: move line." }, tip.lines)
            assert.is_true(tip.shown)
            frame.scripts.OnLeave(frame)
            assert.is_false(tip.shown)
        end)
    end)

    describe("position", function()
        it("keeps where a drag leaves it by its centre, and a drag is not a click", function()
            bandanas()
            frame.scripts.OnDragStart(frame)
            assert.is_true(frame.moving)
            frame.center = { 700, 260 } -- where the client leaves it (UIParent's centre is 512)
            frame.scripts.OnDragStop(frame)
            assert.is_false(frame.moving)
            assert.are.same({ point = "CENTER", relativePoint = "BOTTOM", x = 188, y = 260 }, ns.Core.Get("nowPoint"))
            assert.are.same({ "CENTER", UIParent, "BOTTOM", 188, 260 }, frame.point)
            WowStubs.click(frame, "LeftButton") -- the mouse-up that ended the drag
            assert.are.equal(0, WowStubs.superTracked)
            WowStubs.advance(1)
            WowStubs.click(frame, "LeftButton")
            assert.are.equal(214, WowStubs.superTracked)
        end)

        it("a drag that never finished does not block the next click", function()
            bandanas()
            frame.scripts.OnDragStart(frame) -- and no OnDragStop: the frame was hidden mid-drag
            frame:RunScript("OnHide")
            assert.is_false(frame.moving)
            frame.scripts.OnDragStart(frame)
            frame:RunScript("OnMouseDown", "LeftButton") -- the next press
            WowStubs.click(frame, "LeftButton")
            assert.are.equal(214, WowStubs.superTracked)
        end)

        it("without a centre to read, keeps the anchor a drag leaves on UIParent, and no other", function()
            frame.scripts.OnDragStart(frame)
            frame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 500, -300)
            frame.scripts.OnDragStop(frame)
            assert.are.same({ point = "TOPLEFT", relativePoint = "TOPLEFT", x = 500, y = -300 }, ns.Core.Get("nowPoint"))
            ns.Core.Store("nowPoint", nil)
            frame.scripts.OnDragStart(frame)
            frame:SetPoint("TOPLEFT", ObjectiveTrackerFrame, "BOTTOMLEFT", 0, 0)
            frame.scripts.OnDragStop(frame)
            assert.is_nil(ns.Core.Get("nowPoint"))
        end)

        it("comes back where it was saved; /monke now reset puts it back at the bottom middle", function()
            WowStubs.reset()
            _G.MonkeDoDB = { nowPoint = { point = "CENTER", relativePoint = "BOTTOM", x = 10, y = 400 } }
            start()
            assert.are.same({ "CENTER", UIParent, "BOTTOM", 10, 400 }, frame.point)
            SlashCmdList["MONKEDO"]("now reset")
            atHome()
            assert.is_nil(ns.Core.Get("nowPoint"))
        end)

        it("ignores a saved spot that makes no sense", function()
            WowStubs.reset()
            _G.MonkeDoDB = { nowPoint = { point = "MIDDLE", relativePoint = "CENTER", x = "a", y = 1 } }
            start()
            atHome()
        end)
    end)

    describe("the setting", function()
        it("off hides the line and stops the ticker; on brings both back", function()
            bandanas()
            track(214)
            assert.are.equal(1, activeTickers())
            SlashCmdList["MONKEDO"]("now off")
            assert.is_false(frame:IsShown())
            assert.are.equal(0, activeTickers())
            assert.is_false(Now.IsActive())
            WowStubs.fire("SUPER_TRACKING_CHANGED")
            WowStubs.fire("QUEST_LOG_UPDATE")
            WowStubs.advance(2)
            assert.is_false(frame:IsShown())
            assert.are.equal(0, activeTickers())
            SlashCmdList["MONKEDO"]("now on")
            assert.is_true(frame:IsShown())
            assert.are.equal(1, activeTickers())
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("hides while the original text shows, and comes back with Monke Do text", function()
            bandanas()
            track(214)
            ns.Core.ToggleOriginal() -- "Monke don't": the stock interface
            assert.is_false(frame:IsShown())
            assert.are.equal(0, activeTickers())
            assert.is_false(Now.IsActive())
            WowStubs.printed = {}
            ns.Pick.Next() -- the key still picks; the answer goes to chat
            assert.are.equal(1, #WowStubs.printed)
            WowStubs.fire("QUEST_LOG_UPDATE")
            WowStubs.advance(2)
            assert.is_false(frame:IsShown())
            ns.Core.ToggleOriginal() -- "OK, monke do"
            assert.is_true(frame:IsShown())
            assert.are.equal(1, activeTickers())
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("off, the line takes no messages, so callers fall back to chat", function()
            ns.Core.Set("nowLine", false)
            assert.is_false(Now.Say("Hello"))
            ns.Core.Set("nowLine", true)
            assert.is_true(Now.Say("Hello"))
            assert.are.equal("Hello", line())
        end)
    end)

    describe("fights", function()
        it("fades during a fight, shows whole under the mouse, and keeps counting", function()
            local entry = bandanas()
            track(214)
            assert.are.equal(1, frame:GetAlpha())
            WowStubs.fire("PLAYER_REGEN_DISABLED") -- before the lockdown starts, as the game sends it
            WowStubs.inCombat = true
            assert.are.equal(0.35, frame:GetAlpha())
            installTip()
            frame.scripts.OnEnter(frame)
            assert.are.equal(1, frame:GetAlpha())
            frame.scripts.OnLeave(frame)
            assert.are.equal(0.35, frame:GetAlpha())
            entry.objectives[1].text = "4/10 Red Silk Bandana"
            entry.objectives[1].numFulfilled = 4
            WowStubs.fire("QUEST_LOG_UPDATE")
            WowStubs.advance(0.3)
            assert.are.equal(at("Take 6 more Red Silk Bandana off bad men", "120 yd"), line())
            assert.are.equal(0.35, frame:GetAlpha())
            WowStubs.inCombat = false
            WowStubs.fire("PLAYER_REGEN_ENABLED")
            assert.are.equal(1, frame:GetAlpha())
        end)

        it("starts faded after a reload in the middle of a fight", function()
            WowStubs.reset()
            _G.MonkeDB = { [214] = RECORD_214 }
            WowStubs.inCombat = true
            start()
            assert.are.equal(0.35, frame:GetAlpha())
        end)
    end)

    describe("resume cue", function()
        it("pulses when a fight ends and there is a task to show", function()
            bandanas()
            track(214)
            WowStubs.fire("PLAYER_REGEN_DISABLED")
            WowStubs.fire("PLAYER_REGEN_ENABLED")
            assert.are.equal(1, frame.monkePulse.plays)
            assert.is_true(frame.monkePulse:IsPlaying())
        end)

        it("pulses a moment after a loading screen", function()
            bandanas()
            track(214)
            WowStubs.fire("PLAYER_ENTERING_WORLD")
            assert.is_nil(frame.monkePulse.plays)
            WowStubs.advance(1)
            assert.are.equal(1, frame.monkePulse.plays)
        end)

        it("stays still with nothing tracked, with the line off, and in combat", function()
            WowStubs.fire("PLAYER_REGEN_ENABLED")
            WowStubs.fire("PLAYER_ENTERING_WORLD")
            WowStubs.advance(2)
            assert.is_nil(frame.monkePulse.plays)

            bandanas()
            track(214)
            ns.Core.Set("nowLine", false)
            WowStubs.fire("PLAYER_REGEN_ENABLED")
            WowStubs.fire("PLAYER_ENTERING_WORLD")
            WowStubs.advance(2)
            assert.is_nil(frame.monkePulse.plays)

            ns.Core.Set("nowLine", true)
            WowStubs.inCombat = true
            WowStubs.fire("PLAYER_ENTERING_WORLD")
            WowStubs.advance(2)
            assert.is_nil(frame.monkePulse.plays)
        end)
    end)

    describe("on a thinner client", function()
        local function fresh(remove)
            WowStubs.reset()
            _G.MonkeDB = { [214] = RECORD_214 }
            remove()
            ns = WowStubs.load()
            assert.has_no.errors(WowStubs.login)
            Now = ns.Now
            frame = Now.frame
        end

        it("keeps its place without an objective tracker", function()
            fresh(function() _G.ObjectiveTrackerFrame = nil end)
            atHome()
            assert.are.equal(INVITE, line())
            SlashCmdList["MONKEDO"]("now reset")
            atHome()
        end)

        it("redraws at once and runs no timers without C_Timer", function()
            fresh(function() _G.C_Timer = nil end)
            local entry = bandanas()
            track(214)
            assert.are.equal(at(TAKE, "120 yd"), line())
            entry.objectives[1].text = "5/10 Red Silk Bandana"
            entry.objectives[1].numFulfilled = 5
            WowStubs.fire("QUEST_LOG_UPDATE")
            assert.are.equal(at("Take 5 more Red Silk Bandana off bad men", "120 yd"), line())
            Now.Say("Hello")
            assert.are.equal("Hello", line())
            WowStubs.fire("PLAYER_ENTERING_WORLD")
            WowStubs.advance(3)
            WowStubs.fire("QUEST_LOG_UPDATE") -- the message is over; the next redraw shows the quest
            assert.are.equal(at("Take 5 more Red Silk Bandana off bad men", "120 yd"), line())
            assert.are.equal(0, #WowStubs.timers)
        end)

        it("follows Monke pick without C_SuperTrack", function()
            fresh(function() _G.C_SuperTrack = nil end)
            bandanas()
            assert.are.equal(INVITE, line())
            WowStubs.click(frame, "LeftButton")
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)

        it("does nothing without UIParent, and Monke pick reports in chat", function()
            fresh(function() _G.UIParent = nil end)
            assert.is_nil(frame)
            assert.is_false(Now.IsActive())
            bandanas()
            WowStubs.printed = {}
            assert.are.equal(214, ns.Pick.Next())
            assert.are.equal(1, #WowStubs.printed)
            assert.is_not_nil(WowStubs.printed[1]:find("Monke pick: Red Silk Bandanas", 1, true))
        end)

        it("survives every optional global missing at once", function()
            fresh(function()
                _G.ObjectiveTrackerFrame, _G.C_SuperTrack, _G.C_Timer, _G.GetTime = nil, nil, nil, nil
                _G.InCombatLockdown, _G.PlaySound, _G.SOUNDKIT, _G.issecretvalue = nil, nil, nil, nil
                _G.QuestMapFrame_OpenToQuestDetails, _G.GameTooltip = nil, nil
            end)
            bandanas()
            assert.has_no.errors(function()
                WowStubs.click(frame, "LeftButton")
                WowStubs.click(frame, "RightButton")
                frame.scripts.OnEnter(frame)
                frame.scripts.OnLeave(frame)
                frame.scripts.OnDragStart(frame)
                frame.scripts.OnDragStop(frame)
                WowStubs.click(frame, "LeftButton")
                WowStubs.fire("PLAYER_ENTERING_WORLD")
                WowStubs.fire("PLAYER_REGEN_DISABLED")
                WowStubs.fire("PLAYER_REGEN_ENABLED")
                WowStubs.fire("QUEST_LOG_UPDATE")
                SlashCmdList["MONKEDO"]("now reset")
            end)
            assert.are.equal(at(TAKE, "120 yd"), line())
        end)
    end)
end)

describe("Now line and Monke pick globals", function()
    it("read only globals declared in .luacheckrc", function()
        local seen = WowStubs.trackGlobals(function()
            WowStubs.reset()
            local ns = WowStubs.load()
            WowStubs.login()
            WowStubs.addLogQuest({ questID = 214, title = "Red Silk Bandanas", distanceSq = 400, waypoint = "Go north",
                objectives = {
                    { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
                } })
            local frame = ns.Now.frame
            WowStubs.click(frame, "LeftButton")
            WowStubs.fire("QUEST_LOG_UPDATE")
            WowStubs.advance(2)
            frame.scripts.OnEnter(frame)
            frame.scripts.OnLeave(frame)
            WowStubs.click(frame, "RightButton")
            WowStubs.fire("PLAYER_REGEN_DISABLED")
            WowStubs.inCombat = true
            WowStubs.click(frame, "RightButton")
            WowStubs.inCombat = false
            WowStubs.fire("PLAYER_REGEN_ENABLED")
            WowStubs.fire("PLAYER_ENTERING_WORLD")
            WowStubs.advance(4)
            frame.scripts.OnDragStart(frame)
            frame.center = { 600, 300 }
            frame.scripts.OnDragStop(frame)
            ns.Core.HandleSlash("now off")
            ns.Pick.Next()
            ns.Core.HandleSlash("now on")
            ns.Core.HandleSlash("now reset")
            ns.Core.HandleSlash("pick")
            MonkeDo_Pick()
        end)
        local declared = WowStubs.declaredGlobals()
        -- Read by the fake client and the other modules through _G[name], not by these two.
        local scaffolding = { QuestDetailScrollFrame = true, QuestProgressScrollFrame = true,
            QuestRewardScrollFrame = true, QuestObjectiveTracker = true, CampaignQuestObjectiveTracker = true }
        local undeclared = {}
        for name in pairs(seen) do
            if not declared[name] and not scaffolding[name] then
                undeclared[#undeclared + 1] = name
            end
        end
        table.sort(undeclared)
        assert.are.same({}, undeclared)
    end)
end)
