-- Rent-a-Blorb -- assigns each player a pre-built base plot (with rental stand slots)
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
