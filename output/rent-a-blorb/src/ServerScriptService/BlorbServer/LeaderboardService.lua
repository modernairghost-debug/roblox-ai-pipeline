-- Rent-a-Blorb -- global "rarest Blorb ever owned" leaderboard via OrderedDataStore.
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
	label.Text = table.concat(lines, "\n")
end

return LeaderboardService
