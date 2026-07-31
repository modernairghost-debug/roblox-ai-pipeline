-- Rent-a-Blorb -- simulated NPC customers. Solves the cold-start problem (an idle stand
-- earns something even with no other players online) without out-competing real
-- player-to-player renting, which pays full price and this deliberately doesn't.

local Players = game:GetService("Players")
local BlorbData = require(game:GetService("ReplicatedStorage"):WaitForChild("BlorbShared"):WaitForChild("BlorbData"))
local PlayerDataManager = require(script.Parent:WaitForChild("PlayerDataManager"))
local RentalService = require(script.Parent:WaitForChild("RentalService"))

local CustomerSimService = {}

local nextVisitAt = {} -- [userId] = os.time() of next customer check

local function scheduleNext(userId)
	local cfg = BlorbData.Config
	nextVisitAt[userId] = os.time() + math.random(cfg.CustomerIntervalMin, cfg.CustomerIntervalMax)
end

function CustomerSimService.OnPlayerAdded(player)
	scheduleNext(player.UserId)
end

function CustomerSimService.OnPlayerRemoving(player)
	nextVisitAt[player.UserId] = nil
end

-- Called on a repeating loop from Main.server.lua.
function CustomerSimService.Tick()
	local now = os.time()

	for _, player in ipairs(Players:GetPlayers()) do
		if nextVisitAt[player.UserId] and now >= nextVisitAt[player.UserId] then
			scheduleNext(player.UserId)

			local data = PlayerDataManager.Get(player)
			if data then
				-- Pick a random idle (occupied, not currently rented) slot for the NPC to visit.
				local idleSlots = {}
				for i = 1, BlorbData.Config.MaxStandSlots do
					local slot = data.standSlots[i]
					if slot and not (slot.rentedByUserId and slot.rentExpiresAt and slot.rentExpiresAt > now) then
						table.insert(idleSlots, i)
					end
				end

				if #idleSlots > 0 then
					local slotIndex = idleSlots[math.random(1, #idleSlots)]
					local slot = data.standSlots[slotIndex]
					local blorb = data.blorbs[slot.blorbId]

					if blorb and blorb.hunger > BlorbData.Config.StarvedHungerThreshold then
						local tier = BlorbData.RarityTiers[blorb.rarityId]
						local snackMultiplier = RentalService.GetActiveBuffMagnitude(data, "SnackMultiplier")
						local payout = math.floor(tier.rentPrice * BlorbData.Config.CustomerPayoutMultiplier * snackMultiplier)

						data.currency += payout
						data.stats.totalEarned += payout
						data.stats.totalRented += 1

						-- Ties the stand up briefly, same as a real rental, just shorter and NPC-only.
						slot.rentedByUserId = -1 -- NPC sentinel, never matches a real UserId
						slot.rentExpiresAt = now + 20
					end
				end
			end
		end
	end
end

return CustomerSimService
