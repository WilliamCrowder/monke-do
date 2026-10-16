-- Core.lua: settings, slash commands, DB lookup, startup.
-- The Forever beta writes SavedVariables but does not load them, so every setting has a
-- sane default and nothing here depends on a value surviving a relog.

local ADDON_NAME, ns = ...

local Voice = ns.Voice

local Core = {}
ns.Core = Core

Core.DEFAULTS = {
    voice = "monke",
    showLore = true,
    groupWarning = true,
    tracker = true,
    nowLine = true,
    goldArrow = false, -- the Now line points with the monke finger unless this is on
    sounds = true,     -- "OK, monke do" / "Monke don't" when the original-text toggle flips
    monkeList = false, -- the Monke Do list: every quest's next step, nearest first
    minimap = { hide = false },
}

local MEDIA = "Interface\\AddOns\\MonkeDo\\Media\\"
local SOUND_MONKE_ON = MEDIA .. "monke_do.ogg"
local SOUND_MONKE_OFF = MEDIA .. "monke_dont.ogg"
local ORIGINAL_TINT = 0.4 -- the minimap banana, dimmed while the original text shows
local ACCEPT_GAP = 3       -- seconds: one "monke do" for a burst of accepts (a chain, a share)

-- Per-session on purpose (see the header note). showOriginal is the lore toggle.
ns.state = { showOriginal = false }

local PREFIX = "|cffd2a679Monke Do|r: "
local listeners = {}

function Core.Print(message)
    print(PREFIX .. tostring(message))
end

local function copyDefaults(defaults, target)
    for key, value in pairs(defaults) do
        if type(value) == "table" then
            if type(target[key]) ~= "table" then
                target[key] = {}
            end
            copyDefaults(value, target[key])
        elseif type(target[key]) ~= type(value) then
            target[key] = value
        end
    end
end

function Core.InitSettings()
    if type(MonkeDoDB) ~= "table" then
        MonkeDoDB = {}
    end
    copyDefaults(Core.DEFAULTS, MonkeDoDB)
    if not Voice.IsVoice(MonkeDoDB.voice) then
        MonkeDoDB.voice = Core.DEFAULTS.voice
    end
    ns.settings = MonkeDoDB
    return MonkeDoDB
end

function Core.Get(key)
    local settings = ns.settings or Core.InitSettings()
    return settings[key]
end

function Core.Set(key, value)
    local settings = ns.settings or Core.InitSettings()
    settings[key] = value
    Core.NotifyChanged()
end

-- For a value that changes nothing on screen by itself (the Now line's position): saved,
-- with no redraw.
function Core.Store(key, value)
    local settings = ns.settings or Core.InitSettings()
    settings[key] = value
end

-- Display and Tracker register here so a settings change redraws what is on screen.
function Core.OnChange(fn)
    listeners[#listeners + 1] = fn
end

function Core.NotifyChanged()
    for _, fn in ipairs(listeners) do
        fn()
    end
end

function Core.GetRecord(questID)
    local db = MonkeDB
    if type(db) ~= "table" or type(questID) ~= "number" then
        return nil
    end
    return db[questID]
end

-- The voice line playing now: the next one cuts it off rather than talk over it (the toggle is
-- often flipped and flipped back inside the 2.5 seconds a line lasts).
local voiceHandle

-- Plays one voice line; true when the client will play it.
local function playVoice(path)
    if not PlaySoundFile then
        return false
    end
    if voiceHandle and StopSound then
        StopSound(voiceHandle)
    end
    local willPlay, handle = PlaySoundFile(path, "SFX")
    voiceHandle = willPlay and handle or nil
    return willPlay and true or false
end

-- The voice line for the state just switched to. A client that cannot play the file (none
-- shipped yet, or no PlaySoundFile) gets the settings checkbox click instead.
local function playToggleSound(original)
    if not Core.Get("sounds") then
        return
    end
    local played = playVoice(original and SOUND_MONKE_OFF or SOUND_MONKE_ON)
    if not played and PlaySound and SOUNDKIT then
        local kit = original and SOUNDKIT.IG_MAINMENU_OPTION_CHECKBOX_OFF or SOUNDKIT.IG_MAINMENU_OPTION_CHECKBOX_ON
        if kit then
            PlaySound(kit)
        end
    end
end

-- The minimap banana shows which text is on: full colour for Monke Do, dimmed for the original.
-- LibDBIcon redraws the button when these LibDataBroker attributes change.
function Core.UpdateMinimap()
    local object = Core.minimapObject
    if not object then
        return
    end
    local tint = ns.state.showOriginal and ORIGINAL_TINT or 1
    object.iconR, object.iconG, object.iconB = tint, tint, tint
end

function Core.ToggleOriginal()
    ns.state.showOriginal = not ns.state.showOriginal
    Core.NotifyChanged()
    Core.UpdateMinimap()
    playToggleSound(ns.state.showOriginal)
    return ns.state.showOriginal
end

-- Accepting a quest while Monke Do text is on: "OK, monke do". Not for the area tasks, world
-- quests and bounties the client also reports as accepted, and once per burst. Blizzard's own
-- accept sound still plays, so there is no fallback click here.
local lastAcceptSound
function Core.OnQuestAccepted(questID)
    if ns.state.showOriginal or not Core.Get("sounds") or type(questID) ~= "number" then
        return
    end
    local log = C_QuestLog
    if log and ((log.IsQuestTask and log.IsQuestTask(questID)) or (log.IsWorldQuest and log.IsWorldQuest(questID))
            or (log.IsQuestBounty and log.IsQuestBounty(questID))) then
        return
    end
    local now = GetTime and GetTime() or 0
    if lastAcceptSound and now - lastAcceptSound < ACCEPT_GAP then
        return
    end
    lastAcceptSound = now
    playVoice(SOUND_MONKE_ON)
end

function Core.OriginalStateText(original)
    return original and "showing the original quest text" or "showing Monke Do text"
end

function Core.VersionText()
    local version = "dev"
    if C_AddOns and C_AddOns.GetAddOnMetadata then
        version = C_AddOns.GetAddOnMetadata(ADDON_NAME, "Version") or version
    end
    local meta = MonkeDB_Meta
    if type(meta) ~= "table" then
        return ("v%s, no quest database loaded"):format(version)
    end
    return ("v%s, %d quests, game build %s, generated %s"):format(
        version, meta.count or 0, tostring(meta.build or "unknown"), tostring(meta.generated or "unknown"))
end

function Core.OpenSettings()
    if Core.categoryID and Settings and Settings.OpenToCategory then
        Settings.OpenToCategory(Core.categoryID)
    else
        Core.PrintHelp()
    end
end

function Core.PrintHelp()
    Core.Print("commands")
    print("  /monke - open the settings")
    print("  /monke lore - swap between Monke Do text and the original")
    print("  /monke voice monke||plain")
    print("  /monke showlore on||off")
    print("  /monke group on||off")
    print("  /monke tracker on||off")
    print("  /monke pick - which quest now? Again: the next one. A key for it: Keybindings, AddOns")
    print("  /monke now on||off||reset - the Now line at the bottom middle of the screen")
    print("  /monke pointer finger||arrow - the monke finger or a gold arrow points the way")
    print("  /monke list on||off||reset - the Monke Do list: every quest's next step, nearest first")
    print("  /monke sound on||off - \"OK, monke do\" and \"Monke don't\" when the text swaps or a quest is taken")
    print("  /monke version")
end

local function parseSwitch(word, current)
    if word == "on" then
        return true
    elseif word == "off" then
        return false
    end
    return not current
end

local function onOff(value)
    return value and "on" or "off"
end

function Core.HandleSlash(message)
    local command, rest = (message or ""):lower():match("^%s*(%S*)%s*(.-)%s*$")
    if command == "" then
        Core.OpenSettings()
    elseif command == "lore" then
        Core.Print(Core.OriginalStateText(Core.ToggleOriginal()))
    elseif command == "voice" then
        if Voice.IsVoice(rest) then
            Core.Set("voice", rest)
        elseif rest == "" then
            Core.Set("voice", Core.Get("voice") == "monke" and "plain" or "monke")
        else
            Core.Print("voice is monke or plain")
            return
        end
        Core.Print("voice: " .. Core.Get("voice"))
    elseif command == "showlore" then
        Core.Set("showLore", parseSwitch(rest, Core.Get("showLore")))
        Core.Print("lore: " .. onOff(Core.Get("showLore")))
    elseif command == "group" then
        Core.Set("groupWarning", parseSwitch(rest, Core.Get("groupWarning")))
        Core.Print("group warning: " .. onOff(Core.Get("groupWarning")))
    elseif command == "tracker" then
        Core.Set("tracker", parseSwitch(rest, Core.Get("tracker")))
        Core.Print("tracker text: " .. onOff(Core.Get("tracker")))
    elseif command == "pick" then
        if ns.Pick then
            ns.Pick.Next()
        end
    elseif command == "now" then
        if rest == "reset" then
            if ns.Now then
                ns.Now.ResetPosition()
            end
            Core.Print("Now line: back in its first spot")
            return
        end
        Core.Set("nowLine", parseSwitch(rest, Core.Get("nowLine")))
        Core.Print("Now line: " .. onOff(Core.Get("nowLine")))
    elseif command == "pointer" then
        if rest == "arrow" or rest == "gold" then
            Core.Set("goldArrow", true)
        elseif rest == "finger" or rest == "monke" then
            Core.Set("goldArrow", false)
        else
            Core.Set("goldArrow", not Core.Get("goldArrow"))
        end
        Core.Print("pointer: " .. (Core.Get("goldArrow") and "gold arrow" or "monke finger"))
    elseif command == "list" then
        if rest == "reset" then
            if ns.List then
                ns.List.ResetPosition()
            end
            Core.Print("Monke Do list: back in its first spot")
            return
        end
        Core.Set("monkeList", parseSwitch(rest, Core.Get("monkeList")))
        Core.Print("Monke Do list: " .. onOff(Core.Get("monkeList")))
    elseif command == "sound" or command == "sounds" then
        Core.Set("sounds", parseSwitch(rest, Core.Get("sounds")))
        Core.Print("sounds: " .. onOff(Core.Get("sounds")))
    elseif command == "version" then
        Core.Print(Core.VersionText())
    else
        Core.PrintHelp()
    end
end

-- Blizzard settings panel. The Settings API has changed shape between patches, so the whole
-- thing runs under pcall and the slash commands stay the fallback.
local function buildSettingsPanel()
    if not (Settings and Settings.RegisterVerticalLayoutCategory and Settings.RegisterAddOnSetting) then
        return
    end
    local settings = ns.settings
    local category = Settings.RegisterVerticalLayoutCategory("Monke Do")

    local function register(key, varType, label)
        local setting = Settings.RegisterAddOnSetting(
            category, "MonkeDo_" .. key, key, settings, varType, label, Core.DEFAULTS[key])
        setting:SetValueChangedCallback(function()
            Core.NotifyChanged()
        end)
        return setting
    end

    local function voiceOptions()
        local container = Settings.CreateControlTextContainer()
        container:Add("monke", "Monke")
        container:Add("plain", "Plain English")
        return container:GetData()
    end
    Settings.CreateDropdown(category, register("voice", "string", "Voice"), voiceOptions,
        "Monke is the caveman voice. Plain English says the same thing without the joke.")
    Settings.CreateCheckbox(category, register("showLore", "boolean", "Show lore"),
        "Show the one or two sentence story above the task list.")
    Settings.CreateCheckbox(category, register("groupWarning", "boolean", "Group warning"),
        "Warn at the top of the quest when it is meant for a group.")
    Settings.CreateCheckbox(category, register("tracker", "boolean", "Tracker text"),
        "Use the same short wording in the objective tracker.")
    Settings.CreateCheckbox(category, register("nowLine", "boolean", "Now line"),
        "One next step for the tracked quest, and how far away it is, at the bottom middle of the "
        .. "screen. Drag it anywhere. Click it for Monke pick. A key for Monke pick: Keybindings, AddOns.")
    Settings.CreateCheckbox(category, register("goldArrow", "boolean", "Gold arrow"),
        "On the Now line, point the way with a gold arrow instead of the monke finger.")
    Settings.CreateCheckbox(category, register("monkeList", "boolean", "Monke Do list"),
        "A list of every quest's next step, nearest first. Click a line to track that quest. "
        .. "Drag its title to move it.")
    Settings.CreateCheckbox(category, register("sounds", "boolean", "Sounds"),
        "Say \"OK, monke do\" or \"Monke don't\" when you swap between Monke Do and the original text, "
        .. "and \"OK, monke do\" when you accept a quest.")

    Settings.RegisterAddOnCategory(category)
    Core.categoryID = category:GetID()
end

local function buildMinimapButton()
    if not LibStub then
        return
    end
    local broker = LibStub("LibDataBroker-1.1", true)
    local icon = LibStub("LibDBIcon-1.0", true)
    if not (broker and icon) then
        return
    end
    local object = broker:NewDataObject("MonkeDo", {
        type = "launcher",
        text = "Monke Do",
        icon = "Interface\\AddOns\\MonkeDo\\Media\\minimap.png",
        OnClick = function(_, button)
            if button == "RightButton" then
                Core.OpenSettings()
            else
                Core.Print(Core.OriginalStateText(Core.ToggleOriginal()))
            end
        end,
        OnTooltipShow = function(tooltip)
            tooltip:AddLine("Monke Do")
            if ns.state.showOriginal then
                tooltip:AddLine("Showing: the original quest text", 0.7, 0.7, 0.7)
                tooltip:AddLine("Click: Monke Do text", 1, 1, 1)
            else
                tooltip:AddLine("Showing: Monke Do text", 1, 0.82, 0)
                tooltip:AddLine("Click: the original quest text", 1, 1, 1)
            end
            tooltip:AddLine("Right-click: settings", 1, 1, 1)
        end,
    })
    if object then
        Core.minimapObject = object
        Core.UpdateMinimap()
        icon:Register("MonkeDo", object, ns.settings.minimap)
    end
end

-- Named in the TOC as ## AddonCompartmentFunc.
function MonkeDo_OnAddonCompartmentClick()
    Core.OpenSettings()
end

-- Named in Bindings.xml (binding MONKEDO_PICK). The labels show in Keybindings, AddOns.
BINDING_NAME_MONKEDO_PICK = "Monke Do: which quest now?"

function MonkeDo_Pick()
    if ns.Pick then
        return ns.Pick.Next()
    end
end

function Core.OnLogin()
    local ok, err = pcall(buildSettingsPanel)
    if not ok then
        Core.settingsError = err
    end
    pcall(buildMinimapButton)
    if ns.Display then
        ns.Display.Enable()
    end
    if ns.Tracker then
        ns.Tracker.Enable()
    end
    if ns.Now then
        ns.Now.Enable()
    end
    if ns.List then
        ns.List.Enable()
    end
    Core.Print("loaded. /monke for voice and options.")
end

SLASH_MONKEDO1 = "/monke"
SLASH_MONKEDO2 = "/monkedo"
SlashCmdList["MONKEDO"] = Core.HandleSlash

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
pcall(frame.RegisterEvent, frame, "QUEST_ACCEPTED") -- a build without it only loses the sound
frame:SetScript("OnEvent", function(_, event, arg)
    if event == "ADDON_LOADED" then
        if arg == ADDON_NAME then
            Core.InitSettings()
        end
    elseif event == "PLAYER_LOGIN" then
        Core.OnLogin()
    elseif event == "QUEST_ACCEPTED" then
        Core.OnQuestAccepted(arg)
    end
end)
