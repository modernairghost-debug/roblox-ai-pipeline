-- Rent-a-Blorb -- hunger decay + feeding. A starved Blorb can't be rented, which is the
-- game's only real "maintenance" pressure on top of the rent loop.

local BlorbData = require(game:GetService("ReplicatedStorage"):WaitForChild("BlorbShared"):WaitForChild("BlorbData"))
local PlayerDataManager = require(script.Parent:WaitForChild("PlayerDataManager"))
local RentalService = require(script.Parent:WaitForChild("RentalService"))

local FeedingService = {}

function FeedingService.Feed(player, blorbId)
	local data = PlayerDataManager.Get(player)
	if not data then
		return false, "Data not loaded"
	end

	local blorb = data.blorbs[blorbId]
	if not blorb then
		return false, "You don't own that Blorb"
	end

	if blorb.hunger >= BlorbData.Config.HungerMax then
		return false, "Already full"
	end

	if data.currency < BlorbData.Config.FeedCost then
		return false, "Not enough Snacks"
	end

	data.currency -= BlorbData.Config.FeedCost
	blorb.hunger = math.min(BlorbData.Config.HungerMax, blorb.hunger + BlorbData.Config.FeedRestoreAmount)

	return true, blorb.hunger
end

-- Called on a slow repeating loop from Main.server.lua for every online player.
function FeedingService.DecayTick(player, minutesElapsed)
	local data = PlayerDataManager.Get(player)
	if not data then
		return
	end

	local decay = BlorbData.Config.HungerDecayPerMinute * minutesElapsed
	for _, blorb in pairs(data.blorbs) do
		blorb.hunger = math.max(0, blorb.hunger - decay)
		if blorb.hunger <= BlorbData.Config.StarvedHungerThreshold and blorb.standSlot then
			-- Starved Blorbs get pulled off the rental stand automatically.
			RentalService.ForceRemoveFromStand(player, blorb.standSlot)
		end
	end
end

return FeedingService
