-- Rent-a-Blorb -- player data persistence.
-- One DataStore key per player (UserId). Session data lives in-memory in `Cache`
-- while the player is in the server; SaveAsync only happens on leave/autosave/BindToClose.

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")

local BlorbData = require(game:GetService("ReplicatedStorage"):WaitForChild("BlorbShared"):WaitForChild("BlorbData"))

local PlayerDataManager = {}

local STORE_NAME = "RentABlorb_PlayerData_v1"

-- GetDataStore() itself throws (not just GetAsync/SetAsync) if this place has never been
-- published to Roblox (no place ID yet -- e.g. a Rojo-built .rbxlx opened directly in
-- Studio for local testing). Unprotected, that error used to kill this require() entirely,
-- which cascaded to every service below that requires PlayerDataManager, which meant
-- Main.server.lua never even reached TestWorldBuilder.Build(). Guard it so local/unpublished
-- testing still works -- data just won't persist between sessions until you publish.
local blorbStoreOk, blorbStore = pcall(function()
	return DataStoreService:GetDataStore(STORE_NAME)
end)
if not blorbStoreOk then
	warn("RentABlorb: DataStore unavailable this session (place not published yet, or Studio "
		.. "API access is off) -- player data will NOT persist between play sessions. Error: "
		.. tostring(blorbStore))
	blorbStore = nil
end

local Cache = {} -- [userId] = dataTable

local function defaultData()
	return {
		currency = BlorbData.Config.StarterCurrency,
		nextBlorbId = 1,
		blorbs = {}, -- [blorbId] = { id, species, rarityId, buffTypeId, hunger, generation, parentIds, standSlot }
		standSlots = {}, -- [slotIndex] = { blorbId, rentedByUserId, rentExpiresAt } or nil
		activeBuffs = {}, -- list of { buffTypeId, magnitude, expiresAt }
		stats = { rarestScore = 0, totalRented = 0, totalEarned = 0, totalSpent = 0 },
	}
end

function PlayerDataManager.Load(player)
	local stored = nil
	if blorbStore then
		local ok, result = pcall(function()
			return blorbStore:GetAsync("user_" .. player.UserId)
		end)
		if ok then
			stored = result
		end
	end

	local data = stored or defaultData()

	-- Backfill any fields added since a save was last written (keeps old saves loadable).
	local fresh = defaultData()
	for key, value in pairs(fresh) do
		if data[key] == nil then
			data[key] = value
		end
	end

	Cache[player.UserId] = data
	return data
end

function PlayerDataManager.Get(player)
	return Cache[player.UserId]
end

function PlayerDataManager.Save(player)
	local data = Cache[player.UserId]
	if not data then
		return
	end

	if not blorbStore then
		return -- DataStore unavailable this session (unpublished place) -- nothing to save to
	end

	local ok, err = pcall(function()
		blorbStore:SetAsync("user_" .. player.UserId, data)
	end)

	if not ok then
		warn(("RentABlorb: failed to save data for %s: %s"):format(player.Name, tostring(err)))
	end
end

function PlayerDataManager.Release(player)
	PlayerDataManager.Save(player)
	Cache[player.UserId] = nil
end

function PlayerDataManager.SaveAll()
	for _, player in ipairs(Players:GetPlayers()) do
		PlayerDataManager.Save(player)
	end
end

return PlayerDataManager
