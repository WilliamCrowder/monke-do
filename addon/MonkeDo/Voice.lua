-- Voice.lua: every player-facing string, in both voices.
-- Templates use {token} slots filled by Voice.Format. pipeline/rules.py mirrors the
-- objective templates, so change both together.

local _, ns = ...

local Voice = {}
ns.Voice = Voice

Voice.DEFAULT = "monke"
Voice.BULLET = "\226\128\162 " -- U+2022 and a space

local STRINGS = {
    monke = {
        -- objective templates ("_one" is used when the amount is 1)
        monster = "Bonk {n} {name}.",
        monster_one = "Bonk {name}.",
        item = "Grab {n} {name}.",
        item_one = "Grab {name}.",
        object = "Poke {n} {name}.",
        object_one = "Poke {name}.",
        event = "Do the thing: {text}.",
        reputation = "Make {faction} like ape.",
        reputation_unknown = "Make {faction} like ape.",
        turnin = "Go back to {npc}.",
        turnin_other = "Go see {npc}.",
        turnin_unknown = "Go back. Get shiny.",
        done = "(done)",
        -- sections
        group = "Bring {friends} friends. Big danger.",
        group_one = "Bring a friend. Big danger.",
        group_tag = "Bring friends. Big danger.",
        tasks_header = "Monke do:",
        rewards = "Monke get: {list}",
        rewards_choice = "pick one: {list}",
        toggle_hint = "Long story? Poke {button}.", -- under Blizzard's own words when there is no lore
        waypoint = "Way: {text}.",                  -- the game's "which way" line, top of the log list
        progress_todo = "Not done. Monke still need:",
        progress_ready = "All done. Give stuff.",
        complete = "Job done. Take shiny.",
        -- toggle button
        toggle_to_original = "Wrinkle",
        toggle_to_monke = "Monke",
        toggle_tip_original = "Show the original quest text",
        toggle_tip_monke = "Show the Monke Do text",
        -- Now line and Monke pick
        now_nothing = "Nothing now. Click: Monke pick.",
        now_way = "Way: {text}",
        now_close = "close",
        now_yards = "{n} yd",
        now_more = "{n} more",
        now_tip_click = "Click: Monke pick quest. Click again: other quest.",
        now_tip_drag = "Drag: move line.",
        pick_none = "No quest. Monke go find quest giver.",
        pick_chat = "Monke pick: {title} \226\128\148 {task}",
    },
    plain = {
        monster = "Kill {n} {name}.",
        monster_one = "Kill {name}.",
        item = "Collect {n} {name}.",
        item_one = "Collect {name}.",
        object = "Use {n} {name}.",
        object_one = "Use {name}.",
        event = "{text}.",
        reputation = "Reach {standing} with {faction}.",
        reputation_unknown = "Earn reputation with {faction}.",
        turnin = "Return to {npc}.",
        turnin_other = "Go to {npc}.",
        turnin_unknown = "Turn in the quest.",
        done = "(done)",
        group = "Suggested group: {n} players.",
        group_one = "Suggested group: {n} players.",
        group_tag = "This is a group quest.",
        tasks_header = "To do:",
        rewards = "Rewards: {list}",
        rewards_choice = "choice of: {list}",
        toggle_hint = "Full text: press {button}.",
        waypoint = "Next: {text}.",
        progress_todo = "Still needed:",
        progress_ready = "Everything is done. Hand it in.",
        complete = "Quest complete. Collect your reward.",
        toggle_to_original = "Original",
        toggle_to_monke = "Short",
        toggle_tip_original = "Show the original quest text",
        toggle_tip_monke = "Show the short quest text",
        now_nothing = "Nothing tracked. Click to pick a quest.",
        now_way = "Next: {text}",
        now_close = "nearby",
        now_yards = "{n} yd",
        now_more = "{n} more",
        now_tip_click = "Click: pick a quest to do now. Click again for another.",
        now_tip_drag = "Drag: move this line.",
        pick_none = "No quests to pick. Find a quest giver.",
        pick_chat = "Picked: {title} \226\128\148 {task}",
    },
}

function Voice.IsVoice(voice)
    return STRINGS[voice] ~= nil
end

-- Unknown voices and keys fall back rather than error: a missing string must never
-- break the quest frame.
function Voice.Get(key, voice)
    local tbl = STRINGS[voice] or STRINGS[Voice.DEFAULT]
    return tbl[key] or STRINGS[Voice.DEFAULT][key] or ""
end

function Voice.Format(key, voice, vars)
    local template = Voice.Get(key, voice)
    local out = template:gsub("{(%w+)}", function(token)
        local value = vars and vars[token]
        if value == nil then
            return ""
        end
        return tostring(value)
    end)
    return out
end
