-- TEST FIXTURE: same format as Questie's classicNpcDB.lua, invented rows (820 is real).
local QuestieDB = QuestieLoader:ImportModule("QuestieDB");

QuestieDB.npcKeys = {
    ['name'] = 1, -- string
    ['minLevelHealth'] = 2, -- int
    ['maxLevelHealth'] = 3, -- int
    ['minLevel'] = 4, -- int
    ['maxLevel'] = 5, -- int
    ['rank'] = 6, -- int
    ['spawns'] = 7, -- table {[zoneID(int)] = {coordPair(floatVector2D),...},...}
    ['waypoints'] = 8, -- table
    ['zoneID'] = 9, -- guess as to where this NPC is most common
}

QuestieDB.npcData = [[return {
[820] = {'Scout Riell',573,573,21,21,0,{[40]={{56.41,47.61}}},nil,40},
[9101] = {'Warden Halla',100,100,10,10,0,{[40]={{10.5,20.25},{11.0,-3.5}}},nil,40},
[9102] = {'Elder "Two-Braids" Moss',100,100,10,10,0,nil,nil,40},
[9201] = {'Gray Wolf',55,60,5,6,0,{[40]={{1.0,2.0}}},nil,40},
[9202] = {'Ridge Stalker',55,60,6,7,0,nil,nil,40},
[9203] = {'Marsh Raider Scout',300,320,20,21,0,nil,nil,40},
[9204] = {'Marsh Raider Brute',300,320,21,22,0,nil,nil,40},
[9205] = {'Tide Coastrunner',120,130,10,11,0,nil,nil,40},
}]]
