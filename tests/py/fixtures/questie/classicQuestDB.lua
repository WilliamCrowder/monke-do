-- AUTO GENERATED FILE! DO NOT EDIT!
-- TEST FIXTURE: same format as Questie's classicQuestDB.lua. Row 214 is the real one,
-- every other row is invented.

---@type QuestieDB
--[[ a block comment in the header: QuestieDB.questKeys = { ['name'] = 99 } ]]
local QuestieDB = QuestieLoader:ImportModule("QuestieDB");

QuestieDB.questKeys = {
    ['name'] = 1, -- string
    ['startedBy'] = 2, -- table
        --['creatureStart'] = 1, -- table {creature(int),...}
        --['objectStart'] = 2, -- table {object(int),...}
        --['itemStart'] = 3, -- table {item(int),...}
    ['finishedBy'] = 3, -- table
        --['creatureEnd'] = 1, -- table {creature(int),...}
        --['objectEnd'] = 2, -- table {object(int),...}
    ['requiredLevel'] = 4, -- int
    ['questLevel'] = 5, -- int
    ['requiredRaces'] = 6, -- bitmask
    ['requiredClasses'] = 7, -- bitmask
    ['objectivesText'] = 8, -- table: {string,...}, Description of the quest. Auto-complete if nil.
    ['triggerEnd'] = 9, -- table: {text, {[zoneID] = {coordPair,...},...}}
    ['objectives'] = 10, -- table
        --['creatureObjective'] = 1, -- table {{creature(int), text(string), iconFile},...}
        --['objectObjective'] = 2, -- table {{object(int), text(string), iconFile},...}
        --['itemObjective'] = 3, -- table {{item(int), text(string), iconFile},...}
        --['reputationObjective'] = 4, -- table: {faction(int), value(int)}
        --['killCreditObjective'] = 5, -- table: {{{creature(int), ...}, baseCreatureID, baseCreatureText, iconFile}, ...}
        --['spellObjective'] = 6, -- table: {{spell(int), text(string), item(int)},...}
    ['sourceItemId'] = 11, -- int, item provided by quest starter
    ['preQuestGroup'] = 12, -- table: {quest(int)}
    ['preQuestSingle'] = 13, -- table: {quest(int)}
    ['childQuests'] = 14, -- table: {quest(int)}
    ['inGroupWith'] = 15, -- table: {quest(int)}
    ['exclusiveTo'] = 16, -- table: {quest(int)}
    ['zoneOrSort'] = 17, -- int, >0: AreaTable.dbc ID; <0: QuestSort.dbc ID
    ['requiredSkill'] = 18, -- table: {skill(int), value(int)}
    ['requiredMinRep'] = 19, -- table: {faction(int), value(int)}
    ['requiredMaxRep'] = 20, -- table: {faction(int), value(int)}
    ['requiredSourceItems'] = 21, -- table: {item(int), ...}
    ['nextQuestInChain'] = 22, -- int
    ['questFlags'] = 23, -- bitmask
    ['specialFlags'] = 24, -- bitmask
    ['parentQuest'] = 25, -- int
    ['reputationReward'] = 26, -- table: {{faction(int), value(int)},...}
}

QuestieDB.questData = [[return {
[214] = {"Red Silk Bandanas",{{820}},{{820}},14,17,77,nil,{"Scout Riell at the Sentinel Hill Tower wants you to bring her 10 Red Silk Bandanas."},nil,{nil,nil,{{915}}},nil,nil,{155},nil,nil,nil,1581,nil,nil,nil,nil,nil,8,nil,nil,{{72,250}}},
[9001] = {"Wolves at the Gate",{{9101}},{{9101}},5,7,nil,nil,{"Kill 8 Gray Wolves and 5 Ridge Stalkers, then return to Warden Halla."},nil,{{{9201},{9202,"Ridge Stalker slain"}}},nil,nil,nil,nil,nil,nil,-22,nil,nil,nil,nil,nil,0x10},
-- a line comment between rows, with a brace { that must not count
[9002] = {"Bark and Iron",{{9101}},{nil,{9301}},8,10,nil,nil,{"Bring 6 Chunks of Mossy Bark and 4 pieces of Bog Iron to the Old Signpost."},nil,{nil,{{9302,"Search the sunken crate"}},{{9401},{9402}}},nil,nil,nil,nil,nil,nil,40},
-- [9999] = {"Commented Out Quest",nil,nil,1,1},
[9003] = {"Trust of the Wardens",{{9101}},{{9102}},20,22,nil,nil,{"Slay 12 Marsh Raiders and earn the trust of the wardens."},nil,{nil,nil,nil,{59,3000},{{{9203,9204},9203,"Marsh Raider"}},{{7001,"Learn the warden's ritual",9403}}},nil,nil,nil,nil,nil,nil,40,nil,nil,nil,nil,nil,8},
[9004] = {"A Quiet Word",{{9101}},{{9102}},1,1,nil,nil,nil,nil,nil},
[9005] = {'Halla\'s Request',{{9101}},{{9101}},10,12,nil,nil,{"Kill 7 Coastrunners, $N.","","Then report to Warden Halla.$B"},nil,
    {{{9205}}},
    nil,nil,nil,nil,nil,nil,40,nil,nil,nil,nil,nil,0},
[9006] = {"Stolen Plans",{{9101}},{{9101}},30,32,nil,nil,{"Get the Reaper 6000 Blueprints for Warden Halla."},nil,{nil,nil,{{9404}}}},
[9007] = {nil,nil,nil,1,1},
}]]
