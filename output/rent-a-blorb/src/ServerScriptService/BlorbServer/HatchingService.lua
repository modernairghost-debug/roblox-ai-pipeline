-- Rent-a-Blorb -- hatching. Buying an egg immediately hatches it (no separate egg
-- inventory in this MVP -- see BUILD_NOTES.md for why).

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local BlorbData = require(ReplicatedStorage:WaitForChild("BlorbShared"):WaitForChild("BlorbData"))
local Util = require(script.Parent:WaitForChild("Util"))
local PlayerDataManager = require(script.Parent:WaitForChild("PlayerDataManager"))
local RentalService = require(script.Parent:WaitForChild("RentalService"))
local LeaderboardService = require(script.Parent:WaitForChild("LeaderboardService"))

local HatchingService = {}

local EGG_PRICES = {
	BasicEgg = BlorbData.Config.BasicEggPrice,
	RareEgg = BlorbData.Config.RareEggPrice,
}

local function rollRarity(weights, luckMultiplier)
	if luckMultiplier <= 1.0 then
		return Util.WeightedPick(weights)
	end

	-- LuckBoost nudges weight from Common into Mythic without guaranteeing anything --
	-- keeps the buff meaningful without breaking the economy.
	local boosted = {}
	for tier, weight in pairs(weights) do
		boosted[tier] = weight
	end
	local shift = (boosted.Common or 0) * 0.15 * (luckMultiplier - 1.0)
	boosted.Common = math.max(0, (boosted.Common or 0) - shift)
	boosted.Mythic = (boosted.Mythic or 0) + shift

	return Util.WeightedPick(boosted)
end

-- eggTypeId: "BasicEgg" | "RareEgg"
function HatchingService.BuyAndHatch(player, eggTypeId)
	local price = EGG_PRICES[eggTypeId]
	if not price then
		return false, "Unknown egg type"
	end

	local data = PlayerDataManager.Get(player)
	if not data then
		return false, "Data not loaded"
	end

	if data.currency < price then
		return false, "Not enough Snacks"
	end

	local weights
	if eggTypeId == "RareEgg" then
		weights = BlorbData.RareEggHatchWeights
	else
		weights = {}
		for tier, info in pairs(BlorbData.RarityTiers) do
			weights[tier] = info.hatchWeight
		end
	end

	data.currency -= price
	data.stats.totalSpent += price

	local luckMultiplier = RentalService.GetActiveBuffMagnitude(data, "LuckBoost")
	local rarityId = rollRarity(weights, luckMultiplier)
	local species = Util.PickFrom(BlorbData.Species)
	local buffTypeId = Util.PickFrom(BlorbData.BuffTypeIds)

	local blorbId = "blorb_" .. tostring(data.nextBlorbId)
	data.nextBlorbId += 1

	data.blorbs[blorbId] = {
		id = blorbId,
		species = species,
		rarityId = rarityId,
		buffTypeId = buffTypeId,
		hunger = BlorbData.Config.HungerMax,
		generation = 1,
		parentIds = nil,
		standSlot = nil,
	}

	LeaderboardService.ReportScore(player, BlorbData.RarityTiers[rarityId].scoreValue)

	return true, blorbId
end

return HatchingService
