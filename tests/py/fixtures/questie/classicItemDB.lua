-- TEST FIXTURE: same format as Questie's classicItemDB.lua, invented rows (915 is real).
local QuestieDB = QuestieLoader:ImportModule("QuestieDB");

QuestieDB.itemKeys = {
    ['name'] = 1, -- string
    ['npcDrops'] = 2, -- table or nil, NPC IDs
    ['objectDrops'] = 3, -- table or nil, object IDs
}

QuestieDB.itemData = [[return {
[915] = {'Red Silk Bandana',{589,590},nil},
[9401] = {'Chunk of Mossy Bark',nil,{9302}},
[9402] = {'Bog Iron',nil,nil},
[9403] = {'Warden\'s Primer',nil,nil},
[9404] = {'Reaper 6000 Blueprints',nil,nil},
}]]
