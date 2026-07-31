-- Rent-a-Blorb -- small server-side helpers shared across services.

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
