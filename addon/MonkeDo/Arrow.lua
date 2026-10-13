-- Arrow.lua: which way to turn. Works out where the super-tracked quest's next spot is from the
-- player, as a turn for the Now line's arrow: 0 is straight ahead and a positive turn is to the
-- left (counter-clockwise), which is what Texture:SetRotation expects of an arrow drawn pointing
-- up.
--
-- Everything is done on the player's own map, where x grows to the east and y to the south,
-- scaled to yards by the map's world size. The spot is the game's next waypoint (a boat, a
-- portal) when there is one, else the quest's map marker. A spot on another map is carried onto
-- the player's map through world coordinates, on the same continent only. GetPlayerFacing gives
-- 0 for north, growing counter-clockwise. Inside instances the game gives no position or facing,
-- so there is no arrow there. Reads game state only; it draws nothing.

local _, ns = ...

local Pick = ns.Pick

local Arrow = {}
ns.Arrow = Arrow

local CLOSE_YARDS = 30 -- as the Now line's "close": the spot is here, no arrow needed
local PARENT_MAPS = 2  -- also look for the quest's marker this many maps up (zone, continent)
local TWO_PI = 2 * math.pi

local cached -- the last lookup, until Arrow.Forget, another quest or another map

-- A finite number this code may do sums with, else nil.
local function number(value)
    if Pick.IsSecret(value) or type(value) ~= "number" then
        return nil
    end
    if value ~= value or value == math.huge or value == -math.huge then
        return nil
    end
    return value
end

-- x, y of a Vector2D (the game's map positions), or nil.
local function xy(vector)
    if type(vector) ~= "table" then
        return nil
    end
    local x, y = vector.x, vector.y
    if (x == nil or y == nil) and vector.GetXY then
        x, y = vector:GetXY()
    end
    x, y = number(x), number(y)
    if x and y then
        return x, y
    end
    return nil
end

local function playerMap()
    if not (C_Map and C_Map.GetBestMapForUnit) then
        return nil
    end
    return number(C_Map.GetBestMapForUnit("player"))
end

-- The turn, in radians within (-pi, pi], from `facing` toward a spot dEast yards east and
-- dSouth yards south of the player. nil when the spot is within CLOSE_YARDS.
function Arrow.Rotation(dEast, dSouth, facing)
    if dEast * dEast + dSouth * dSouth < CLOSE_YARDS * CLOSE_YARDS then
        return nil
    end
    local bearing = math.atan2(-dEast, -dSouth) -- from north, counter-clockwise, like facing
    local turn = (bearing - facing) % TWO_PI
    if turn > math.pi then
        turn = turn - TWO_PI
    end
    return turn
end

-- The maps to look for the quest's marker on: the quest's own, the player's, and the ones
-- above the player's.
local function markerMaps(questID, map)
    local maps, seen = {}, {}
    local function add(mapID)
        mapID = number(mapID)
        if mapID and mapID > 0 and not seen[mapID] then
            seen[mapID] = true
            maps[#maps + 1] = mapID
        end
    end
    if GetQuestUiMapID then
        add(GetQuestUiMapID(questID))
    end
    add(map)
    local up = map
    for _ = 1, PARENT_MAPS do
        local info = C_Map and C_Map.GetMapInfo and C_Map.GetMapInfo(up)
        up = type(info) == "table" and number(info.parentMapID) or nil
        if not up or up <= 0 then
            break
        end
        add(up)
    end
    return maps
end

-- The quest's next spot as mapID, x, y: the game's waypoint first, else its map marker.
local function questSpot(questID, map)
    if not C_QuestLog then
        return nil
    end
    if C_QuestLog.GetNextWaypoint then
        local mapID, x, y = C_QuestLog.GetNextWaypoint(questID)
        mapID, x, y = number(mapID), number(x), number(y)
        if mapID and x and y then
            return mapID, x, y
        end
    end
    if not C_QuestLog.GetQuestsOnMap then
        return nil
    end
    for _, mapID in ipairs(markerMaps(questID, map)) do
        local markers = C_QuestLog.GetQuestsOnMap(mapID)
        if type(markers) == "table" then
            for _, marker in ipairs(markers) do
                if type(marker) == "table" and not Pick.IsSecret(marker.questID) and marker.questID == questID then
                    local x, y = number(marker.x), number(marker.y)
                    if x and y then
                        return mapID, x, y
                    end
                end
            end
        end
    end
    return nil
end

-- A spot on mapID carried onto `map`, through world coordinates; nil across continents.
local function onMap(mapID, x, y, map)
    if mapID == map then
        return x, y
    end
    if not (C_Map and C_Map.GetWorldPosFromMapPos and C_Map.GetMapPosFromWorldPos and CreateVector2D) then
        return nil
    end
    local continent, world = C_Map.GetWorldPosFromMapPos(mapID, CreateVector2D(x, y))
    local here = C_Map.GetWorldPosFromMapPos(map, CreateVector2D(0.5, 0.5))
    continent, here = number(continent), number(here)
    if not (continent and here and continent == here and type(world) == "table") then
        return nil
    end
    local _, position = C_Map.GetMapPosFromWorldPos(continent, world, map)
    return xy(position)
end

-- The quest's spot on the player's map `map`, with that map's size in yards, or nil.
function Arrow.Target(questID, map)
    map = map or playerMap()
    if not (questID and map and C_Map and C_Map.GetMapWorldSize) then
        return nil
    end
    local width, height = C_Map.GetMapWorldSize(map)
    width, height = number(width), number(height)
    if not (width and height and width > 0 and height > 0) then
        return nil
    end
    local spotMap, spotX, spotY = questSpot(questID, map)
    if not spotMap then
        return nil
    end
    local x, y = onMap(spotMap, spotX, spotY, map)
    if not (x and y) then
        return nil
    end
    return { questID = questID, map = map, x = x, y = y, width = width, height = height }
end

-- Look the spot up again on the next turn (the quest moved on, or a second went by).
function Arrow.Forget()
    cached = nil
end

-- The arrow's turn toward the quest's next spot, or nil for no arrow: no position or facing
-- (an instance), no spot the game will tell (no marker, another continent), or the spot is close.
-- The spot is looked up once and kept until Arrow.Forget, another quest or another map; only
-- the player's position and facing are read every time.
function Arrow.Turn(questID)
    local map = playerMap()
    if not (questID and map) then
        return nil
    end
    if not (cached and cached.questID == questID and cached.map == map) then
        cached = Arrow.Target(questID, map) or { questID = questID, map = map } -- "no spot" is kept too
    end
    if not (cached.x and C_Map.GetPlayerMapPosition and GetPlayerFacing) then
        return nil
    end
    local px, py = xy(C_Map.GetPlayerMapPosition(map, "player"))
    local facing = number(GetPlayerFacing())
    if not (px and facing) then
        return nil
    end
    return Arrow.Rotation((cached.x - px) * cached.width, (cached.y - py) * cached.height, facing)
end
