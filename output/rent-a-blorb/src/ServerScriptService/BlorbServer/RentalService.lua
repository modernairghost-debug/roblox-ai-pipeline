-- Rent-a-Blorb -- placing Blorbs on your own rental stand + other players renting them.
-- NOTE: renting only works while the owner is online in the same server -- see
-- BUILD_NOTES.md for the offline/cross-server limitation and how this could be extended.

local Players = game:GetService("Players")
local BlorbData = require(game:GetService("ReplicatedStorage"):WaitForChild("BlorbShared"):WaitForChild("BlorbData"))
local PlayerDataManager = require(script.Parent:WaitForChild("PlayerDataManager"))

local RentalService = {}

-- data.standSlots[slotIndex] = nil (empty) | { blorbId, rentedByUserId, rentExpiresAt }

function RentalService.PlaceOnStand(player, blorbId, slotIndex)
	local data = PlayerDataManager.Get(player)
	if not data then return false, "Data not loaded" end
	if slotIndex < 1 or slotIndex > BlorbData.Config.MaxStandSlots then
		return false, "Invalid stand slot"
	end

	local blorb = data.blorbs[blorbId]
	if not blorb then return false, "You don't own that Blorb" end
	if blorb.hunger <= BlorbData.Config.StarvedHungerThreshold then
		return false, "That Blorb is starving -- feed it first"
	end
	if blorb.standSlot then
		return false, "Already placed on a stand slot"
	end
	if data.standSlots[slotIndex] then
		return false, "That slot is occupied"
	end

	data.standSlots[slotIndex] = { blorbId = blorbId, rentedByUserId = nil, rentExpiresAt = nil }
	blorb.standSlot = slotIndex
	return true
end

local function clearSlot(data, slotIndex)
	local slot = data.standSlots[slotIndex]
	if slot then
		local blorb = data.blorbs[slot.blorbId]
		if blorb then
			blorb.standSlot = nil
		end
	end
	data.standSlots[slotIndex] = nil
end

function RentalService.RemoveFromStand(player, slotIndex)
	local data = PlayerDataManager.Get(player)
	if not data then return false, "Data not loaded" end

	local slot = data.standSlots[slotIndex]
	if not slot then
		return false, "That slot is empty"
	end
	if slot.rentedByUserId and slot.rentExpiresAt and slot.rentExpiresAt > os.time() then
		return false, "Currently rented out -- wait for the rental to end"
	end

	clearSlot(data, slotIndex)
	return true
end

-- Used by FeedingService when a placed Blorb starves.
function RentalService.ForceRemoveFromStand(player, slotIndex)
	local data = PlayerDataManager.Get(player)
	if not data then return end
	clearSlot(data, slotIndex)
end

local function applyBuffToRenter(renterPlayer, renterData, blorb, magnitude)
	table.insert(renterData.activeBuffs, {
		buffTypeId = blorb.buffTypeId,
		magnitude = magnitude,
		expiresAt = os.time() + BlorbData.Config.RentDurationSeconds,
	})

	local buffInfo = BlorbData.BuffTypes[blorb.buffTypeId]
	local character = renterPlayer.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if humanoid then
		if buffInfo.statAffected == "WalkSpeed" then
			humanoid.WalkSpeed *= magnitude
		elseif buffInfo.statAffected == "JumpPower" then
			humanoid.UseJumpPower = true
			humanoid.JumpPower *= magnitude
		end
	end
	-- LuckBoost / SnackMultiplier aren't character stats -- HatchingService and
	-- CustomerSimService read them straight off activeBuffs via GetActiveBuffMagnitude.
end

function RentalService.RentBlorb(renterPlayer, ownerUserId, slotIndex)
	if renterPlayer.UserId == ownerUserId then
		return false, "You can't rent your own Blorb"
	end

	local ownerPlayer = Players:GetPlayerByUserId(ownerUserId)
	if not ownerPlayer then
		return false, "That player isn't in this server right now"
	end

	local ownerData = PlayerDataManager.Get(ownerPlayer)
	local renterData = PlayerDataManager.Get(renterPlayer)
	if not ownerData or not renterData then
		return false, "Data not loaded"
	end

	local slot = ownerData.standSlots[slotIndex]
	if not slot then
		return false, "That stand slot is empty"
	end
	if slot.rentedByUserId and slot.rentExpiresAt and slot.rentExpiresAt > os.time() then
		return false, "Already rented out"
	end

	local blorb = ownerData.blorbs[slot.blorbId]
	if not blorb then
		return false, "That Blorb no longer exists"
	end
	if blorb.hunger <= BlorbData.Config.StarvedHungerThreshold then
		return false, "That Blorb is starving and can't be rented"
	end

	local tier = BlorbData.RarityTiers[blorb.rarityId]
	local price = tier.rentPrice
	if renterData.currency < price then
		return false, "Not enough Snacks"
	end

	renterData.currency -= price
	ownerData.currency += price
	ownerData.stats.totalEarned += price
	ownerData.stats.totalRented += 1

	slot.rentedByUserId = renterPlayer.UserId
	slot.rentExpiresAt = os.time() + BlorbData.Config.RentDurationSeconds

	local magnitude = tier.buffMagnitude
	if blorb.hunger <= BlorbData.Config.GrumpyHungerThreshold then
		magnitude *= 0.5 -- a hungry, grumpy Blorb gives a worse buff -- feed your Blorbs
	end

	applyBuffToRenter(renterPlayer, renterData, blorb, magnitude)

	return true, { price = price, buffTypeId = blorb.buffTypeId, magnitude = magnitude }
end

-- Repeating loop from Main.server.lua: clears expired rentals and reverts expired buffs.
function RentalService.ExpireTick()
	local now = os.time()

	for _, player in ipairs(Players:GetPlayers()) do
		local data = PlayerDataManager.Get(player)
		if data then
			for i = 1, BlorbData.Config.MaxStandSlots do
				local slot = data.standSlots[i]
				if slot and slot.rentExpiresAt and slot.rentExpiresAt <= now then
					slot.rentedByUserId = nil
					slot.rentExpiresAt = nil
				end
			end

			local kept = {}
			for _, buff in ipairs(data.activeBuffs) do
				if buff.expiresAt > now then
					table.insert(kept, buff)
				elseif buff.buffTypeId == "SpeedBoost" or buff.buffTypeId == "JumpBoost" then
					local character = player.Character
					local humanoid = character and character:FindFirstChildOfClass("Humanoid")
					if humanoid then
						if buff.buffTypeId == "SpeedBoost" then
							humanoid.WalkSpeed /= buff.magnitude
						else
							humanoid.JumpPower /= buff.magnitude
						end
					end
				end
			end
			data.activeBuffs = kept
		end
	end
end

-- Read helper for HatchingService / CustomerSimService.
function RentalService.GetActiveBuffMagnitude(data, buffTypeId)
	local now = os.time()
	for _, buff in ipairs(data.activeBuffs) do
		if buff.buffTypeId == buffTypeId and buff.expiresAt > now then
			return buff.magnitude
		end
	end
	return 1.0
end

return RentalService
