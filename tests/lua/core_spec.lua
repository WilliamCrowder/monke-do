-- Core.lua: settings that survive the SavedVariables beta bug, slash commands, DB lookup.

describe("Core", function()
    local ns, Core

    local function printedContains(fragment)
        for _, line in ipairs(WowStubs.printed) do
            if line:find(fragment, 1, true) then
                return true
            end
        end
        return false
    end

    before_each(function()
        WowStubs.reset()
        ns = WowStubs.load()
        Core = ns.Core
    end)

    describe("settings", function()
        it("default sanely when SavedVariables never loaded", function()
            _G.MonkeDoDB = nil
            WowStubs.login()
            assert.are.equal("monke", Core.Get("voice"))
            assert.is_true(Core.Get("showLore"))
            assert.is_true(Core.Get("groupWarning"))
            assert.is_true(Core.Get("tracker"))
            assert.are.same({ hide = false }, Core.Get("minimap"))
        end)
        it("keep saved values and repair bad ones", function()
            _G.MonkeDoDB = { voice = "plain", showLore = false, groupWarning = "yes", minimap = 7 }
            WowStubs.login()
            assert.are.equal("plain", Core.Get("voice"))
            assert.is_false(Core.Get("showLore"))
            assert.is_true(Core.Get("groupWarning"))
            assert.are.same({ hide = false }, Core.Get("minimap"))
        end)
        it("reject an unknown voice", function()
            _G.MonkeDoDB = { voice = "klingon" }
            WowStubs.login()
            assert.are.equal("monke", Core.Get("voice"))
        end)
        it("work before ADDON_LOADED too", function()
            assert.are.equal("monke", Core.Get("voice"))
        end)
        it("ignore ADDON_LOADED for other addons", function()
            _G.MonkeDoDB = nil
            WowStubs.fire("ADDON_LOADED", "SomeOtherAddon")
            assert.is_nil(MonkeDoDB)
        end)
    end)

    describe("slash commands", function()
        before_each(function()
            WowStubs.login()
        end)
        it("are registered", function()
            assert.are.equal("/monke", SLASH_MONKEDO1)
            assert.are.equal(Core.HandleSlash, SlashCmdList["MONKEDO"])
        end)
        it("/monke lore toggles the per-session original text state", function()
            assert.is_false(ns.state.showOriginal)
            SlashCmdList["MONKEDO"]("lore")
            assert.is_true(ns.state.showOriginal)
            SlashCmdList["MONKEDO"]("LORE")
            assert.is_false(ns.state.showOriginal)
        end)
        it("/monke voice sets and flips the voice", function()
            SlashCmdList["MONKEDO"]("voice plain")
            assert.are.equal("plain", Core.Get("voice"))
            SlashCmdList["MONKEDO"]("voice")
            assert.are.equal("monke", Core.Get("voice"))
            SlashCmdList["MONKEDO"]("voice klingon")
            assert.are.equal("monke", Core.Get("voice"))
        end)
        it("/monke showlore, group and tracker take on, off or nothing", function()
            SlashCmdList["MONKEDO"]("showlore off")
            assert.is_false(Core.Get("showLore"))
            SlashCmdList["MONKEDO"]("showlore")
            assert.is_true(Core.Get("showLore"))
            SlashCmdList["MONKEDO"]("group off")
            assert.is_false(Core.Get("groupWarning"))
            SlashCmdList["MONKEDO"]("tracker off")
            assert.is_false(Core.Get("tracker"))
        end)
        it("/monke version reports the database", function()
            _G.MonkeDB_Meta = { build = "1.60.1.69913", generated = "2026-10-01", count = 3120 }
            SlashCmdList["MONKEDO"]("version")
            assert.is_true(printedContains("v1.2.3, 3120 quests, game build 1.60.1.69913, generated 2026-10-01"))
        end)
        it("/monke version copes with no database", function()
            SlashCmdList["MONKEDO"]("version")
            assert.is_true(printedContains("no quest database loaded"))
        end)
        it("/monke with no Settings API prints help", function()
            SlashCmdList["MONKEDO"]("")
            assert.is_true(printedContains("/monke lore"))
        end)
        it("unknown commands print help", function()
            SlashCmdList["MONKEDO"]("banana")
            assert.is_true(printedContains("/monke voice"))
        end)
        it("changes notify listeners", function()
            local calls = 0
            Core.OnChange(function() calls = calls + 1 end)
            SlashCmdList["MONKEDO"]("voice plain")
            SlashCmdList["MONKEDO"]("lore")
            assert.are.equal(2, calls)
        end)
    end)

    describe("settings panel", function()
        it("registers a category and opens it from /monke and the addon compartment", function()
            WowStubs.installSettings()
            WowStubs.login()
            assert.is_nil(Core.settingsError)
            assert.are.equal(42, Core.categoryID)
            SlashCmdList["MONKEDO"]("")
            assert.are.equal(42, WowStubs.openedCategory)
            WowStubs.openedCategory = nil
            MonkeDo_OnAddonCompartmentClick()
            assert.are.equal(42, WowStubs.openedCategory)
        end)
        it("a broken Settings API does not stop login", function()
            _G.Settings = {
                RegisterVerticalLayoutCategory = function() error("changed in a hotfix") end,
                RegisterAddOnSetting = function() end,
            }
            assert.has_no.errors(WowStubs.login)
            assert.is_not_nil(Core.settingsError)
            assert.is_true(printedContains("loaded"))
        end)
    end)

    describe("GetRecord", function()
        it("finds a record and copes with a missing database", function()
            assert.is_nil(Core.GetRecord(214))
            _G.MonkeDB = { [214] = { l = "x", v = 3 } }
            assert.are.equal("x", Core.GetRecord(214).l)
            assert.is_nil(Core.GetRecord(215))
            assert.is_nil(Core.GetRecord("214"))
        end)
    end)
end)
