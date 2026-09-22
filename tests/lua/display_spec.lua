-- Display.lua and Tracker.lua against the fake client. This proves the wiring and the
-- toggle contract; frame positions and real layout stay on the in-game checklist.

describe("Display", function()
    local ns
    local BULLET = "\226\128\162 "

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

        ns.Core.ToggleOriginal()
        assert.are.equal(RECORD_214.l, QuestInfoDescriptionText:GetText())
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

    it("renders rule-based bullets and keeps Blizzard lore for a quest with no DB entry", function()
        _G.MonkeDB = {}
        WowStubs.showQuest("detail")
        assert.are.equal("Lore not yet translated.\n\n" .. WowStubs.quest.description, QuestInfoDescriptionText:GetText())
        assert.are.equal(
            BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" .. BULLET .. "Go back. Get shiny.\n\nMonke get: 875 XP, 4s",
            QuestInfoObjectivesText:GetText())
    end)

    it("does not stack the no-lore notice when the same page refreshes", function()
        _G.MonkeDB = {}
        WowStubs.showQuest("detail")
        ns.Core.Set("groupWarning", false) -- any setting change redraws
        assert.are.equal("Lore not yet translated.\n\n" .. WowStubs.quest.description, QuestInfoDescriptionText:GetText())
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
        assert.are.equal("|cffff2020Bring 2 friends. Big danger.|r\n\n" .. RECORD_214.l, QuestInfoDescriptionText:GetText())
    end)

    it("treats elite and dungeon tags as group quests", function()
        WowStubs.quest.tag = { tagID = 81, isElite = false }
        WowStubs.showQuest("detail")
        assert.are.equal("|cffff2020Bring friends. Big danger.|r\n\n" .. RECORD_214.l, QuestInfoDescriptionText:GetText())
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
        _G.C_QuestLog = nil
        ns = WowStubs.load()
        assert.has_no.errors(WowStubs.login)
        assert.has_no.errors(ns.Display.Refresh)
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

    local function installTracker(trackerBlock)
        _G.QuestObjectiveTracker = {
            UpdateSingle = function() end,
            GetExistingBlock = function() return trackerBlock end,
            MarkDirty = function(self) self.dirty = (self.dirty or 0) + 1 end,
        }
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
        assert.are.equal(1, QuestObjectiveTracker.dirty)

        ns.Core.Set("tracker", true)
        ns.Core.ToggleOriginal()
        QuestObjectiveTracker:UpdateSingle(quest)
        assert.are.equal("3/10 Red Silk Bandana", b.usedLines[1].Text:GetText())

        ns.Core.ToggleOriginal()
        WowStubs.quest.objectives[1].finished = true
        QuestObjectiveTracker:UpdateSingle(quest)
        assert.are.equal("3/10 Red Silk Bandana", b.usedLines[1].Text:GetText())
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
