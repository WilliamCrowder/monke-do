-- Compose.lua: the rendering rules of docs/DATA_CONTRACT.md section 2.

describe("Compose", function()
    local ns, Compose
    local BULLET = "\226\128\162 "

    -- Quest 214 as the pipeline exports it. PLACEHOLDER WORDING: replace l, p and t with the
    -- text from the pitch (and pin it in pipeline/llm/overrides.jsonl) so this is the golden test.
    local RECORD_214 = {
        l = "Bad men wear red hankies. Scout lady want them. Take hankies.",
        p = "The Defias wear red bandanas. Scout Riell wants ten as proof they are being thinned out.",
        t = { "Grab 10 Red Silk Bandana.", "Go back to Scout Riell." },
        n = 1, e = "Scout Riell", v = 3,
    }
    local LIVE_214 = {
        { text = "3/10 Red Silk Bandana", type = "item", finished = false, numFulfilled = 3, numRequired = 10 },
    }

    before_each(function()
        WowStubs.reset()
        ns = WowStubs.load()
        Compose = ns.Compose
    end)

    it("renders quest 214 in monke voice", function()
        local s = Compose.Build({ record = RECORD_214, objectives = LIVE_214, voice = "monke", showProgress = true,
            rewards = { xp = 875, money = 400 } })
        assert.are.equal(RECORD_214.l, Compose.DescriptionText(s, "original"))
        assert.are.equal(
            BULLET .. "Grab 10 Red Silk Bandana (3/10)\n" ..
            BULLET .. "Go back to Scout Riell.\n\n" ..
            "Monke get: 875 XP, 4s",
            Compose.ObjectivesText(s))
    end)

    it("renders quest 214 in plain voice from rules plus the turn-in NPC", function()
        local s = Compose.Build({ record = RECORD_214, objectives = LIVE_214, voice = "plain", showProgress = true })
        assert.are.equal(RECORD_214.p, s.lore)
        assert.are.same({ "Collect 10 Red Silk Bandana (3/10)", "Return to Scout Riell." }, s.tasks)
    end)

    it("shows no progress for a quest that is only being offered", function()
        local s = Compose.Build({ record = RECORD_214, objectives = LIVE_214, voice = "monke", showProgress = false })
        assert.are.same({ "Grab 10 Red Silk Bandana.", "Go back to Scout Riell." }, s.tasks)
    end)

    it("builds rule-based bullets and no lore when there is no record", function()
        local s = Compose.Build({ objectives = LIVE_214, voice = "monke", showProgress = true })
        assert.is_nil(s.lore)
        assert.is_true(s.loreMissing)
        assert.are.same({ "Grab 10 Red Silk Bandana (3/10)", "Go back. Get shiny." }, s.tasks)
        assert.are.equal("Lore not yet translated.\n\nBlizzard words", Compose.DescriptionText(s, "Blizzard words"))
    end)

    it("uses go-to wording for a delivery quest in plain voice", function()
        local record = { t = { "Go see Gryan Stoutmantle." }, e = "Gryan Stoutmantle", d = true, v = 3 }
        assert.are.same({ "Go to Gryan Stoutmantle." }, Compose.Build({ record = record, voice = "plain" }).tasks)
        assert.are.same({ "Go see Gryan Stoutmantle." }, Compose.Build({ record = record, voice = "monke" }).tasks)
    end)

    it("still ends with a turn-in line when the quest has no objectives", function()
        local s = Compose.Build({ objectives = {}, voice = "plain" })
        assert.are.same({ "Turn in the quest." }, s.tasks)
        assert.are.equal(0, s.numObjectiveTasks)
    end)

    it("falls back to rules when the live objective count differs from n", function()
        local live = {
            LIVE_214[1],
            { text = "0/1 Defias Note", type = "item", finished = false, numFulfilled = 0, numRequired = 1 },
        }
        local s = Compose.Build({ record = RECORD_214, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Grab 10 Red Silk Bandana (3/10)", "Grab Defias Note.", "Go back to Scout Riell." }, s.tasks)
    end)

    it("falls back to rules when a DB line has the wrong count", function()
        local record = { t = { "Grab 8 Red Silk Bandana.", "Go back to Scout Riell." }, n = 1, v = 3 }
        local s = Compose.Build({ record = record, objectives = LIVE_214, voice = "monke", showProgress = true })
        assert.are.equal("Grab 10 Red Silk Bandana (3/10)", s.tasks[1])
    end)

    it("re-pairs DB lines when the game orders objectives differently", function()
        local record = {
            t = { "Grab 5 Candle.", "Bonk 8 Kobold Vermin.", "Go back to Marshal Dughan." }, n = 2, v = 3,
        }
        local live = {
            { text = "2/8 Kobold Vermin slain", type = "monster", numFulfilled = 2, numRequired = 8 },
            { text = "1/5 Candle", type = "item", numFulfilled = 1, numRequired = 5 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Bonk 8 Kobold Vermin (2/8)", "Grab 5 Candle (1/5)", "Go back to Marshal Dughan." }, s.tasks)
    end)

    it("shows the DB bullets when the game has no objectives yet (quest only offered)", function()
        local s = Compose.Build({ record = RECORD_214, objectives = nil, voice = "monke", showProgress = false })
        assert.are.same({ "Grab 10 Red Silk Bandana.", "Go back to Scout Riell." }, s.tasks)
        s = Compose.Build({ record = RECORD_214, objectives = {}, voice = "monke" })
        assert.are.same({ "Grab 10 Red Silk Bandana.", "Go back to Scout Riell." }, s.tasks)
    end)

    it("pairs by name when the same-position line names a different live objective", function()
        -- Shipped record 5251: the game lists the object first and the archivist second.
        local record = { t = { "Bonk Archivist Galford.", "Poke Scarlet Archive." }, n = 2, v = 3 }
        local live = {
            { type = "object", text = "Archive Burned: 1/1", finished = true, numFulfilled = 1, numRequired = 1 },
            { type = "monster", text = "Archivist Galford slain: 0/1", numFulfilled = 0, numRequired = 1 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Poke Scarlet Archive (done)", "Bonk Archivist Galford.", "Go back. Get shiny." }, s.tasks)
    end)

    it("pairs the last objective with the last free line when nothing contradicts it", function()
        local record = { t = { "Bonk Archivist Galford.", "Poke Scarlet Archive.", "Grab Old Tome." }, n = 3, v = 3 }
        local live = {
            { type = "object", text = "Archive Burned: 1/1", finished = true, numFulfilled = 1, numRequired = 1 },
            { type = "monster", text = "Archivist Galford slain: 0/1", numFulfilled = 0, numRequired = 1 },
            { type = "item", text = "Dusty Tome: 0/1", numFulfilled = 0, numRequired = 1 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Poke Scarlet Archive (done)", "Bonk Archivist Galford.", "Grab Old Tome.", "Go back. Get shiny." },
            s.tasks)
    end)

    it("falls back when the only free line names a different objective", function()
        local record = { t = { "Bonk Archivist Galford.", "Bonk Archivist Galford.", "Grab Old Tome." }, n = 3, v = 3 }
        local live = {
            { type = "object", text = "Archive Burned: 1/1", finished = true, numFulfilled = 1, numRequired = 1 },
            { type = "monster", text = "Archivist Galford slain: 0/1", numFulfilled = 0, numRequired = 1 },
            { type = "item", text = "Dusty Tome: 0/1", numFulfilled = 0, numRequired = 1 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Poke Archive Burned (done)", "Bonk Archivist Galford.", "Grab Dusty Tome.", "Go back. Get shiny." },
            s.tasks)
    end)

    it("does not let a short name claim a longer name's line", function()
        local record = { t = { "Bonk 6 Burly Rockjaw Trogg.", "Bonk 4 Rockjaw Trogg.", "Go back to Senir." }, n = 2, v = 3 }
        local live = {
            { type = "monster", text = "Rockjaw Trogg slain: 1/4", numFulfilled = 1, numRequired = 4 },
            { type = "monster", text = "Burly Rockjaw Trogg slain: 0/6", numFulfilled = 0, numRequired = 6 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Bonk 4 Rockjaw Trogg (1/4)", "Bonk 6 Burly Rockjaw Trogg (0/6)", "Go back to Senir." }, s.tasks)
    end)

    it("gives up rather than guess when two lines name the same objective", function()
        local record = { t = { "Grab 5 Candle.", "Grab 5 Candle.", "Go back to Marshal Dughan." }, n = 2, v = 3 }
        local live = {
            { type = "item", text = "1/5 Candle", numFulfilled = 1, numRequired = 5 },
            { type = "item", text = "0/5 Torch", numFulfilled = 0, numRequired = 5 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Grab 5 Candle (1/5)", "Grab 5 Torch (0/5)", "Go back to Marshal Dughan." }, s.tasks)
    end)

    it("treats a reputation threshold as no count at all", function()
        local record = { t = { "Grab Abyssal Scepter.", "Make tree people like ape.", "Go back to Aurel Goldleaf." },
            n = 2, v = 3 }
        local live = {
            { type = "item", text = "Abyssal Scepter: 0/1", numFulfilled = 0, numRequired = 1 },
            { type = "reputation", text = "Cenarion Circle: Neutral / Friendly", numFulfilled = 1200, numRequired = 3000 },
        }
        local s = Compose.Build({ record = record, objectives = live, voice = "monke", showProgress = true })
        assert.are.same({ "Grab Abyssal Scepter.", "Make tree people like ape.", "Go back to Aurel Goldleaf." }, s.tasks)
    end)

    it("ignores records from a newer schema or with bad types", function()
        assert.is_nil(Compose.UsableRecord({ l = "x", v = 4 }))
        assert.is_nil(Compose.UsableRecord({ l = "x" }))
        assert.is_nil(Compose.UsableRecord({ l = 5, v = 3 }))
        assert.is_nil(Compose.UsableRecord({ t = { 1, 2 }, v = 3 }))
        assert.is_nil(Compose.UsableRecord("nope"))
        assert.is_nil(Compose.UsableRecord({ t = { "a" }, n = 2, v = 3 }))
        assert.is_nil(Compose.UsableRecord({ t = { "a" }, n = "1", v = 3 }))
        assert.is_not_nil(Compose.UsableRecord({ l = "x", v = 2 }))
    end)

    it("uses the other voice for lore when one is missing", function()
        assert.are.equal("only monke", Compose.Build({ record = { l = "only monke", v = 3 }, voice = "plain" }).lore)
        assert.are.equal("only plain", Compose.Build({ record = { p = "only plain", v = 3 }, voice = "monke" }).lore)
    end)

    it("hides lore when the setting is off", function()
        local s = Compose.Build({ record = RECORD_214, objectives = LIVE_214, voice = "monke", showLore = false })
        assert.is_nil(s.lore)
        assert.is_nil(s.loreMissing)
        assert.are.equal("", Compose.DescriptionText(s, "original"))
    end)

    describe("group line", function()
        it("appears for a suggested group", function()
            assert.are.equal("Bring 2 friends. Big danger.", Compose.Build({ voice = "monke", groupSize = 3 }).group)
            assert.are.equal("Suggested group: 3 players.", Compose.Build({ voice = "plain", groupSize = 3 }).group)
            assert.are.equal("Bring a friend. Big danger.", Compose.Build({ voice = "monke", groupSize = 2 }).group)
        end)
        it("appears for elite, dungeon and raid tags with no size", function()
            assert.are.equal("Bring friends. Big danger.", Compose.Build({ voice = "monke", groupTag = true }).group)
        end)
        it("prefers the DB line in monke voice only", function()
            local record = { g = "Big bad. Bring pack.", l = "x", v = 3 }
            assert.are.equal("Big bad. Bring pack.",
                Compose.Build({ record = record, voice = "monke", groupSize = 5 }).group)
            assert.are.equal("Suggested group: 5 players.",
                Compose.Build({ record = record, voice = "plain", groupSize = 5 }).group)
        end)
        it("is prepended to the description in colour", function()
            local s = Compose.Build({ record = RECORD_214, voice = "monke", groupSize = 3 })
            assert.are.equal("|cffff2020Bring 2 friends. Big danger.|r\n\n" .. RECORD_214.l, Compose.DescriptionText(s))
        end)
        it("stays away for solo quests and when switched off", function()
            assert.is_nil(Compose.Build({ voice = "monke", groupSize = 1 }).group)
            assert.is_nil(Compose.Build({ voice = "monke", groupSize = 5, showGroup = false }).group)
        end)
    end)

    describe("rewards", function()
        it("formats money", function()
            assert.are.equal("1g 4s 20c", Compose.Money(10420))
            assert.are.equal("2g", Compose.Money(20000))
            assert.is_nil(Compose.Money(0))
            assert.is_nil(Compose.Money(nil))
        end)
        it("lists xp, money, items and choices", function()
            local line = Compose.RewardsLine(
                { xp = 100, money = 250, items = { "Red Mask" }, choices = { "Axe", "Staff" } }, "monke")
            assert.are.equal("Monke get: 100 XP, 2s 50c, Red Mask, pick one: Axe / Staff", line)
        end)
        it("is absent when there is nothing to list", function()
            assert.is_nil(Compose.RewardsLine({ xp = 0, money = 0, items = {} }, "plain"))
            assert.is_nil(Compose.RewardsLine(nil, "plain"))
        end)
    end)

    describe("progress and complete pages", function()
        it("lists only objective bullets while unfinished", function()
            local s = Compose.Build({ record = RECORD_214, objectives = LIVE_214, voice = "monke", showProgress = true })
            assert.are.equal("Not done. Monke still need:\n\n" .. BULLET .. "Grab 10 Red Silk Bandana (3/10)",
                Compose.ProgressText(s, false))
        end)
        it("says so when ready", function()
            local s = Compose.Build({ record = RECORD_214, objectives = LIVE_214, voice = "plain" })
            assert.are.equal("Everything is done. Hand it in.", Compose.ProgressText(s, true))
        end)
        it("returns nil when it has nothing better than the original text", function()
            assert.is_nil(Compose.ProgressText(Compose.Build({ voice = "monke" }), false))
        end)
        it("complete page adds rewards", function()
            local s = Compose.Build({ voice = "monke", rewards = { xp = 50 } })
            assert.are.equal("Job done. Take shiny.\n\nMonke get: 50 XP", Compose.CompleteText(s))
        end)
    end)
end)
