# Build instructions

1. Install Rojo: https://rojo.space/docs/installation/
2. From this directory, run: `rojo build -o output.rbxlx`
3. Open output.rbxlx in Roblox Studio to inspect before publishing
4. Or use `rojo` + Open Cloud to push directly (see publish/ stage)

## World-building still needed in Studio

- At least 2 parts tagged 'EggStall' (CollectionService), each with an EggType attribute ('BasicEgg' or 'RareEgg') and a child ProximityPrompt.
- At least 6-12 Models tagged 'PlayerBasePlot', each containing exactly 3 parts tagged 'RentalStand' (each with a child ProximityPrompt and a preset SlotIndex attribute of 1, 2, or 3) plus one part or SpawnLocation named 'BaseSpawn'. More plots = more concurrent players supported.
- Optional: a part named 'Leaderboard_Board' in Workspace with a SurfaceGui containing a TextLabel named 'Display', for the rarest-Blorb leaderboard.
