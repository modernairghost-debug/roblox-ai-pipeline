-- Rent-a-Blorb -- minimal test world, built procedurally at server start so the place
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
