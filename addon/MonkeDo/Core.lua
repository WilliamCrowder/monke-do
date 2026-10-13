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
    minimap = { hide = false },
}

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

function Core.ToggleOriginal()
    ns.state.showOriginal = not ns.state.showOriginal
    Core.NotifyChanged()
    return ns.state.showOriginal
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
        local original = Core.ToggleOriginal()
        Core.Print(original and "showing the original quest text" or "showing Monke Do text")
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
                Core.ToggleOriginal()
            end
        end,
        OnTooltipShow = function(tooltip)
            tooltip:AddLine("Monke Do")
            tooltip:AddLine("Click: swap Monke Do and original text", 1, 1, 1)
            tooltip:AddLine("Right-click: settings", 1, 1, 1)
        end,
    })
    if object then
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
    Core.Print("loaded. /monke for voice and options.")
end

SLASH_MONKEDO1 = "/monke"
SLASH_MONKEDO2 = "/monkedo"
SlashCmdList["MONKEDO"] = Core.HandleSlash

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" then
        if name == ADDON_NAME then
            Core.InitSettings()
        end
    elseif event == "PLAYER_LOGIN" then
        Core.OnLogin()
    end
end)
