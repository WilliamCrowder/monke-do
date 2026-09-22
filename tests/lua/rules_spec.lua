-- Rules.lua and Voice.lua: every objective type, both client text formats, progress.

describe("Rules", function()
    local ns, Rules, Voice

    before_each(function()
        WowStubs.reset()
        ns = WowStubs.load()
        Rules, Voice = ns.Rules, ns.Voice
    end)

    describe("ParseObjectiveText", function()
        it("reads the Retail format", function()
            local name, have, need = Rules.ParseObjectiveText("3/10 Red Silk Bandana")
            assert.are.equal("Red Silk Bandana", name)
            assert.are.equal(3, have)
            assert.are.equal(10, need)
        end)
        it("reads the Classic format", function()
            local name, have, need = Rules.ParseObjectiveText("Red Silk Bandana: 3/10")
            assert.are.equal("Red Silk Bandana", name)
            assert.are.equal(3, have)
            assert.are.equal(10, need)
        end)
        it("drops the word slain in both formats", function()
            assert.are.equal("Kobold Vermin", (Rules.ParseObjectiveText("0/8 Kobold Vermin slain")))
            assert.are.equal("Kobold Vermin", (Rules.ParseObjectiveText("Kobold Vermin slain: 0/8")))
        end)
        it("keeps text with no count", function()
            local name, have, need = Rules.ParseObjectiveText("Explore the Jasperlode Mine")
            assert.are.equal("Explore the Jasperlode Mine", name)
            assert.is_nil(have)
            assert.is_nil(need)
        end)
        it("reports whether the text was a kill line", function()
            local _, _, _, slain = Rules.ParseObjectiveText("0/8 Kobold Vermin slain")
            assert.is_true(slain)
            _, _, _, slain = Rules.ParseObjectiveText("Find Mankrik's Wife: 0/1")
            assert.is_false(slain)
        end)
        it("survives junk", function()
            assert.are.equal("", (Rules.ParseObjectiveText(nil)))
            assert.are.equal("", (Rules.ParseObjectiveText(42)))
        end)
    end)

    describe("Line", function()
        it("monster", function()
            local o = { type = "monster", text = "0/8 Kobold Vermin slain", numRequired = 8, numFulfilled = 0 }
            assert.are.equal("Bonk 8 Kobold Vermin.", Rules.Line(o, "monke"))
            assert.are.equal("Kill 8 Kobold Vermin.", Rules.Line(o, "plain"))
        end)
        it("single monster has no count", function()
            local o = { type = "monster", text = "0/1 Hogger slain", numRequired = 1, numFulfilled = 0 }
            assert.are.equal("Bonk Hogger.", Rules.Line(o, "monke"))
            assert.are.equal("Kill Hogger.", Rules.Line(o, "plain"))
        end)
        it("item", function()
            local o = { type = "item", text = "3/10 Red Silk Bandana", numRequired = 10, numFulfilled = 3 }
            assert.are.equal("Grab 10 Red Silk Bandana.", Rules.Line(o, "monke"))
            assert.are.equal("Collect 10 Red Silk Bandana.", Rules.Line(o, "plain"))
        end)
        it("object", function()
            local o = { type = "object", text = "0/1 Wanted Poster", numRequired = 1, numFulfilled = 0 }
            assert.are.equal("Poke Wanted Poster.", Rules.Line(o, "monke"))
            assert.are.equal("Use Wanted Poster.", Rules.Line(o, "plain"))
            o = { type = "object", text = "0/4 Rune Stone", numRequired = 4, numFulfilled = 0 }
            assert.are.equal("Poke 4 Rune Stone.", Rules.Line(o, "monke"))
        end)
        it("event and spell keep the game wording with one full stop", function()
            local o = { type = "event", text = "Explore the Jasperlode Mine.", numRequired = 1, numFulfilled = 0 }
            assert.are.equal("Do the thing: Explore the Jasperlode Mine.", Rules.Line(o, "monke"))
            assert.are.equal("Explore the Jasperlode Mine.", Rules.Line(o, "plain"))
            o = { type = "spell", text = "0/1 Learn Apprentice Cooking", numRequired = 1, numFulfilled = 0 }
            assert.are.equal("Do the thing: Learn Apprentice Cooking.", Rules.Line(o, "monke"))
        end)
        it("reputation", function()
            local o = { type = "reputation", text = "Argent Dawn: Neutral / Friendly" }
            assert.are.equal("Make Argent Dawn like ape.", Rules.Line(o, "monke"))
            assert.are.equal("Reach Friendly with Argent Dawn.", Rules.Line(o, "plain"))
            o = { type = "reputation", text = "Timbermaw Hold" }
            assert.are.equal("Earn reputation with Timbermaw Hold.", Rules.Line(o, "plain"))
        end)
        it("unknown types fall back to the event template", function()
            local o = { type = "somethingnew", text = "Dance with the trogg" }
            assert.are.equal("Do the thing: Dance with the trogg.", Rules.Line(o, "monke"))
        end)
        it("keeps the game's words for a credit objective that is not a kill", function()
            local o = { type = "monster", text = "Find Mankrik's Wife: 0/1", numRequired = 1, numFulfilled = 0 }
            assert.are.equal("Do the thing: Find Mankrik's Wife.", Rules.Line(o, "monke"))
            assert.are.equal("Find Mankrik's Wife.", Rules.Line(o, "plain"))
            o = { type = "monster", text = "2/5 Peons Awoken", numRequired = 5, numFulfilled = 2 }
            assert.are.equal("Do the thing: Peons Awoken.", Rules.Line(o, "monke"))
        end)
        it("does not double the punctuation of text ending in ! or ?", function()
            local o = { type = "event", text = "Survive!", numRequired = 1 }
            assert.are.equal("Do the thing: Survive!", Rules.Line(o, "monke"))
            assert.are.equal("Survive!", Rules.Line(o, "plain"))
            o = { type = "event", text = "0/1 Who goes there?", numRequired = 1 }
            assert.are.equal("Who goes there?", Rules.Line(o, "plain"))
        end)
        it("reads the count from Classic-format text when the API gives none", function()
            local o = { type = "item", text = "Linen Cloth: 2/6" }
            assert.are.equal("Grab 6 Linen Cloth.", Rules.Line(o, "monke"))
        end)
    end)

    describe("Progress", function()
        it("shows have/need for counted objectives", function()
            local o = { type = "monster", text = "x", numFulfilled = 3, numRequired = 15 }
            assert.are.equal("(3/15)", Rules.Progress(o, "monke"))
        end)
        it("never shows more than needed", function()
            local o = { type = "item", text = "x", numFulfilled = 12, numRequired = 10 }
            assert.are.equal("(10/10)", Rules.Progress(o, "monke"))
        end)
        it("single objectives show only when done", function()
            assert.is_nil(Rules.Progress({ type = "object", text = "x", numFulfilled = 0, numRequired = 1 }, "monke"))
            local done = { type = "object", text = "x", numFulfilled = 1, numRequired = 1, finished = true }
            assert.are.equal("(done)", Rules.Progress(done, "monke"))
        end)
        it("progress bars show a percentage", function()
            assert.are.equal("(45%)", Rules.Progress({ type = "progressbar", text = "x", percent = 45 }, "monke"))
        end)
        it("reputation never shows raw numbers", function()
            local o = { type = "reputation", text = "x", numFulfilled = 1200, numRequired = 3000 }
            assert.is_nil(Rules.Progress(o, "plain"))
        end)
    end)

    describe("TurnIn", function()
        it("names the NPC when known", function()
            assert.are.equal("Go back to Scout Riell.", Rules.TurnIn("Scout Riell", "monke"))
            assert.are.equal("Return to Scout Riell.", Rules.TurnIn("Scout Riell", "plain"))
        end)
        it("says go see when the turn-in is not the quest giver", function()
            assert.are.equal("Go see Gryan Stoutmantle.", Rules.TurnIn("Gryan Stoutmantle", "monke", true))
            assert.are.equal("Go to Gryan Stoutmantle.", Rules.TurnIn("Gryan Stoutmantle", "plain", true))
        end)
        it("has a generic line otherwise", function()
            assert.are.equal("Go back. Get shiny.", Rules.TurnIn(nil, "monke"))
            assert.are.equal("Turn in the quest.", Rules.TurnIn("", "plain"))
        end)
    end)

    describe("BuildTasks", function()
        it("skips objectives with no text and keeps order", function()
            local tasks = Rules.BuildTasks({
                { type = "monster", text = "0/8 Kobold Vermin slain", numRequired = 8 },
                { type = "event", text = "" },
                { type = "item", text = "0/5 Candle", numRequired = 5 },
            }, "monke")
            assert.are.same({ "Bonk 8 Kobold Vermin.", "Grab 5 Candle." }, tasks)
        end)
        it("accepts nil", function()
            assert.are.same({}, Rules.BuildTasks(nil, "monke"))
        end)
    end)

    describe("Voice", function()
        it("falls back on unknown voice and key", function()
            assert.are.equal("Go back. Get shiny.", Voice.Get("turnin_unknown", "klingon"))
            assert.are.equal("", Voice.Get("no_such_key", "monke"))
        end)
        it("leaves percent signs and patterns in values alone", function()
            assert.are.equal("Grab 100% Pure %d+.", Voice.Format("item_one", "monke", { name = "100% Pure %d+" }))
        end)
        it("every key exists in both voices", function()
            for _, key in ipairs({ "monster", "monster_one", "item", "item_one", "object", "object_one", "event",
                "reputation", "reputation_unknown", "turnin", "turnin_other", "turnin_unknown", "group", "group_one", "group_tag",
                "rewards", "rewards_choice", "progress_todo", "progress_ready", "complete",
                "toggle_to_original", "toggle_to_monke", "toggle_tip_original", "toggle_tip_monke" }) do
                assert.is_true(Voice.Get(key, "monke") ~= "", key)
                assert.is_true(Voice.Get(key, "plain") ~= "", key)
            end
        end)
    end)
end)
