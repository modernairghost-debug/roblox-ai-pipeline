"""
content_gen/luau_generator.py

Takes an APPROVED idea (from review/approved/) and generates the Luau scripts + level
config for it.

Two generation paths:
1. Rent-a-Blorb (title-gated) uses the original hand-authored implementation -- kept as a
   known-good reference and regression check, since it's the one concept that's actually
   been playtested end to end.
2. Every other idea goes through _generate_via_llm(), which calls the Anthropic API with a
   system prompt encoding the "house style" learned from debugging Rent-a-Blorb's first
   build (see LLM_SYSTEM_PROMPT below) -- most importantly: never call
   DataStoreService:GetDataStore()/GetOrderedDataStore() unprotected at module load time,
   since that throws on an unpublished place and silently kills the whole require chain.
   Output is validated by lint_scripts() (Luau syntax + the DataStore-guard heuristic)
   before it's trusted; generate_luau_for_idea() retries once with the lint report fed
   back to the model if the first attempt fails lint.
"""

import json
import os
import re

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "level_templates")

try:
    import anthropic
except ImportError:
    anthropic = None


def load_template(genre_pattern: str) -> str:
    """
    genre_pattern should match one of: brainrot_meme, simulator, roleplay_social, horror_survival
    (see research/known_trends_seed.json -> genre_patterns keys)

    Kept as scaffold reference for the genre conventions (single clear verb, no-tutorial
    onboarding, leaderboard/social-proof hook) even though the real generator below
    doesn't do placeholder substitution on it anymore.
    """
    filename_map = {
        "brainrot_meme": "brainrot_meme.lua.template",
        "simulator": "simulator.lua.template",
        "roleplay_social": "roleplay_social.lua.template",
        "horror_survival": "horror_survival.lua.template",
    }
    filename = filename_map.get(genre_pattern)
    if not filename:
        raise ValueError(f"No template for genre_pattern={genre_pattern!r}")

    path = os.path.join(TEMPLATES_DIR, filename)
    with open(path, "r") as f:
        return f.read()


def generate_luau_for_idea(idea: dict) -> dict:
    """
    idea: one object from an approved ideas file (see ideation/idea_generator.py schema)

    Returns: {"scripts": {relative_path_under_src: lua_code}, "level_config": {...}}
    """
    title = idea.get("title", "")
    genre_pattern = idea.get("genre_pattern", "")

    if title == "Rent-a-Blorb" and genre_pattern == "brainrot_meme":
        return _generate_rent_a_blorb(idea)

    return generate_luau_via_llm(idea)


_BLORB_DATA_LUA = """-- Rent-a-Blorb -- shared game data (rarity tiers, species, buffs, egg types, tunable
-- constants). Read by both server (authoritative rolls/economy) and client (UI display
-- only -- the client never trusts its own copy for anything that moves currency).

local BlorbData = {}

BlorbData.Config = {
	StarterCurrency = 100,
	MaxStandSlots = 3,

	HungerMax = 100,
	HungerDecayPerMinute = 4,
	FeedCost = 5,
	FeedRestoreAmount = 40,
	GrumpyHungerThreshold = 20, -- below this, rental buffs are halved
	StarvedHungerThreshold = 0, -- at this point the Blorb can't be rented at all

	BasicEggPrice = 20,
	RareEggPrice = 100,

	BreedCost = 50,
	BreedTierUpChance = 0.12, -- chance the offspring rolls one rarity tier above the better parent

	RentDurationSeconds = 180,
	CustomerIntervalMin = 45,
	CustomerIntervalMax = 120,
	CustomerPayoutMultiplier = 0.4, -- NPC customers pay less than a real player would -- P2P renting is the better economy

	AutosaveIntervalSeconds = 120,
}

-- Rarity order matters for breeding tier-up logic (index+1 = next tier up)
BlorbData.RarityOrder = { "Common", "Uncommon", "Rare", "Epic", "Mythic" }

BlorbData.RarityTiers = {
	Common =   { hatchWeight = 55, rentPrice = 5,   buffMagnitude = 1.00, scoreValue = 1 },
	Uncommon = { hatchWeight = 25, rentPrice = 12,  buffMagnitude = 1.15, scoreValue = 3 },
	Rare =     { hatchWeight = 13, rentPrice = 30,  buffMagnitude = 1.35, scoreValue = 8 },
	Epic =     { hatchWeight = 5,  rentPrice = 75,  buffMagnitude = 1.60, scoreValue = 20 },
	Mythic =   { hatchWeight = 2,  rentPrice = 200, buffMagnitude = 2.00, scoreValue = 50 },
}

-- Rare Egg reweights the odds toward the top of the table -- still can't guarantee Mythic.
BlorbData.RareEggHatchWeights = {
	Common = 25, Uncommon = 30, Rare = 25, Epic = 15, Mythic = 5,
}

-- Original meme-mashup species names -- deliberately not referencing any existing IP.
BlorbData.Species = {
	"Turbo Sock Goblin",
	"Crusty Waffle Pigeon",
	"Glitch Noodle Toaster",
	"Sus Rizz Raccoon",
	"Feral Cardboard Wizard",
	"Static Pickle Dragon",
	"Doomscroll Duckling",
	"Buffering Hamster Knight",
}

BlorbData.BuffTypes = {
	SpeedBoost = { label = "Turbo Legs", statAffected = "WalkSpeed" },
	JumpBoost = { label = "Rizz Hops", statAffected = "JumpPower" },
	LuckBoost = { label = "Sus Luck", statAffected = "HatchLuck" },
	SnackMultiplier = { label = "Snack Rizz", statAffected = "SnackIncome" },
}

BlorbData.BuffTypeIds = { "SpeedBoost", "JumpBoost", "LuckBoost", "SnackMultiplier" }

return BlorbData
"""


_UTIL_LUA = """-- Rent-a-Blorb -- small server-side helpers shared across services.

local Util = {}

-- Weighted random pick from a {key = weight} table. Returns the chosen key.
function Util.WeightedPick(weights)
	local total = 0
	for _, weight in pairs(weights) do
		total += weight
	end

	local roll = math.random() * total
	local cumulative = 0
	for key, weight in pairs(weights) do
		cumulative += weight
		if roll <= cumulative then
			return key
		end
	end

	-- Floating point fallback -- return the last key iterated.
	local lastKey
	for key in pairs(weights) do
		lastKey = key
	end
	return lastKey
end

function Util.PickFrom(list)
	return list[math.random(1, #list)]
end

return Util
"""


_PLAYER_DATA_MANAGER_LUA = """-- Rent-a-Blorb -- player data persistence.
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
"""


_LEADERBOARD_SERVICE_LUA = """-- Rent-a-Blorb -- global "rarest Blorb ever owned" leaderboard via OrderedDataStore.
-- Studio still needs a physical board part (see BUILD_NOTES.md) -- this only maintains
-- the data and, if a part is found, keeps its text in sync.

local DataStoreService = game:GetService("DataStoreService")
local Workspace = game:GetService("Workspace")

local LeaderboardService = {}

local ORDERED_STORE_NAME = "RentABlorb_RarestScore_v1"

-- Same guard as PlayerDataManager -- GetOrderedDataStore() itself throws on an unpublished
-- place, and unprotected that used to kill this whole module's require() (and, via the
-- require chain in Main.server.lua, every system after it, including TestWorldBuilder).
local orderedStoreOk, orderedStore = pcall(function()
	return DataStoreService:GetOrderedDataStore(ORDERED_STORE_NAME)
end)
if not orderedStoreOk then
	warn("RentABlorb: Leaderboard DataStore unavailable this session (place not published yet) "
		.. "-- the rarest-Blorb leaderboard will be empty until you publish. Error: "
		.. tostring(orderedStore))
	orderedStore = nil
end

local sessionBest = {} -- [userId] = score, avoids a write on every single hatch/breed

function LeaderboardService.ReportScore(player, score)
	if not orderedStore then
		return
	end

	local best = sessionBest[player.UserId] or 0
	if score <= best then
		return
	end
	sessionBest[player.UserId] = score

	task.spawn(function()
		local ok, err = pcall(function()
			orderedStore:SetAsync("user_" .. player.UserId, score)
		end)
		if not ok then
			warn(("RentABlorb: leaderboard write failed for %s: %s"):format(player.Name, tostring(err)))
		end
	end)
end

function LeaderboardService.GetTop(n)
	if not orderedStore then
		return {}
	end

	local ok, pages = pcall(function()
		return orderedStore:GetSortedAsync(false, n)
	end)
	if not ok then
		return {}
	end

	local top = {}
	local page = pages:GetCurrentPage()
	for _, entry in ipairs(page) do
		table.insert(top, { userIdKey = entry.key, score = entry.value })
	end
	return top
end

-- Repeating loop from Main.server.lua. Looks for a part named "Leaderboard_Board" with a
-- SurfaceGui > TextLabel named "Display" and keeps it in sync -- no-ops if not built yet.
function LeaderboardService.RefreshBoard()
	local board = Workspace:FindFirstChild("Leaderboard_Board")
	if not board then
		return
	end
	local surfaceGui = board:FindFirstChildOfClass("SurfaceGui")
	local label = surfaceGui and surfaceGui:FindFirstChild("Display")
	if not (label and label:IsA("TextLabel")) then
		return
	end

	local top = LeaderboardService.GetTop(5)
	local lines = { "Rarest Blorbs" }
	for i, entry in ipairs(top) do
		table.insert(lines, ("%d. %s -- %d"):format(i, entry.userIdKey, entry.score))
	end
	label.Text = table.concat(lines, "\\n")
end

return LeaderboardService
"""


_RENTAL_SERVICE_LUA = """-- Rent-a-Blorb -- placing Blorbs on your own rental stand + other players renting them.
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
"""


_HATCHING_SERVICE_LUA = """-- Rent-a-Blorb -- hatching. Buying an egg immediately hatches it (no separate egg
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
"""


_FEEDING_SERVICE_LUA = """-- Rent-a-Blorb -- hunger decay + feeding. A starved Blorb can't be rented, which is the
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
"""


_BREEDING_SERVICE_LUA = """-- Rent-a-Blorb -- breeding: combine two owned Blorbs into a new one. Consumes both
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
"""


_CUSTOMER_SIM_SERVICE_LUA = """-- Rent-a-Blorb -- simulated NPC customers. Solves the cold-start problem (an idle stand
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
"""


_BASE_ASSIGNMENT_SERVICE_LUA = """-- Rent-a-Blorb -- assigns each player a pre-built base plot (with rental stand slots)
-- for the duration of their session. Requires Studio to build "PlayerBasePlot"-tagged
-- models ahead of time -- see BUILD_NOTES.md for the exact part/tag contract.

local CollectionService = game:GetService("CollectionService")

local BaseAssignmentService = {}

local UNCLAIMED_OWNER_ID = 0
local claimedPlotByUserId = {} -- [userId] = plotInstance

local function getRentalStands(plot)
	local stands = {}
	for _, descendant in ipairs(plot:GetDescendants()) do
		if CollectionService:HasTag(descendant, "RentalStand") then
			table.insert(stands, descendant)
		end
	end
	return stands
end

function BaseAssignmentService.AssignBase(player)
	local plot = claimedPlotByUserId[player.UserId]

	if not plot then
		for _, candidate in ipairs(CollectionService:GetTagged("PlayerBasePlot")) do
			local owner = candidate:GetAttribute("OwnerUserId") or UNCLAIMED_OWNER_ID
			if owner == UNCLAIMED_OWNER_ID then
				plot = candidate
				break
			end
		end

		if not plot then
			warn(("RentABlorb: no free base plot for %s -- Studio needs to build more PlayerBasePlot models"):format(player.Name))
			return nil
		end

		plot:SetAttribute("OwnerUserId", player.UserId)
		for _, stand in ipairs(getRentalStands(plot)) do
			stand:SetAttribute("OwnerUserId", player.UserId)
		end
		claimedPlotByUserId[player.UserId] = plot
	end

	local spawn = plot:FindFirstChild("BaseSpawn", true)
	if spawn and player.Character then
		local hrp = player.Character:FindFirstChild("HumanoidRootPart")
		if hrp then
			hrp.CFrame = spawn.CFrame + Vector3.new(0, 3, 0)
		end
	end

	return plot
end

function BaseAssignmentService.ReleaseBase(player)
	local plot = claimedPlotByUserId[player.UserId]
	if not plot then
		return
	end

	plot:SetAttribute("OwnerUserId", UNCLAIMED_OWNER_ID)
	for _, stand in ipairs(getRentalStands(plot)) do
		stand:SetAttribute("OwnerUserId", UNCLAIMED_OWNER_ID)
	end
	claimedPlotByUserId[player.UserId] = nil
end

return BaseAssignmentService
"""


_TEST_WORLD_BUILDER_LUA = """-- Rent-a-Blorb -- minimal test world, built procedurally at server start so the place
-- is playtestable immediately after opening the built .rbxlx -- no hand-placing parts
-- in Studio required first. This is scaffolding for local playtesting only; once you've
-- built real level art in Studio, flip BUILD_TEST_WORLD to false in Main.server.lua (or
-- just delete this module and its call site) so the placeholder geometry stops spawning.
--
-- Builds exactly what the other services expect (see BUILD_NOTES.md "World-building"
-- section): one EggStall, one PlayerBasePlot with 3 RentalStand slots + a BaseSpawn, a
-- baseplate to stand on, and a default SpawnLocation.

local CollectionService = game:GetService("CollectionService")
local Workspace = game:GetService("Workspace")

local TestWorldBuilder = {}

local function part(name, size, position, color, parent)
	local p = Instance.new("Part")
	p.Name = name
	p.Size = size
	p.Position = position
	p.Anchored = true
	p.BrickColor = color
	p.Parent = parent
	return p
end

local function proximityPrompt(actionText, objectText, parent)
	local prompt = Instance.new("ProximityPrompt")
	prompt.ActionText = actionText
	prompt.ObjectText = objectText
	prompt.MaxActivationDistance = 10
	prompt.HoldDuration = 0.5
	prompt.Parent = parent
	return prompt
end

function TestWorldBuilder.Build()
	if Workspace:FindFirstChild("TestWorld") then
		return -- already built (e.g. a live-sync reload) -- don't duplicate it
	end

	local testWorld = Instance.new("Folder")
	testWorld.Name = "TestWorld"
	testWorld.Parent = Workspace

	-- // Ground + spawn ---------------------------------------------------------------

	local baseplate = part(
		"Baseplate", Vector3.new(120, 1, 120), Vector3.new(0, 0, 0),
		BrickColor.new("Medium stone grey"), testWorld
	)
	baseplate.CanCollide = true

	local spawn = Instance.new("SpawnLocation")
	spawn.Name = "DefaultSpawn"
	spawn.Size = Vector3.new(6, 1, 6)
	spawn.Position = Vector3.new(0, 1, -10)
	spawn.Anchored = true
	spawn.CanCollide = true
	spawn.Neutral = true
	spawn.BrickColor = BrickColor.new("Bright blue")
	spawn.Parent = testWorld

	-- // Egg stall ----------------------------------------------------------------------

	local eggStall = part(
		"EggStall_Basic", Vector3.new(4, 4, 4), Vector3.new(10, 2.5, 0),
		BrickColor.new("New Yeller"), testWorld
	)
	eggStall:SetAttribute("EggType", "BasicEgg")
	CollectionService:AddTag(eggStall, "EggStall")
	proximityPrompt("Buy Basic Egg", "Egg Stall", eggStall)

	-- // One player base plot, with 3 rental stands --------------------------------------

	local plot = Instance.new("Model")
	plot.Name = "PlayerBasePlot_1"
	plot.Parent = testWorld
	CollectionService:AddTag(plot, "PlayerBasePlot")

	local baseSpawn = part(
		"BaseSpawn", Vector3.new(2, 1, 2), Vector3.new(-15, 1, 0),
		BrickColor.new("Institutional white"), plot
	)
	baseSpawn.CanCollide = false
	baseSpawn.Transparency = 0.7

	for i = 1, 3 do
		local stand = part(
			"RentalStand_" .. i,
			Vector3.new(3, 3, 3),
			Vector3.new(-20 - (i * 3), 2, 6),
			BrickColor.new("Cyan"),
			plot
		)
		stand:SetAttribute("SlotIndex", i)
		CollectionService:AddTag(stand, "RentalStand")
		proximityPrompt("Manage Stand " .. i, "Rental Stand " .. i, stand)
	end

	plot.PrimaryPart = baseSpawn
end

return TestWorldBuilder
"""


_MAIN_SERVER_LUA = """-- Rent-a-Blorb -- server entry point. Wires Remotes, player lifecycle, and the
-- background loops (hunger decay, rental expiry, NPC customers, leaderboard, autosave).

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- // Module setup ---------------------------------------------------------------------
-- Wrapped in pcall + WaitForChild timeouts on purpose: a require() error or a missing
-- Instance here used to fail SILENTLY (an unprotected error/infinite yield at the top of
-- a Script just halts the whole script -- nothing after it, including
-- TestWorldBuilder.Build(), ever runs, and Studio's Output panel can be easy to miss).
-- Now any failure here prints loudly and the script bails out cleanly instead of hanging.

local BlorbData, PlayerDataManager, HatchingService, FeedingService, BreedingService,
	RentalService, CustomerSimService, LeaderboardService, BaseAssignmentService, TestWorldBuilder

local setupOk, setupErr = pcall(function()
	BlorbData = require(ReplicatedStorage:WaitForChild("BlorbShared", 10):WaitForChild("BlorbData", 10))
	PlayerDataManager = require(script.Parent:WaitForChild("PlayerDataManager", 10))
	HatchingService = require(script.Parent:WaitForChild("HatchingService", 10))
	FeedingService = require(script.Parent:WaitForChild("FeedingService", 10))
	BreedingService = require(script.Parent:WaitForChild("BreedingService", 10))
	RentalService = require(script.Parent:WaitForChild("RentalService", 10))
	CustomerSimService = require(script.Parent:WaitForChild("CustomerSimService", 10))
	LeaderboardService = require(script.Parent:WaitForChild("LeaderboardService", 10))
	BaseAssignmentService = require(script.Parent:WaitForChild("BaseAssignmentService", 10))
	TestWorldBuilder = require(script.Parent:WaitForChild("TestWorldBuilder", 10))
end)

if not setupOk then
	warn("=====================================================")
	warn("RentABlorb: Main.server.lua FAILED during module setup (require chain):")
	warn(tostring(setupErr))
	warn("This means NONE of the server systems ran this session, including")
	warn("TestWorldBuilder -- that's why Workspace looks empty. Fix the module/")
	warn("path named above and rerun.")
	warn("=====================================================")
	return
end

-- Flip this to false once you've built real level art in Studio to replace the
-- placeholder test world (see TestWorldBuilder.lua / BUILD_NOTES.md).
local BUILD_TEST_WORLD = true

if BUILD_TEST_WORLD then
	local buildOk, buildErr = pcall(function()
		TestWorldBuilder.Build()
	end)

	if not buildOk then
		warn("=====================================================")
		warn("RentABlorb: TestWorldBuilder.Build() FAILED:")
		warn(tostring(buildErr))
		warn("Workspace will stay empty (just Camera/Terrain) until this is fixed.")
		warn("=====================================================")
	else
		print("RentABlorb: TestWorldBuilder.Build() completed OK -- check Workspace.TestWorld.")
	end
end

-- // Remotes setup ------------------------------------------------------------------

local remotesFolder = Instance.new("Folder")
remotesFolder.Name = "Remotes"
remotesFolder.Parent = ReplicatedStorage

local function newRemoteEvent(name)
	local remote = Instance.new("RemoteEvent")
	remote.Name = name
	remote.Parent = remotesFolder
	return remote
end

local BuyAndHatchEggRemote = newRemoteEvent("BuyAndHatchEgg")
local FeedBlorbRemote = newRemoteEvent("FeedBlorb")
local BreedBlorbsRemote = newRemoteEvent("BreedBlorbs")
local PlaceOnStandRemote = newRemoteEvent("PlaceOnStand")
local RemoveFromStandRemote = newRemoteEvent("RemoveFromStand")
local RentBlorbRemote = newRemoteEvent("RentBlorb")

local DataUpdatedRemote = newRemoteEvent("DataUpdated") -- server -> client, full data snapshot
local NotifyRemote = newRemoteEvent("Notify") -- server -> client, short feedback message

-- // Helpers -------------------------------------------------------------------------

local function pushData(player)
	local data = PlayerDataManager.Get(player)
	if data then
		DataUpdatedRemote:FireClient(player, data)
	end
end

local function notify(player, message, isError)
	NotifyRemote:FireClient(player, message, isError == true)
end

local function handle(remote, fn)
	remote.OnServerEvent:Connect(function(player, ...)
		local ok, success, resultOrError = pcall(fn, player, ...)
		if not ok then
			warn(("RentABlorb: handler error for %s: %s"):format(remote.Name, tostring(success)))
			notify(player, "Something went wrong -- try again.", true)
			return
		end

		if success then
			pushData(player)
		else
			notify(player, tostring(resultOrError), true)
		end
	end)
end

-- // Remote wiring --------------------------------------------------------------------

handle(BuyAndHatchEggRemote, function(player, eggTypeId)
	return HatchingService.BuyAndHatch(player, eggTypeId)
end)

handle(FeedBlorbRemote, function(player, blorbId)
	return FeedingService.Feed(player, blorbId)
end)

handle(BreedBlorbsRemote, function(player, blorbIdA, blorbIdB)
	return BreedingService.Breed(player, blorbIdA, blorbIdB)
end)

handle(PlaceOnStandRemote, function(player, blorbId, slotIndex)
	return RentalService.PlaceOnStand(player, blorbId, slotIndex)
end)

handle(RemoveFromStandRemote, function(player, slotIndex)
	return RentalService.RemoveFromStand(player, slotIndex)
end)

RentBlorbRemote.OnServerEvent:Connect(function(renterPlayer, ownerUserId, slotIndex)
	local ok, success, resultOrError = pcall(RentalService.RentBlorb, renterPlayer, ownerUserId, slotIndex)
	if not ok then
		warn("RentABlorb: RentBlorb handler error: " .. tostring(success))
		notify(renterPlayer, "Something went wrong -- try again.", true)
		return
	end

	if success then
		pushData(renterPlayer)
		local ownerPlayer = Players:GetPlayerByUserId(ownerUserId)
		if ownerPlayer then
			pushData(ownerPlayer)
			notify(ownerPlayer, ("%s rented one of your Blorbs for %d Snacks!"):format(renterPlayer.Name, resultOrError.price), false)
		end
		notify(renterPlayer, "Rented! Buff active.", false)
	else
		notify(renterPlayer, tostring(resultOrError), true)
	end
end)

-- // Player lifecycle -----------------------------------------------------------------

Players.PlayerAdded:Connect(function(player)
	PlayerDataManager.Load(player)
	CustomerSimService.OnPlayerAdded(player)
	BaseAssignmentService.AssignBase(player)

	player.CharacterAdded:Connect(function()
		BaseAssignmentService.AssignBase(player)
	end)

	pushData(player)
end)

Players.PlayerRemoving:Connect(function(player)
	CustomerSimService.OnPlayerRemoving(player)
	BaseAssignmentService.ReleaseBase(player)
	PlayerDataManager.Release(player)
end)

game:BindToClose(function()
	PlayerDataManager.SaveAll()
end)

-- // Background loops -----------------------------------------------------------------

task.spawn(function()
	while true do
		task.wait(60)
		for _, player in ipairs(Players:GetPlayers()) do
			FeedingService.DecayTick(player, 1)
		end
	end
end)

task.spawn(function()
	while true do
		task.wait(5)
		RentalService.ExpireTick()
	end
end)

task.spawn(function()
	while true do
		task.wait(10)
		CustomerSimService.Tick()
		for _, player in ipairs(Players:GetPlayers()) do
			pushData(player) -- keeps client currency/hunger/stand UI reasonably fresh
		end
	end
end)

task.spawn(function()
	while true do
		task.wait(30)
		LeaderboardService.RefreshBoard()
	end
end)

task.spawn(function()
	while true do
		task.wait(BlorbData.Config.AutosaveIntervalSeconds)
		PlayerDataManager.SaveAll()
	end
end)
"""


_MAIN_CLIENT_LUA = """-- Rent-a-Blorb -- client. Builds a minimal functional HUD (not a polished UI -- see
-- BUILD_NOTES.md) and wires ProximityPrompts on world parts tagged by CollectionService.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local LocalPlayer = Players.LocalPlayer

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local BuyAndHatchEggRemote = Remotes:WaitForChild("BuyAndHatchEgg")
local FeedBlorbRemote = Remotes:WaitForChild("FeedBlorb")
local BreedBlorbsRemote = Remotes:WaitForChild("BreedBlorbs")
local PlaceOnStandRemote = Remotes:WaitForChild("PlaceOnStand")
local RemoveFromStandRemote = Remotes:WaitForChild("RemoveFromStand")
local RentBlorbRemote = Remotes:WaitForChild("RentBlorb")
local DataUpdatedRemote = Remotes:WaitForChild("DataUpdated")
local NotifyRemote = Remotes:WaitForChild("Notify")

local BlorbData = require(ReplicatedStorage:WaitForChild("BlorbShared"):WaitForChild("BlorbData"))

local latestData = nil
local selectedForBreeding = {} -- up to 2 blorbIds
local selectedForPlacement = nil -- one blorbId, consumed on next stand interaction

-- // HUD ------------------------------------------------------------------------------

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "BlorbHUD"
screenGui.ResetOnSpawn = false
screenGui.Parent = LocalPlayer:WaitForChild("PlayerGui")

local currencyLabel = Instance.new("TextLabel")
currencyLabel.Name = "Currency"
currencyLabel.Size = UDim2.new(0, 220, 0, 32)
currencyLabel.Position = UDim2.new(0, 12, 0, 12)
currencyLabel.BackgroundColor3 = Color3.fromRGB(20, 20, 28)
currencyLabel.TextColor3 = Color3.fromRGB(255, 230, 120)
currencyLabel.Font = Enum.Font.GothamBold
currencyLabel.TextSize = 18
currencyLabel.Text = "Snacks: --"
currencyLabel.Parent = screenGui

local notifyLabel = Instance.new("TextLabel")
notifyLabel.Name = "Notify"
notifyLabel.Size = UDim2.new(0, 320, 0, 28)
notifyLabel.Position = UDim2.new(0, 12, 0, 48)
notifyLabel.BackgroundTransparency = 1
notifyLabel.Font = Enum.Font.Gotham
notifyLabel.TextSize = 14
notifyLabel.TextXAlignment = Enum.TextXAlignment.Left
notifyLabel.Text = ""
notifyLabel.Parent = screenGui

local listFrame = Instance.new("ScrollingFrame")
listFrame.Name = "BlorbList"
listFrame.Size = UDim2.new(0, 320, 0, 300)
listFrame.Position = UDim2.new(0, 12, 0, 84)
listFrame.BackgroundColor3 = Color3.fromRGB(20, 20, 28)
listFrame.BackgroundTransparency = 0.2
listFrame.CanvasSize = UDim2.new(0, 0, 0, 0)
listFrame.AutomaticCanvasSize = Enum.AutomaticSize.Y
listFrame.ScrollBarThickness = 6
listFrame.Parent = screenGui

local listLayout = Instance.new("UIListLayout")
listLayout.SortOrder = Enum.SortOrder.LayoutOrder
listLayout.Padding = UDim.new(0, 4)
listLayout.Parent = listFrame

local buyBasicButton = Instance.new("TextButton")
buyBasicButton.Size = UDim2.new(0, 150, 0, 32)
buyBasicButton.Position = UDim2.new(0, 12, 0, 396)
buyBasicButton.Text = ("Buy Basic Egg (%d)"):format(BlorbData.Config.BasicEggPrice)
buyBasicButton.Font = Enum.Font.Gotham
buyBasicButton.TextSize = 13
buyBasicButton.Parent = screenGui

local buyRareButton = Instance.new("TextButton")
buyRareButton.Size = UDim2.new(0, 150, 0, 32)
buyRareButton.Position = UDim2.new(0, 172, 0, 396)
buyRareButton.Text = ("Buy Rare Egg (%d)"):format(BlorbData.Config.RareEggPrice)
buyRareButton.Font = Enum.Font.Gotham
buyRareButton.TextSize = 13
buyRareButton.Parent = screenGui

local breedButton = Instance.new("TextButton")
breedButton.Size = UDim2.new(0, 310, 0, 32)
breedButton.Position = UDim2.new(0, 12, 0, 434)
breedButton.Text = "Breed Selected (pick 2 below)"
breedButton.Font = Enum.Font.Gotham
breedButton.TextSize = 13
breedButton.Parent = screenGui

buyBasicButton.MouseButton1Click:Connect(function()
	BuyAndHatchEggRemote:FireServer("BasicEgg")
end)
buyRareButton.MouseButton1Click:Connect(function()
	BuyAndHatchEggRemote:FireServer("RareEgg")
end)
breedButton.MouseButton1Click:Connect(function()
	if #selectedForBreeding == 2 then
		BreedBlorbsRemote:FireServer(selectedForBreeding[1], selectedForBreeding[2])
		selectedForBreeding = {}
	end
end)

local function rebuildList()
	for _, child in ipairs(listFrame:GetChildren()) do
		if child:IsA("Frame") then
			child:Destroy()
		end
	end

	if not latestData then
		return
	end

	local order = 0
	for blorbId, blorb in pairs(latestData.blorbs) do
		order += 1

		local row = Instance.new("Frame")
		row.Name = blorbId
		row.Size = UDim2.new(1, -8, 0, 64)
		row.BackgroundColor3 = Color3.fromRGB(32, 32, 44)
		row.LayoutOrder = order
		row.Parent = listFrame

		local info = Instance.new("TextLabel")
		info.Size = UDim2.new(1, -8, 0, 36)
		info.Position = UDim2.new(0, 4, 0, 2)
		info.BackgroundTransparency = 1
		info.Font = Enum.Font.Gotham
		info.TextSize = 12
		info.TextXAlignment = Enum.TextXAlignment.Left
		info.TextColor3 = Color3.fromRGB(230, 230, 240)
		info.Text = ("%s [%s]\\nHunger %d/100 -- %s"):format(
			blorb.species, blorb.rarityId, blorb.hunger, BlorbData.BuffTypes[blorb.buffTypeId].label
		)
		info.Parent = row

		local feedBtn = Instance.new("TextButton")
		feedBtn.Size = UDim2.new(0, 60, 0, 22)
		feedBtn.Position = UDim2.new(0, 4, 0, 38)
		feedBtn.Text = "Feed"
		feedBtn.TextSize = 11
		feedBtn.Parent = row
		feedBtn.MouseButton1Click:Connect(function()
			FeedBlorbRemote:FireServer(blorbId)
		end)

		local placeBtn = Instance.new("TextButton")
		placeBtn.Size = UDim2.new(0, 90, 0, 22)
		placeBtn.Position = UDim2.new(0, 68, 0, 38)
		placeBtn.Text = blorb.standSlot and ("On stand #" .. blorb.standSlot) or "Select to place"
		placeBtn.TextSize = 11
		placeBtn.Parent = row
		placeBtn.MouseButton1Click:Connect(function()
			if blorb.standSlot then
				RemoveFromStandRemote:FireServer(blorb.standSlot)
			else
				selectedForPlacement = blorbId
				notifyLabel.Text = "Selected for placement -- walk up to an empty stand slot."
			end
		end)

		local breedBtn = Instance.new("TextButton")
		breedBtn.Size = UDim2.new(0, 90, 0, 22)
		breedBtn.Position = UDim2.new(0, 162, 0, 38)
		local isSelected = table.find(selectedForBreeding, blorbId) ~= nil
		breedBtn.Text = isSelected and "Selected" or "Pick to breed"
		breedBtn.TextSize = 11
		breedBtn.Parent = row
		breedBtn.MouseButton1Click:Connect(function()
			if isSelected then
				local idx = table.find(selectedForBreeding, blorbId)
				table.remove(selectedForBreeding, idx)
			elseif #selectedForBreeding < 2 then
				table.insert(selectedForBreeding, blorbId)
			end
			rebuildList()
		end)
	end
end

DataUpdatedRemote.OnClientEvent:Connect(function(data)
	latestData = data
	currencyLabel.Text = ("Snacks: %d"):format(data.currency)
	rebuildList()
end)

NotifyRemote.OnClientEvent:Connect(function(message, isError)
	notifyLabel.TextColor3 = isError and Color3.fromRGB(255, 120, 120) or Color3.fromRGB(150, 255, 150)
	notifyLabel.Text = message
	task.delay(4, function()
		if notifyLabel.Text == message then
			notifyLabel.Text = ""
		end
	end)
end)

-- // World interactions (egg stalls + rental stands) --------------------------------

local function onEggStallPrompt(part)
	local eggType = part:GetAttribute("EggType") or "BasicEgg"
	BuyAndHatchEggRemote:FireServer(eggType)
end

local function onRentalStandPrompt(part)
	local ownerUserId = part:GetAttribute("OwnerUserId")
	local slotIndex = part:GetAttribute("SlotIndex")
	if not ownerUserId or not slotIndex then
		return
	end

	if ownerUserId == LocalPlayer.UserId then
		if selectedForPlacement then
			PlaceOnStandRemote:FireServer(selectedForPlacement, slotIndex)
			selectedForPlacement = nil
		else
			RemoveFromStandRemote:FireServer(slotIndex)
		end
	else
		RentBlorbRemote:FireServer(ownerUserId, slotIndex)
	end
end

local function wirePrompt(part, handler)
	local prompt = part:FindFirstChildOfClass("ProximityPrompt")
	if prompt then
		prompt.Triggered:Connect(function()
			handler(part)
		end)
	end
end

for _, part in ipairs(CollectionService:GetTagged("EggStall")) do
	wirePrompt(part, onEggStallPrompt)
end
CollectionService:GetInstanceAddedSignal("EggStall"):Connect(function(part)
	wirePrompt(part, onEggStallPrompt)
end)

for _, part in ipairs(CollectionService:GetTagged("RentalStand")) do
	wirePrompt(part, onRentalStandPrompt)
end
CollectionService:GetInstanceAddedSignal("RentalStand"):Connect(function(part)
	wirePrompt(part, onRentalStandPrompt)
end)
"""


def _generate_rent_a_blorb(idea: dict) -> dict:
    header = (
        f"-- {idea['title']} -- generated by content_gen/luau_generator.py\n"
        f"-- Core loop: {idea['core_loop']}\n"
        f"-- Hook: {idea['hook']}\n"
        f"-- Economy/social design: {idea['economy_or_social_design']}\n"
        f"-- {idea['ai_disclosure_note']}\n\n"
    )

    scripts = {
        "ReplicatedStorage/BlorbShared/BlorbData.lua": header + _BLORB_DATA_LUA,
        "ServerScriptService/BlorbServer/Util.lua": _UTIL_LUA,
        "ServerScriptService/BlorbServer/PlayerDataManager.lua": _PLAYER_DATA_MANAGER_LUA,
        "ServerScriptService/BlorbServer/LeaderboardService.lua": _LEADERBOARD_SERVICE_LUA,
        "ServerScriptService/BlorbServer/RentalService.lua": _RENTAL_SERVICE_LUA,
        "ServerScriptService/BlorbServer/HatchingService.lua": _HATCHING_SERVICE_LUA,
        "ServerScriptService/BlorbServer/FeedingService.lua": _FEEDING_SERVICE_LUA,
        "ServerScriptService/BlorbServer/BreedingService.lua": _BREEDING_SERVICE_LUA,
        "ServerScriptService/BlorbServer/CustomerSimService.lua": _CUSTOMER_SIM_SERVICE_LUA,
        "ServerScriptService/BlorbServer/BaseAssignmentService.lua": _BASE_ASSIGNMENT_SERVICE_LUA,
        "ServerScriptService/BlorbServer/TestWorldBuilder.lua": _TEST_WORLD_BUILDER_LUA,
        "ServerScriptService/BlorbServer/Main.server.lua": header + _MAIN_SERVER_LUA,
        "StarterPlayer/StarterPlayerScripts/BlorbClient/Main.client.lua": header + _MAIN_CLIENT_LUA,
    }

    level_config = {
        "title": idea["title"],
        "genre_pattern": idea["genre_pattern"],
        "hook": idea["hook"],
        "economy_or_social_design": idea["economy_or_social_design"],
        "ai_disclosure_note": idea["ai_disclosure_note"],
        "world_build_requirements": [
            "At least 2 parts tagged 'EggStall' (CollectionService), each with an "
            "EggType attribute ('BasicEgg' or 'RareEgg') and a child ProximityPrompt.",
            "At least 6-12 Models tagged 'PlayerBasePlot', each containing exactly 3 "
            "parts tagged 'RentalStand' (each with a child ProximityPrompt and a preset "
            "SlotIndex attribute of 1, 2, or 3) plus one part or SpawnLocation named "
            "'BaseSpawn'. More plots = more concurrent players supported.",
            "Optional: a part named 'Leaderboard_Board' in Workspace with a SurfaceGui "
            "containing a TextLabel named 'Display', for the rarest-Blorb leaderboard.",
        ],
    }

    return {"scripts": scripts, "level_config": level_config}


# ---------------------------------------------------------------------------------------
# Generic (LLM-driven) generation path -- for every idea other than Rent-a-Blorb.
# ---------------------------------------------------------------------------------------

LLM_SYSTEM_PROMPT = """You are a senior Roblox Luau engineer generating a complete, playable
first-draft game from a game design concept. Write real, working Luau code -- no
placeholders, no TODOs, no stub functions.

House style rules -- non-negotiable. Rule 1 in particular is a real bug that shipped and
had to be debugged; do not repeat it.

1. NEVER call DataStoreService:GetDataStore(...) or GetOrderedDataStore(...) unprotected at
   a ModuleScript's top level. An unpublished/local place throws on that call, and an
   unprotected error there kills the require() of that module -- which cascades and kills
   every other module that (transitively) requires it, so the entire server can silently
   do nothing. Always do this instead, and guard every later use on the store being non-nil:
       local storeOk, store = pcall(function() return DataStoreService:GetDataStore(NAME) end)
       if not storeOk then
           warn("<Game>: DataStore unavailable this session (place not published yet) -- ...")
           store = nil
       end
   Every function that reads/writes the store must check `if not store then return ... end`
   (or equivalent) before touching it.
2. Main.server.lua's entire require() chain must be wrapped in one pcall that warns loudly
   and returns cleanly on failure. Any world-building call (the TestWorldBuilder module's
   Build() function) must ALSO be wrapped in its own pcall, with a loud warn() on failure and
   a print() confirming success -- so a broken startup is unmistakable in Studio's Output
   panel instead of leaving an empty, silent Workspace.
3. Every player-data system needs: a Cache table keyed by UserId, Load/Get/Save/Release
   functions, and a defaultData() function. Save/Load must both no-op gracefully (never
   error) when the DataStore handle is nil per rule 1.
4. Build a TestWorldBuilder ModuleScript that procedurally builds a minimal but PLAYABLE
   physical world at server start (a baseplate, a SpawnLocation, and whatever physical
   objects the gameplay needs) using CollectionService tags + attributes -- never require a
   human to hand-place parts in Studio first. Guard it against double-building with a
   Workspace:FindFirstChild check so live-sync reloads don't duplicate it.
5. All RemoteEvents live in a "Remotes" Folder under ReplicatedStorage created by
   Main.server.lua. Every OnServerEvent handler is wrapped in pcall with a loud warn() on
   failure and a client-facing "Notify" remote for user-facing error messages -- never let a
   remote handler throw uncaught.
6. Modules form a DAG -- no circular requires. Shared constants/config live in one
   ReplicatedStorage data ModuleScript readable by both server and client.
7. Keep scope small enough to actually be playable in one sitting: one clear core loop, a
   minimal viable economy, no combat/PvP unless the concept explicitly calls for it.

Output format: respond with ONLY a single JSON object -- no markdown fences, no prose
before or after, no trailing commentary. Shape exactly:
{
  "scripts": {
    "<RojoRelativePath>": "<lua source code>",
    ...
  },
  "level_config": {
    "title": "...",
    "genre_pattern": "...",
    "hook": "...",
    "economy_or_social_design": "...",
    "ai_disclosure_note": "...",
    "world_build_requirements": ["...", "..."]
  }
}

Script path rules (Rojo convention -- this is how paths map to Roblox instance types and
services): each key's first path segment must be one of ReplicatedStorage, ServerScriptService,
or StarterPlayer/StarterPlayerScripts. A filename ending in ".server.lua" becomes a server
Script, ".client.lua" becomes a LocalScript, plain ".lua" becomes a ModuleScript. Include at
minimum: one shared data ModuleScript (ReplicatedStorage), one player-data-manager
ModuleScript, one or more gameplay-service ModuleScripts, one TestWorldBuilder ModuleScript,
one Main.server.lua entry point, and one Main.client.lua entry point that builds a minimal
functional HUD (labels + buttons wired to the remotes, no polish required for a first draft).
"""

LLM_USER_PROMPT_TEMPLATE = """Generate a complete Roblox game for this approved concept:

{idea_json}

Follow every house style rule in the system prompt exactly, especially rule 1 (DataStore
guard). Respond with only the JSON object described in the system prompt."""

_DATASTORE_CALL_RE = re.compile(r"DataStoreService\s*:\s*Get(?:Ordered)?DataStore\s*\(")
_BLOCK_OPENERS_RE = re.compile(
    r"\b(function|do|then|repeat)\b|\bfor\b[^\n]*?\bdo\b|\bwhile\b[^\n]*?\bdo\b"
)


def lint_scripts(scripts: dict) -> list:
    """
    Best-effort static QA pass, run after generation and before trusting the output enough
    to hand to `rojo build`. Not a real Luau parser (none was reliably installable in this
    sandbox -- no PyPI access beyond a small pre-cached mirror, no apt access to a lua
    interpreter package) so this is two heuristics, not a guarantee:

    1. Delimiter/keyword-balance sanity check -- catches truncated or structurally broken
       output (parens/brackets/braces unbalanced, or block-opener count wildly mismatched
       from `end`/`until` count). Loose on purpose: Luau's grammar has enough block-opener
       shapes (if/then, for/do, while/do, function, do) that an exact count needs a real
       parser; this flags only clear, large mismatches.
    2. The exact bug class that broke Rent-a-Blorb's first build: DataStoreService:Get(Ordered)?
       DataStore(...) called without a nearby `pcall` -- i.e. unprotected at module load time.

    Returns a list of {"severity": "error"|"warning", "script": path, "message": str}.
    Real runtime correctness can only be confirmed by actually opening the built place in
    Roblox Studio -- this just keeps obviously-broken output from being shipped for review.
    """
    findings = []

    for path, code in scripts.items():
        for open_ch, close_ch, label in (("(", ")", "parentheses"), ("[", "]", "brackets"), ("{", "}", "braces")):
            depth = 0
            for ch in code:
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
            if depth != 0:
                findings.append({
                    "severity": "error",
                    "script": path,
                    "message": f"Unbalanced {label} (net depth {depth:+d}) -- likely truncated or malformed output.",
                })

        openers = len(_BLOCK_OPENERS_RE.findall(code))
        enders = len(re.findall(r"\bend\b", code)) + len(re.findall(r"\buntil\b", code))
        if openers > 0 and enders == 0:
            findings.append({
                "severity": "error",
                "script": path,
                "message": "Found block openers (function/do/if/for/while) but zero `end`/`until` -- almost certainly truncated.",
            })
        elif enders > 0 and abs(openers - enders) > max(3, openers * 0.5):
            findings.append({
                "severity": "warning",
                "script": path,
                "message": f"Block-opener count ({openers}) and end/until count ({enders}) are far apart -- worth a manual read.",
            })

        for match in _DATASTORE_CALL_RE.finditer(code):
            window_start = max(0, match.start() - 400)
            preceding = code[window_start:match.start()]
            if "pcall" not in preceding:
                findings.append({
                    "severity": "error",
                    "script": path,
                    "message": (
                        "DataStoreService:Get(Ordered)DataStore(...) called with no `pcall` in the "
                        "preceding ~400 chars -- this is the exact bug class that silently killed "
                        "Rent-a-Blorb's Main.server.lua require chain. Must be pcall-wrapped."
                    ),
                })

    return findings


def generate_luau_via_llm(idea: dict, model: str = "claude-sonnet-4-6", max_attempts: int = 2) -> dict:
    """
    Generic generation path for any idea other than Rent-a-Blorb. Calls the Anthropic API
    once, lints the result with lint_scripts(), and -- if lint finds errors -- retries up to
    max_attempts total, feeding the lint report back to the model for a corrective pass.
    Raises RuntimeError (with the lint report attached) if it still fails lint after
    max_attempts, rather than silently handing back broken code.
    """
    if anthropic is None:
        raise RuntimeError("pip install anthropic first (see requirements.txt)")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Set it as an environment variable -- "
            "never paste it into code or chat."
        )

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{
        "role": "user",
        "content": LLM_USER_PROMPT_TEMPLATE.format(idea_json=json.dumps(idea, indent=2)),
    }]

    last_findings = None
    for attempt in range(1, max_attempts + 1):
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=LLM_SYSTEM_PROMPT,
            messages=messages,
        )
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        raw_text = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError as e:
            last_findings = [{"severity": "error", "script": "<response>", "message": f"Response was not valid JSON: {e}"}]
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": (
                f"That response was not valid JSON ({e}). Respond again with ONLY the JSON "
                "object -- no markdown fences, no prose."
            )})
            continue

        scripts = result.get("scripts", {})
        errors = [f for f in lint_scripts(scripts) if f["severity"] == "error"]
        if not errors:
            return result

        last_findings = errors
        messages.append({"role": "assistant", "content": raw_text})
        report = "\n".join(f"- [{f['script']}] {f['message']}" for f in errors)
        messages.append({"role": "user", "content": (
            f"That output failed automated QA:\n{report}\n\n"
            "Fix these specific issues and respond again with ONLY the corrected JSON object."
        )})

    raise RuntimeError(
        f"generate_luau_via_llm: still failing lint after {max_attempts} attempt(s) for "
        f"idea {idea.get('title')!r}. Last findings: {json.dumps(last_findings, indent=2)}"
    )


if __name__ == "__main__":
    example_idea = {
        "title": "Rent-a-Blorb",
        "genre_pattern": "brainrot_meme",
        "core_loop": (
            "Players hatch, feed, and rent out absurd meme-mashup creatures called "
            "Blorbs to other players' bases for short-term buffs; learnable in under "
            "15 minutes."
        ),
        "hook": (
            "Instead of a one-off meme cash-grab, Blorbs generate ongoing rental "
            "income for their owners, giving the meme premise a light economy that "
            "can deepen post-launch rather than flattening after the initial spike."
        ),
        "economy_or_social_design": (
            "The rental marketplace is the core scarcity/trading loop; a breeding "
            "sink prevents rental-Blorb inflation; showing off rare Blorbs is the "
            "social hook."
        ),
        "build_complexity": "low",
        "ai_disclosure_note": (
            "AI would generate the initial wave of Blorb designs, names, and rental "
            "flavor text; a human needs to tune rental payout balance so the economy "
            "doesn't inflate within days."
        ),
    }
    result = generate_luau_for_idea(example_idea)
    print(json.dumps(result["level_config"], indent=2))
    print(f"\n--- {len(result['scripts'])} scripts generated ---")
    for path in result["scripts"]:
        print(f"  {path}")
