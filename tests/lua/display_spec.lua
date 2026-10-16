-- Display.lua and Tracker.lua against the fake client. This proves the wiring and the
-- toggle contract; frame positions and real layout stay on the in-game checklist.

describe("Display", function()
    local ns
    local BULLET = "\226\128\162 "
    local HEADER_MONKE = "|cff000000Monke do:|r" -- Blizzard's header colour on parchment
    local HEADER_PLAIN = "|cff000000To do:|r"
    local GREY = "|cff4d4d4d" -- the finished-line grey that reads on parchment
    local HINT_MONKE = "|cff4d4d4dLong story? Poke Wrinkle.|r"
    local HINT_PLAIN = "|cff4d4d4dFull text: press Original.|r"

    local RECORD_214 = {
        l = "Bad men wear red hankies. Scout lady want them. Take hankies.",
        p = "The Defias wear red bandanas. Scout Riell wants ten of them.",
        t = { "Grab 10 Red Silk Bandana.", "Go back to Scout Riell." },
        n = 1, e = "Scout Riell", v = 3,
    }

    before_each(function()
        WowStubs.reset()
        _G.MonkeDB = { [214] = RECORD_214 }
        ns = WowStubs.load()
        WowStubs.login()
    end)

    it("replaces description and objectives on the quest giver page", function()
        WowStubs.showQuest("detail")
        assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
        assert.are.equal(
            BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Go back to Scout Riell.\n\nMonke get: 875 XP, 4s",
            QuestInfoObjectivesText:GetText())
        assert.are.equal(1, QuestDetailScrollFrame.scrollUpdates)
    end)

    it("works from the quest log and map details too", function()
        WowStubs.showQuest("log")
        assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
    end)

    it("the toggle restores Blizzard text byte for byte, and back", function()
        local quest = WowStubs.quest
        quest.description = "Line one.\n\n  Odd  spacing, $n.|cffff0000 colour|r \226\128\148 dash"
        WowStubs.showQuest("detail")
        assert.is_true(QuestInfoDescriptionText:GetText() ~= quest.description)

        ns.Core.ToggleOriginal()
        assert.are.equal(quest.description, QuestInfoDescriptionText:GetText())
        assert.are.equal(quest.objectivesText, QuestInfoObjectivesText:GetText())
        assert.are.equal("Quest Objectives", QuestInfoObjectivesHeader:GetText())

        ns.Core.ToggleOriginal()
        assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
        assert.are.equal("Monke do:", QuestInfoObjectivesHeader:GetText())
    end)

    -- Build 1.60.1.70338 fades the quest giver's description in and never clears the gradient
    -- afterwards (QuestFrameDetailPanel_OnShow / _OnUpdate in QuestFrame.lua).
    describe("description fade", function()
        local LONG = ("Blizzard tells a long story here. "):rep(12)

        it("plays over the Monke text", function()
            WowStubs.showQuest("detail")
            assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
            assert.are.equal(0, QuestInfoDescriptionText.gradient[1])
            WowStubs.fadeQuestText()
            assert.is_nil(QuestFrameDetailPanel.fading)
            assert.are.equal(0, WowStubs.hiddenCharacters(QuestInfoDescriptionText))
        end)

        it("shows all of Blizzard's text when toggled after the fade", function()
            WowStubs.quest.description = LONG
            WowStubs.showQuest("detail")
            WowStubs.fadeQuestText() -- stops just past the short Monke text
            ns.Core.ToggleOriginal()
            assert.are.equal(LONG, QuestInfoDescriptionText:GetText())
            assert.are.equal(0, WowStubs.hiddenCharacters(QuestInfoDescriptionText))
            ns.Core.ToggleOriginal()
            assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
            assert.are.equal(0, WowStubs.hiddenCharacters(QuestInfoDescriptionText))
        end)

        it("leaves a fade that is still running to Blizzard", function()
            WowStubs.quest.description = LONG
            WowStubs.showQuest("detail")
            WowStubs.fadeQuestText(0.25)
            local start = QuestInfoDescriptionText.gradient[1]
            ns.Core.ToggleOriginal()
            assert.are.equal(start, QuestInfoDescriptionText.gradient[1])
            WowStubs.fadeQuestText()
            assert.are.equal(0, WowStubs.hiddenCharacters(QuestInfoDescriptionText))
        end)

        it("does not leave the map details cut off where a quest giver's fade stopped", function()
            ns.Core.ToggleOriginal() -- Blizzard's own text throughout
            WowStubs.quest.description = "Short."
            WowStubs.showQuest("detail")
            WowStubs.fadeQuestText()
            WowStubs.quest.description = LONG
            WowStubs.showQuest("log")
            assert.are.equal(LONG, QuestInfoDescriptionText:GetText())
            assert.are.equal(0, WowStubs.hiddenCharacters(QuestInfoDescriptionText))
        end)
    end)

    it("restores the original even when Monke Do had emptied the description", function()
        ns.Core.Set("showLore", false) -- no lore and no group line: the description becomes ""
        WowStubs.showQuest("detail")
        assert.is_nil(QuestInfoDescriptionText:GetText())
        ns.Core.ToggleOriginal()
        assert.are.equal(WowStubs.quest.description, QuestInfoDescriptionText:GetText())
        ns.Core.ToggleOriginal()
        assert.is_nil(QuestInfoDescriptionText:GetText())
    end)

    it("shows the DB bullets on the quest giver page before the quest is in the log", function()
        WowStubs.quest.objectives = {}
        WowStubs.quest.onQuest = false
        WowStubs.showQuest("detail")
        assert.are.equal(
            BULLET .. "Grab 10 Red Silk Bandana.\n" .. BULLET .. "Go back to Scout Riell.\n\nMonke get: 875 XP, 4s",
            QuestInfoObjectivesText:GetText())
    end)

    it("stays on the original text for the next quest while toggled off", function()
        ns.Core.ToggleOriginal()
        WowStubs.showQuest("detail")
        assert.are.equal(WowStubs.quest.description, QuestInfoDescriptionText:GetText())
    end)

    it("never restores a previous quest's text", function()
        WowStubs.showQuest("detail")
        WowStubs.quest = {
            id = 999, description = "Second quest text.", objectivesText = "Kill things.", objectives = {},
            onQuest = false, groupSize = 0, xp = 0, money = 0, items = {}, choices = {},
        }
        WowStubs.showQuest("detail")
        ns.Core.ToggleOriginal()
        assert.are.equal("Second quest text.", QuestInfoDescriptionText:GetText())
        assert.are.equal("Kill things.", QuestInfoObjectivesText:GetText())
    end)

    it("puts Blizzard's objectives sentence where the lore goes for a quest with no DB entry", function()
        _G.MonkeDB = {}
        WowStubs.showQuest("detail")
        assert.are.equal(WowStubs.quest.objectivesText .. "\n" .. HINT_MONKE, QuestInfoDescriptionText:GetText())
        assert.are.equal(
            BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Go back. Get shiny.\n\nMonke get: 875 XP, 4s",
            QuestInfoObjectivesText:GetText())
        ns.Core.Set("voice", "plain")
        assert.are.equal(WowStubs.quest.objectivesText .. "\n" .. HINT_PLAIN, QuestInfoDescriptionText:GetText())
    end)

    it("does the same in the quest log and map details", function()
        _G.MonkeDB = {}
        WowStubs.showQuest("log")
        assert.are.equal(WowStubs.quest.objectivesText .. "\n" .. HINT_MONKE, QuestInfoDescriptionText:GetText())
        assert.are.equal(HEADER_MONKE .. "\n" .. BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Go back. Get shiny.",
            QuestInfoObjectivesText:GetText())
    end)

    it("never takes its own bullets for Blizzard's sentence on a redraw or a settings change", function()
        _G.MonkeDB = {}
        for _, kind in ipairs({ "detail", "log" }) do
            WowStubs.showQuest(kind)
            ns.Core.Set("groupWarning", false) -- any setting change redraws from what is on screen
            assert.are.equal(WowStubs.quest.objectivesText .. "\n" .. HINT_MONKE, QuestInfoDescriptionText:GetText())
            WowStubs.showQuest(kind) -- Blizzard redraws with fresh strings
            ns.Core.Set("groupWarning", true)
            assert.are.equal(WowStubs.quest.objectivesText .. "\n" .. HINT_MONKE, QuestInfoDescriptionText:GetText())
            ns.Core.ToggleOriginal()
            assert.are.equal(WowStubs.quest.description, QuestInfoDescriptionText:GetText())
            assert.are.equal(WowStubs.quest.objectivesText, QuestInfoObjectivesText:GetText())
            ns.Core.ToggleOriginal()
        end
    end)

    it("never shows a long description while Monke text is on", function()
        _G.MonkeDB = {}
        local long = ("The Defias Brotherhood has plagued Westfall for years. "):rep(8) .. "Bring me their bandanas."
        WowStubs.quest.description = long
        local function check(where)
            local text = QuestInfoDescriptionText:GetText() or ""
            assert.is_nil(text:find("Bring me their bandanas", 1, true), where)
            assert.is_true(#text < 200, where)
        end
        for _, kind in ipairs({ "detail", "log" }) do
            WowStubs.showQuest(kind)
            check(kind)
            ns.Core.Set("voice", "plain")
            check(kind .. " plain")
            ns.Core.Set("voice", "monke")
            WowStubs.showQuest(kind)
            check(kind .. " redraw")
        end
        -- A talk quest has no objectives sentence: the first sentence or two of the description.
        WowStubs.quest.objectivesText = ""
        for _, kind in ipairs({ "detail", "log" }) do
            WowStubs.showQuest(kind)
            assert.are.equal("The Defias Brotherhood has plagued Westfall for years. " ..
                "The Defias Brotherhood has plagued Westfall for years.\n" .. HINT_MONKE, QuestInfoDescriptionText:GetText())
            ns.Core.Set("groupWarning", false)
            check(kind .. " talk quest")
        end
        -- The toggle still has every word of it.
        ns.Core.ToggleOriginal()
        assert.are.equal(long, QuestInfoDescriptionText:GetText())
    end)

    it("cuts a talk quest's description from Blizzard's text on every redraw, never from its own", function()
        _G.MonkeDB = {}
        WowStubs.quest.objectivesText = ""
        WowStubs.quest.description = "The Defias Brotherhood " .. ("keeps raiding the farms of Westfall and "):rep(5) ..
            "nobody stops them."
        for _, kind in ipairs({ "detail", "log" }) do
            WowStubs.showQuest(kind)
            local first = QuestInfoDescriptionText:GetText()
            -- 23 + 3 x 40 characters, then the words that still fit in 159 and the ellipsis
            assert.are.equal("The Defias Brotherhood " .. ("keeps raiding the farms of Westfall and "):rep(3) ..
                "keeps raiding\226\128\166\n" .. HINT_MONKE, first)
            ns.Core.Set("groupWarning", false) -- redraws from what is on screen, which is our text now
            assert.are.equal(first, QuestInfoDescriptionText:GetText())
            ns.Core.Set("groupWarning", true)
        end
    end)

    it("keeps the no-lore setting as it was: no lore section at all", function()
        _G.MonkeDB = {}
        ns.Core.Set("showLore", false)
        WowStubs.showQuest("detail")
        assert.is_nil(QuestInfoDescriptionText:GetText())
        WowStubs.quest.groupSize = 3
        WowStubs.showQuest("log")
        assert.are.equal("|cffb01010Bring 2 friends. Big danger.|r", QuestInfoDescriptionText:GetText())
    end)

    it("relabels the Quest Objectives header on the quest giver page, and the toggle puts it back", function()
        WowStubs.showQuest("detail")
        assert.are.equal("Monke do:", QuestInfoObjectivesHeader:GetText())
        ns.Core.ToggleOriginal()
        assert.are.equal("Quest Objectives", QuestInfoObjectivesHeader:GetText())
        ns.Core.ToggleOriginal()
        assert.are.equal("Monke do:", QuestInfoObjectivesHeader:GetText())
        ns.Core.Set("voice", "plain")
        assert.are.equal("To do:", QuestInfoObjectivesHeader:GetText())
        WowStubs.showQuest("detail") -- Blizzard never rewrites a header: it must not become "the original"
        ns.Core.ToggleOriginal()
        assert.are.equal("Quest Objectives", QuestInfoObjectivesHeader:GetText())
    end)

    it("never leaves its header label behind for a view or a mode that does not want it", function()
        WowStubs.showQuest("detail")
        WowStubs.showQuest("log") -- the log view has no use for that header: it gets Blizzard's back
        assert.are.equal("Quest Objectives", QuestInfoObjectivesHeader:GetText())
        WowStubs.showQuest("detail")
        assert.are.equal("Monke do:", QuestInfoObjectivesHeader:GetText())
        WowStubs.showQuest("reward")
        ns.Core.ToggleOriginal() -- toggled while another page is up
        WowStubs.showQuest("detail")
        assert.are.equal("Quest Objectives", QuestInfoObjectivesHeader:GetText())
        assert.are.equal("Description", QuestInfoDescriptionHeader:GetText())
    end)

    it("gives plain voice the DB task list on the quest giver page before the quest is accepted", function()
        local record = { l = RECORD_214.l, p = RECORD_214.p, t = RECORD_214.t, tp = { "Collect 10 Red Silk Bandana." },
            n = 1, e = "Scout Riell", v = 3 }
        _G.MonkeDB = { [214] = record }
        ns.Core.Set("voice", "plain")
        WowStubs.quest.objectives = {}
        WowStubs.quest.onQuest = false
        WowStubs.showQuest("detail")
        assert.are.equal(
            BULLET .. "Collect 10 Red Silk Bandana.\n" .. BULLET .. "Return to Scout Riell.\n\nRewards: 875 XP, 4s",
            QuestInfoObjectivesText:GetText())
        assert.are.equal("To do:", QuestInfoObjectivesHeader:GetText())

        record.tp = { 42 } -- malformed: tp is dropped, the rest of the record still counts
        WowStubs.showQuest("detail")
        assert.are.equal(BULLET .. "Return to Scout Riell.\n\nRewards: 875 XP, 4s", QuestInfoObjectivesText:GetText())
        assert.are.equal(RECORD_214.p, QuestInfoDescriptionText:GetText())
    end)

    it("does not break with no database at all", function()
        _G.MonkeDB = nil
        assert.has_no.errors(function() WowStubs.showQuest("detail") end)
    end)

    it("switches voice live", function()
        WowStubs.showQuest("detail")
        ns.Core.Set("voice", "plain")
        assert.are.equal(RECORD_214.p, QuestInfoDescriptionText:GetText())
        assert.are.equal(
            BULLET .. "Collect 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Return to Scout Riell.\n\nRewards: 875 XP, 4s",
            QuestInfoObjectivesText:GetText())
    end)

    it("prepends the group warning from the quest giver API", function()
        WowStubs.quest.groupSize = 3
        WowStubs.showQuest("detail")
        assert.are.equal("|cffb01010Bring 2 friends. Big danger.|r\n\n" .. RECORD_214.l, QuestInfoDescriptionText:GetText())
    end)

    it("treats elite and dungeon tags as group quests", function()
        WowStubs.quest.tag = { tagID = 81, isElite = false }
        WowStubs.showQuest("detail")
        assert.are.equal("|cffb01010Bring friends. Big danger.|r\n\n" .. RECORD_214.l, QuestInfoDescriptionText:GetText())
    end)

    it("rewrites the progress page and restores it", function()
        WowStubs.showQuest("progress")
        assert.are.equal("Not done. Monke still need:\n\n" .. BULLET .. "Grab 10 Red Silk Bandana (3/10)",
            QuestProgressText:GetText())
        ns.Core.ToggleOriginal()
        assert.are.equal("Do you have the bandanas?", QuestProgressText:GetText())
    end)

    it("says ready on the progress page when the quest can be completed", function()
        WowStubs.quest.completable = true
        WowStubs.showQuest("progress")
        assert.are.equal("All done. Give stuff.", QuestProgressText:GetText())
    end)

    it("rewrites the reward page", function()
        WowStubs.showQuest("reward")
        assert.are.equal("Job done. Take shiny.\n\nMonke get: 875 XP, 4s", QuestInfoRewardText:GetText())
    end)

    it("lists reward items and choices", function()
        WowStubs.quest.items = { "Red Defias Mask" }
        WowStubs.quest.choices = { "Axe", "Staff" }
        WowStubs.showQuest("reward")
        assert.are.equal("Job done. Take shiny.\n\nMonke get: 875 XP, 4s, Red Defias Mask, pick one: Axe / Staff",
            QuestInfoRewardText:GetText())
    end)

    it("creates toggle buttons whose label follows the state", function()
        local labels = {}
        for _, frame in ipairs(WowStubs.frames) do
            if frame.template == "UIPanelButtonTemplate" then
                labels[#labels + 1] = frame
            end
        end
        assert.are.equal(2, #labels)
        assert.are.equal("Wrinkle", labels[1]:GetText())
        assert.are.equal("Interface\\AddOns\\MonkeDo\\Media\\toggle.png", labels[1].monkeIcon.path)
        labels[1]:GetScript("OnClick")(labels[1])
        assert.are.equal("Monke", labels[1]:GetText())
        assert.are.equal("Interface\\AddOns\\MonkeDo\\Media\\toggle_monke.png", labels[2].monkeIcon.path)
        assert.is_true(ns.state.showOriginal)
    end)

    it("hooking QuestInfo_ShowDescriptionText would never fire, which is why QuestInfo_Display is hooked", function()
        -- Blizzard's templates capture the element functions when the file loads.
        local fired = 0
        _G.QuestInfo_ShowDescriptionText = function() end
        local captured = QuestInfo_ShowDescriptionText
        hooksecurefunc("QuestInfo_ShowDescriptionText", function() fired = fired + 1 end)
        captured()
        assert.are.equal(0, fired)
        _G.QuestInfo_ShowDescriptionText = nil
    end)

    it("says so when Immersion owns the quest window", function()
        WowStubs.reset()
        WowStubs.loadedAddons.Immersion = true
        ns = WowStubs.load()
        WowStubs.login()
        local found = false
        for _, line in ipairs(WowStubs.printed) do
            found = found or line:find("Immersion is drawing the quest window", 1, true) ~= nil
        end
        assert.is_true(found)
    end)

    it("survives a client with none of the quest frame globals", function()
        WowStubs.reset()
        _G.QuestInfo_Display, _G.QuestFrame, _G.QuestFrameProgressPanel, _G.QuestMapFrame = nil, nil, nil, nil
        _G.QuestInfoDescriptionText, _G.QuestInfoObjectivesText, _G.QuestInfoRewardText, _G.QuestProgressText = nil, nil, nil, nil
        _G.QuestInfoObjectivesHeader, _G.QuestInfoDescriptionHeader, _G.QuestInfoObjectivesFrame = nil, nil, nil
        _G.C_QuestLog = nil
        ns = WowStubs.load()
        assert.has_no.errors(WowStubs.login)
        assert.has_no.errors(ns.Display.Refresh)
    end)

    it("survives the log view pieces going missing", function()
        WowStubs.showQuest("log")
        -- Redraw from what is on screen with each piece gone or malformed in turn.
        _G.QuestInfoObjectivesHeader = nil
        _G.QuestInfoObjectivesFrame = { Objectives = "not a list" }
        _G.C_QuestLog.GetNextWaypointText = nil
        assert.has_no.errors(ns.Display.Refresh)
        _G.QuestInfoObjectivesFrame = { Objectives = { {}, false } }
        assert.has_no.errors(ns.Display.Refresh)
        _G.QuestInfoObjectivesFrame = nil
        assert.has_no.errors(ns.Display.Refresh)
        assert.are.equal(HEADER_MONKE .. "\n" .. BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Go back to Scout Riell.",
            QuestInfoObjectivesText:GetText())
        QuestInfoFrame.questLog = false -- the quest giver page, with no header to relabel
        assert.has_no.errors(ns.Display.Refresh)
        assert.has_no.errors(ns.Core.ToggleOriginal)
    end)

    describe("log view", function()
        -- Everything the player can see in the quest log or map details, top to bottom.
        local function visibleText()
            local parts = {}
            local function add(region)
                if region:IsShown() then
                    parts[#parts + 1] = region:GetText() or ""
                end
            end
            add(QuestInfoObjectivesText)
            if QuestInfoObjectivesFrame:IsShown() then
                for _, line in ipairs(QuestInfoObjectivesFrame.Objectives) do
                    add(line)
                end
            end
            add(QuestInfoDescriptionHeader)
            add(QuestInfoDescriptionText)
            return table.concat(parts, "\n")
        end

        local function count(haystack, needle)
            local _, n = haystack:gsub(needle, "")
            return n
        end

        it("shows the tasks once, first, under the tasks header", function()
            WowStubs.quest.waypoint = "Take the boat to Menethil Harbor"
            WowStubs.quest.objectives = {
                { text = "10/10 Red Silk Bandana", type = "item", finished = true, numFulfilled = 10, numRequired = 10 },
            }
            WowStubs.showQuest("log")
            assert.are.equal(
                HEADER_MONKE .. "\n" ..
                BULLET .. "Way: Take the boat to Menethil Harbor.\n" ..
                GREY .. BULLET .. "Grab 10 Red Silk Bandana (10/10)|r\n" ..
                BULLET .. "Go back to Scout Riell.",
                QuestInfoObjectivesText:GetText())
            -- Blizzard's own list keeps its lines (the layout hangs off them) but they say nothing.
            local lines = QuestInfoObjectivesFrame.Objectives
            assert.are.equal(2, #lines)
            for _, line in ipairs(lines) do
                assert.is_true(line:IsShown())
                assert.is_nil(line:GetText())
            end
            assert.are.equal("Description", QuestInfoDescriptionHeader:GetText())
            assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
            local seen = visibleText()
            assert.are.equal(1, count(seen, "Red Silk Bandana"))
            assert.are.equal(1, count(seen, "Menethil Harbor"))
            assert.is_nil(seen:find("Monke get", 1, true)) -- the map has its own rewards panel
        end)

        it("has no which-way bullet when the game gives none", function()
            WowStubs.showQuest("log")
            assert.are.equal(HEADER_MONKE .. "\n" .. BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Go back to Scout Riell.",
                QuestInfoObjectivesText:GetText())
            assert.is_nil(QuestInfoObjectivesFrame.Objectives[1]:GetText())
        end)

        it("the toggle restores every fontstring it touched, byte for byte, and back", function()
            local quest = WowStubs.quest
            quest.waypoint = "Take the boat to Menethil Harbor"
            quest.objectivesText = "Bring 10 bandanas,  $n.|cffff0000 now|r"
            quest.description = "Line one.\n\n  Odd  spacing \226\128\148 dash"
            quest.objectives = {
                { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
                { text = "Speak with Gryan", type = "event", finished = true, numFulfilled = 1, numRequired = 1 },
            }
            local blizzard = { "Optional: Take the boat to Menethil Harbor", "3/10 Red Silk Bandana",
                "Speak with Gryan (Complete)" }
            WowStubs.showQuest("log")
            local lines = QuestInfoObjectivesFrame.Objectives
            local ours = QuestInfoObjectivesText:GetText()
            assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())

            ns.Core.ToggleOriginal()
            assert.are.equal(quest.objectivesText, QuestInfoObjectivesText:GetText())
            assert.are.equal(quest.description, QuestInfoDescriptionText:GetText())
            for i, text in ipairs(blizzard) do
                assert.are.equal(text, lines[i]:GetText())
            end
            assert.are.equal("Description", QuestInfoDescriptionHeader:GetText())
            assert.are.equal("Quest Objectives", QuestInfoObjectivesHeader:GetText())

            ns.Core.ToggleOriginal()
            assert.are.equal(ours, QuestInfoObjectivesText:GetText())
            assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
            for i = 1, #blizzard do
                assert.is_nil(lines[i]:GetText())
            end

            ns.Core.ToggleOriginal() -- and once more, from the emptied state
            for i, text in ipairs(blizzard) do
                assert.are.equal(text, lines[i]:GetText())
            end
        end)

        it("stays right through Blizzard redraws and a voice switch", function()
            local quest = WowStubs.quest
            quest.waypoint = "Take the boat to Menethil Harbor"
            WowStubs.showQuest("log")
            local lines = QuestInfoObjectivesFrame.Objectives
            quest.objectives[1].text = "4/10 Red Silk Bandana"
            quest.objectives[1].numFulfilled = 4
            WowStubs.showQuest("log") -- Blizzard writes fresh strings everywhere
            WowStubs.showQuest("log")
            assert.are.equal(HEADER_MONKE .. "\n" .. BULLET .. "Way: Take the boat to Menethil Harbor.\n" ..
                BULLET .. "Grab 10 Red Silk Bandana (4/10)\n" .. BULLET .. "Go back to Scout Riell.",
                QuestInfoObjectivesText:GetText())

            ns.Core.Set("voice", "plain")
            assert.are.equal(HEADER_PLAIN .. "\n" .. BULLET .. "Next: Take the boat to Menethil Harbor.\n" ..
                BULLET .. "Collect 10 Red Silk Bandana (4/10)\n" .. BULLET .. "Return to Scout Riell.",
                QuestInfoObjectivesText:GetText())
            assert.are.equal(RECORD_214.p, QuestInfoDescriptionText:GetText())
            assert.is_nil(lines[1]:GetText())
            assert.is_nil(lines[2]:GetText())

            ns.Core.ToggleOriginal()
            assert.are.equal("Optional: Take the boat to Menethil Harbor", lines[1]:GetText())
            assert.are.equal("4/10 Red Silk Bandana", lines[2]:GetText()) -- the redraw's string, not the first one
            assert.are.equal(quest.objectivesText, QuestInfoObjectivesText:GetText())
            assert.are.equal(quest.description, QuestInfoDescriptionText:GetText())
        end)

        it("stays on Blizzard's list for the next quest while toggled off", function()
            ns.Core.ToggleOriginal()
            WowStubs.showQuest("log")
            assert.are.equal(WowStubs.quest.objectivesText, QuestInfoObjectivesText:GetText())
            assert.are.equal("3/10 Red Silk Bandana", QuestInfoObjectivesFrame.Objectives[1]:GetText())
        end)

        it("gives Blizzard's lines back when the quest giver page takes the frame", function()
            WowStubs.showQuest("log")
            local line = QuestInfoObjectivesFrame.Objectives[1]
            assert.is_nil(line:GetText())
            WowStubs.showQuest("detail")
            assert.are.equal("3/10 Red Silk Bandana", line:GetText())
            assert.are.equal("Monke do:", QuestInfoObjectivesHeader:GetText())
        end)

        it("does not carry one quest's lines into the next", function()
            WowStubs.quest.objectives[2] = { text = "0/1 Defias Letter", type = "item", finished = false,
                numFulfilled = 0, numRequired = 1 }
            WowStubs.showQuest("log")
            WowStubs.quest = {
                id = 999, description = "Second quest text.", objectivesText = "Kill things.", onQuest = true,
                objectives = { { text = "0/5 Murloc slain", type = "monster", finished = false, numFulfilled = 0, numRequired = 5 } },
                groupSize = 0, xp = 0, money = 0, items = {}, choices = {},
            }
            WowStubs.showQuest("log")
            local lines = QuestInfoObjectivesFrame.Objectives
            assert.is_nil(lines[1]:GetText())
            assert.is_false(lines[2]:IsShown())
            ns.Core.ToggleOriginal()
            assert.are.equal("0/5 Murloc slain", lines[1]:GetText())
            assert.are.equal("Kill things.", QuestInfoObjectivesText:GetText())
            assert.are.equal("Second quest text.", QuestInfoDescriptionText:GetText())
        end)
    end)
end)

describe("Tracker after a voice change", function()
    local function block(lines)
        local usedLines = {}
        for i, text in ipairs(lines) do
            usedLines[i] = { Text = WowStubs.newFontString(text) }
        end
        return { usedLines = usedLines }
    end

    -- One watched quest, 214, whose tracker block is `trackerBlock`.
    local function installTracker(trackerBlock)
        _G.QuestObjectiveTracker = {
            UpdateSingle = function() end,
            GetExistingBlock = function(_, questID) return questID == 214 and trackerBlock or nil end,
        }
        _G.C_QuestLog.GetNumQuestWatches = function() return 1 end
        _G.C_QuestLog.GetQuestIDForQuestWatchIndex = function(index) return index == 1 and 214 or nil end
    end

    local text, ns

    before_each(function()
        WowStubs.reset()
        local b = block({ "3/10 Red Silk Bandana" })
        installTracker(b)
        ns = WowStubs.load()
        WowStubs.login()
        QuestObjectiveTracker:UpdateSingle({ GetID = function() return 214 end })
        text = b.usedLines[1].Text
        assert.are.equal("Grab 10 Red Silk Bandana (3/10)", text:GetText())
        SlashCmdList["MONKEDO"]("voice plain")
        assert.are.equal("Collect 10 Red Silk Bandana (3/10)", text:GetText())
    end)

    it("the toggle still puts Blizzard's line back", function()
        ns.Core.ToggleOriginal()
        assert.are.equal("3/10 Red Silk Bandana", text:GetText())
    end)

    it("/monke tracker off still puts Blizzard's line back", function()
        SlashCmdList["MONKEDO"]("tracker off")
        assert.are.equal("3/10 Red Silk Bandana", text:GetText())
    end)
end)

describe("Tracker", function()
    local ns

    local function block(lines)
        local usedLines = {}
        for i, text in ipairs(lines) do
            usedLines[i] = { Text = WowStubs.newFontString(text) }
        end
        return { usedLines = usedLines }
    end

    -- Quest 214 is watched, and its block is `trackerBlock`. Asking the tracker to redraw from
    -- addon code taints it (and through it Edit Mode), so MarkDirty fails the spec.
    local function installTracker(trackerBlock)
        _G.QuestObjectiveTracker = {
            UpdateSingle = function() end,
            GetExistingBlock = function(_, questID) return questID == 214 and trackerBlock or nil end,
            MarkDirty = function() error("the tracker must never be marked dirty from addon code") end,
        }
        _G.C_QuestLog.GetNumQuestWatches = function() return 1 end
        _G.C_QuestLog.GetQuestIDForQuestWatchIndex = function(index) return index == 1 and 214 or nil end
    end

    before_each(function()
        WowStubs.reset()
    end)

    it("rewrites objective lines after the tracker updates a quest", function()
        local b = block({ "3/10 Red Silk Bandana" })
        installTracker(b)
        ns = WowStubs.load()
        WowStubs.login()
        QuestObjectiveTracker:UpdateSingle({ GetID = function() return 214 end })
        assert.are.equal("Grab 10 Red Silk Bandana (3/10)", b.usedLines[1].Text:GetText())
    end)

    it("keeps the original line when the new one would be taller", function()
        WowStubs.quest.objectives = {
            { text = "0/1 Speak with the very long named Harbormaster of Menethil", type = "event",
              numFulfilled = 0, numRequired = 1 },
        }
        local original = "0/1 Speak with the very long named Har"
        local b = block({ original })
        installTracker(b)
        ns = WowStubs.load()
        WowStubs.login()
        QuestObjectiveTracker:UpdateSingle({ GetID = function() return 214 end })
        assert.are.equal(original, b.usedLines[1].Text:GetText())
    end)

    it("leaves finished lines, the off setting and the original-text toggle alone", function()
        local b = block({ "3/10 Red Silk Bandana" })
        installTracker(b)
        ns = WowStubs.load()
        WowStubs.login()
        local quest = { GetID = function() return 214 end }

        ns.Core.Set("tracker", false)
        QuestObjectiveTracker:UpdateSingle(quest)
        assert.are.equal("3/10 Red Silk Bandana", b.usedLines[1].Text:GetText())

        ns.Core.Set("tracker", true)
        ns.Core.ToggleOriginal()
        QuestObjectiveTracker:UpdateSingle(quest)
        assert.are.equal("3/10 Red Silk Bandana", b.usedLines[1].Text:GetText())

        ns.Core.ToggleOriginal()
        WowStubs.quest.objectives[1].finished = true
        b.usedLines[1].Text:SetText("10/10 Red Silk Bandana") -- Blizzard redraws the line first
        QuestObjectiveTracker:UpdateSingle(quest)
        assert.are.equal("10/10 Red Silk Bandana", b.usedLines[1].Text:GetText())
    end)

    it("the toggle and the setting swap the lines on screen, without redrawing the tracker", function()
        local b = block({ "3/10 Red Silk Bandana" })
        installTracker(b)
        ns = WowStubs.load()
        WowStubs.login()
        QuestObjectiveTracker:UpdateSingle({ GetID = function() return 214 end })
        local text = b.usedLines[1].Text
        assert.are.equal("Grab 10 Red Silk Bandana (3/10)", text:GetText())

        ns.Core.ToggleOriginal() -- "Monke don't": Blizzard's own line, byte for byte
        assert.are.equal("3/10 Red Silk Bandana", text:GetText())
        ns.Core.ToggleOriginal()
        assert.are.equal("Grab 10 Red Silk Bandana (3/10)", text:GetText())
        ns.Core.Set("tracker", false)
        assert.are.equal("3/10 Red Silk Bandana", text:GetText())
        ns.Core.Set("tracker", true)
        assert.are.equal("Grab 10 Red Silk Bandana (3/10)", text:GetText())

        -- Blizzard redrew the line since (a loot): that text is left alone.
        text:SetText("4/10 Red Silk Bandana")
        ns.Core.ToggleOriginal()
        assert.are.equal("4/10 Red Silk Bandana", text:GetText())
    end)

    it("does nothing on a client without the modern tracker", function()
        ns = WowStubs.load()
        assert.has_no.errors(WowStubs.login)
    end)
end)

describe("globals", function()
    it("the addon only touches globals declared in .luacheckrc", function()
        local seen = WowStubs.trackGlobals(function()
            WowStubs.reset()
            _G.MonkeDB = nil
            local ns = WowStubs.load()
            WowStubs.login()
            WowStubs.showQuest("detail")
            WowStubs.fadeQuestText()
            WowStubs.showQuest("log")
            WowStubs.showQuest("reward")
            WowStubs.showQuest("progress")
            ns.Core.ToggleOriginal()
            ns.Core.HandleSlash("version")
            ns.Core.HandleSlash("")
        end)
        local declared = WowStubs.declaredGlobals()
        -- Read by the fake client and the test scaffolding, not by the addon.
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

describe("Display colours", function()
    local BULLET = "\226\128\162 "

    before_each(function()
        WowStubs.reset()
        _G.MonkeDB = { [214] = { l = "Bad men wear red hankies.", t = { "Grab 10 Red Silk Bandana.", "Go back to Scout Riell." },
            n = 1, e = "Scout Riell", v = 3 } }
        WowStubs.load()
        WowStubs.login()
    end)

    it("follows Blizzard's stone page (Quest Text Contrast) instead of assuming parchment", function()
        WowStubs.stone()
        WowStubs.quest.objectives[1] = { text = "10/10 Red Silk Bandana", type = "item", finished = true,
            numFulfilled = 10, numRequired = 10 }
        WowStubs.showQuest("log")
        local text = QuestInfoObjectivesText:GetText()
        assert.is_true(text:find("^|cffedd100Monke do:|r") ~= nil, text)
        assert.is_true(text:find("|cff9d9d9d" .. BULLET .. "Grab 10 Red Silk Bandana (10/10)|r", 1, true) ~= nil, text)
    end)

    it("uses a red that reads on each page for the group warning", function()
        WowStubs.quest.groupSize = 3
        WowStubs.showQuest("detail")
        assert.is_true(QuestInfoDescriptionText:GetText():find("^|cffb01010Bring 2 friends") ~= nil)
        WowStubs.stone()
        WowStubs.showQuest("detail")
        assert.is_true(QuestInfoDescriptionText:GetText():find("^|cffff4040Bring 2 friends") ~= nil)
    end)
end)
