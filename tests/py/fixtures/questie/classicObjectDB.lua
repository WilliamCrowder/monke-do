-- TEST FIXTURE: same format as Questie's classicObjectDB.lua, invented rows.
local QuestieDB = QuestieLoader:ImportModule("QuestieDB");

QuestieDB.objectKeys = {
    ['name'] = 1, -- string
    ['questStarts'] = 2, -- table {questID(int),...}
    ['questEnds'] = 3, -- table {questID(int),...}
    ['spawns'] = 4, -- table
    ['zoneID'] = 5,
}

QuestieDB.objectData = [[return {
[9301] = {"Old Signpost",nil,{9002},{[40]={{41.52,54.66}}},40},
[9302] = {"Sunken Crate",nil,nil,{[40]={{25.97,16.91}}},40},
}]]
