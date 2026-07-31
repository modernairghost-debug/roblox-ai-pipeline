-- Rent-a-Blorb -- breeding: combine two owned Blorbs into a new one. Consumes both
-- parents plus a Snack cost -- this is the economy's sink against rental-Blorb inflation.

local BlorbData = require(game:GetService("ReplicatedStorage"):WaitForChild("BlorbShared"):WaitForChild("BlorbData"))
local Util = require(script.Parent:WaitForChild("Util"))
local PlayerDataManager = require(script.Parent:WaitForChild("PlayerDataManager"))
local LeaderboardService = require(script.Parent:WaitForChild("LeaderboardService"))

local BreedingService = {}

local function tierIndex(rarityId)
	for i, id in ipairs(BlorbData.RarityOrder) do
		if id == rarityId then
			return i
		end
	end
	return 1
end

function BreedingService.Breed(player, blorbIdA, blorbIdB)
	if blorbIdA == blorbIdB then
		return false, "Pick two different Blorbs"
	end

	local data = PlayerDataManager.Get(player)
	if not data then return false, "Data not loaded" end

	local parentA = data.blorbs[blorbIdA]
	local parentB = data.blorbs[blorbIdB]
	if not parentA or not parentB then
		return false, "You don't own both of those Blorbs"
	end
	if parentA.standSlot or parentB.standSlot then
		return false, "Take both Blorbs off their stands before breeding"
	end
	if data.currency < BlorbData.Config.BreedCost then
		return false, "Not enough Snacks"
	end

	data.currency -= BlorbData.Config.BreedCost
	data.stats.totalSpent += BlorbData.Config.BreedCost

	local betterTierIndex = math.max(tierIndex(parentA.rarityId), tierIndex(parentB.rarityId))
	local resultTierIndex = betterTierIndex
	if math.random() < BlorbData.Config.BreedTierUpChance and betterTierIndex < #BlorbData.RarityOrder then
		resultTierIndex += 1
	end
	local rarityId = BlorbData.RarityOrder[resultTierIndex]

	local species = Util.PickFrom({ parentA.species, parentB.species })
	local buffTypeId = Util.PickFrom(BlorbData.BuffTypeIds)

	-- Parents are consumed -- the sink that keeps rental Blorbs scarce.
	data.blorbs[blorbIdA] = nil
	data.blorbs[blorbIdB] = nil

	local blorbId = "blorb_" .. tostring(data.nextBlorbId)
	data.nextBlorbId += 1

	data.blorbs[blorbId] = {
		id = blorbId,
		species = species,
		rarityId = rarityId,
		buffTypeId = buffTypeId,
		hunger = BlorbData.Config.HungerMax,
		generation = math.max(parentA.generation, parentB.generation) + 1,
		parentIds = { blorbIdA, blorbIdB },
		standSlot = nil,
	}

	LeaderboardService.ReportScore(player, BlorbData.RarityTiers[rarityId].scoreValue)

	return true, blorbId
end

return BreedingService
