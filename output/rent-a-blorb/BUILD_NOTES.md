# Rent-a-Blorb -- Build Notes

## What was generated

- A full server-authoritative economy in Luau: hatching (buy+hatch combined), hunger
  decay + feeding, breeding (the inflation sink), player-to-player renting, a simulated
  NPC-customer demand system, a base-plot assignment system, and a global "rarest Blorb"
  leaderboard via `OrderedDataStore`.
- A functional (not polished) client HUD: currency display, a scrollable Blorb inventory
  list with Feed / Place-on-stand / Breed actions, buy-egg buttons, and `ProximityPrompt`
  wiring for world interactions (egg stalls, rental stands).
- **`TestWorldBuilder.lua`**: a procedural bootstrap that builds a minimal playable world
  at server start (a baseplate, a `SpawnLocation`, one `EggStall`, and one
  `PlayerBasePlot` with all 3 `RentalStand` slots + a `BaseSpawn`), with the correct
  `CollectionService` tags, attributes, and `ProximityPrompt`s already wired up. This
  exists so the built `.rbxlx` is playtestable immediately, with no manual Studio work
  first. It's guarded by a `BUILD_TEST_WORLD` flag at the top of `Main.server.lua` --
  flip that to `false` (or delete the module and its call site) once you've built real
  level art to replace it. Rojo's project-file format (this version, 7.7.0) has no way
  to declaratively author `CollectionService` tags or attributes on static instances, so
  a procedural builder script was the more reliable path versus hand-encoding instance
  XML.
- A Rojo project (`default.project.json` + `src/`) grouping the 13 generated scripts into
  `ReplicatedStorage` (one shared data module), `ServerScriptService` (10 server modules +
  the entry script), and `StarterPlayer/StarterPlayerScripts` (1 client script). All
  server modules live in one `BlorbServer` folder and `require()` each other as siblings
  via `script.Parent`.
- Image/thumbnail/asset generation was skipped per instructions -- `assets/image_gen.py`
  is untouched and still stubbed, and no `IMAGE_GEN_API_KEY` was set or used.

All 13 `.lua` files were checked with a standalone Lua 5.1 parser (`luaparse`) after
temporarily expanding Luau's `+=`/`-=`/`*=` compound-assignment operators (which that
parser predates) back to `x = x + y` form -- every file parses cleanly. The project also
builds successfully with the real `rojo build` CLI (Rojo 7.7.0) into a `.rbxlx`. Neither
check exercises runtime behavior -- it hasn't been played yet.

## What still needs manual work in Studio

1. **World geometry beyond the test world.** `TestWorldBuilder.lua` covers the minimum
   to playtest solo/with a couple of accounts (1 egg stall, 1 base plot = 1 player's
   worth of rental stands). For anything beyond quick local testing you still need to
   build, by hand, in Studio:
   - More parts tagged `EggStall` (via `CollectionService`), each with an `EggType`
     attribute set to `"BasicEgg"` or `"RareEgg"` and a child `ProximityPrompt`.
   - More Models tagged `PlayerBasePlot`, each containing exactly 3 parts tagged
     `RentalStand` (each with a child `ProximityPrompt` and a preset `SlotIndex`
     attribute of `1`, `2`, or `3` -- the server sets `OwnerUserId` on these
     dynamically, you don't need to) plus one part or `SpawnLocation` named
     `BaseSpawn`. More plots supports more concurrent players; the server just logs a
     warning and refuses to assign a base once plots run out, it doesn't crash.
   - Real level art -- the test world is plain colored blocks, not a shippable look.
   - Optional: a part named `Leaderboard_Board` in Workspace with a `SurfaceGui`
     containing a `TextLabel` named `Display`, if you want the rarest-Blorb
     leaderboard rendered in-world. `LeaderboardService.RefreshBoard()` no-ops
     harmlessly if this doesn't exist yet.
2. **UI polish.** The client script builds its entire HUD in code (no Frames/9-slice
   art/animations designed in Studio). It's functional enough to playtest the full loop
   but is not shippable -- a real UI pass (inventory grid, an egg-hatch reveal
   animation, rental countdown timers, sound/VFX on rent/feed/breed) belongs in Studio
   or a proper UI framework.
3. **Economy balance.** WalkSpeed/JumpPower buff multipliers, hunger decay rate, egg
   prices, and rental prices are first-pass numbers -- see `BlorbData.Config` and
   `RarityTiers` in `BlorbData.lua`. They need real playtesting, especially the Snacks
   economy (starter currency, egg costs, rental payouts), so it neither stalls out new
   players nor inflates within days. The NPC customer payout multiplier
   (`CustomerPayoutMultiplier = 0.4`) in particular is a guess, not a balanced number.
4. **Blorb visuals.** Species are currently just name strings (e.g. "Turbo Sock
   Goblin") with no model, mesh, or texture -- Blorbs are pure data right now, not
   physical instances anywhere in the world. You'll need to either build/commission
   actual creature models per species, or wire up `assets/image_gen.py` (once you have
   an `IMAGE_GEN_API_KEY`) for 2D icon representations, and connect them to the HUD and
   world.
5. **Playtesting with multiple real accounts.** The player-to-player rental path
   (`RentalService.RentBlorb`) has only been syntax-checked, never exercised with two
   live players. Test the actual flow: place a Blorb, have a second account rent it,
   confirm currency transfers and the buff applies and expires correctly.

## Assumptions made filling in gameplay details the idea didn't fully specify

1. **Combined "buy egg" and "hatch" into one action.** The idea names three verbs --
   "hatch, feed, and rent." A fuller anticipation-building flow would sell an egg item,
   let it sit in inventory, then have a separate hatch action (maybe with an incubation
   timer). I simplified to instant buy-and-reveal to keep the data model and client
   smaller for a first draft. Splitting this back out later is straightforward: add an
   `eggs` array to player data and a `HatchEgg(player, eggId)` entry point in
   `HatchingService.lua`.
2. **Invented an NPC "customer" system to solve the cold-start economy problem.** The
   idea's economy is explicitly player-to-player ("Blorbs generate ongoing rental
   income... showing off rare Blorbs is the social hook"), but a brand-new or
   low-population server has no one to rent from you. `CustomerSimService.lua` adds
   simulated customers that periodically rent an idle stand slot at a reduced rate
   (40% of a real player's price) so solo play and early low-pop servers still have an
   earning loop, while keeping real player rentals strictly more valuable. This is the
   single biggest economic assumption in this build and needs real playtesting.
3. **Renting requires the owner to be online in the same server.** Player data lives
   in an in-memory cache (`PlayerDataManager.lua`) while online and is only persisted
   to `DataStoreService` on leave/autosave/`BindToClose`. A cross-server or
   offline-listing marketplace (e.g. via `MessagingService` or a shared
   DataStore-backed listing table) would be a real feature to add later but is out of
   scope here.
4. **Invented the base-plot assignment system.** Nothing in the idea specifies how
   players get a home base with rental stands. `BaseAssignmentService.lua` claims one
   pre-built `PlayerBasePlot` model per player for their session (tagging its
   `RentalStand` children with the player's `OwnerUserId`) and releases it on leave.
   This is the piece that gives `RentalStand` parts an actual owner -- without it, the
   rent loop has no "whose base is this" concept.
5. **Rarity tiers, hatch odds, species list, and buff types are original inventions,**
   not specified by the idea beyond "rare traits" and "short-term buffs." Five tiers
   (Common -> Mythic), four buff types (speed / jump / hatch-luck / snack-income), and
   eight meme-mashup species names were chosen to give the economy enough texture to
   be interesting without becoming unmanageable for a first build. All are easy to
   extend -- add entries to the relevant table in `BlorbData.lua`.
6. **Breeding consumes both parent Blorbs**, not just one and not neither, to make it
   a real currency-and-Blorb sink -- the idea explicitly calls out that a "breeding sink
   prevents rental-Blorb inflation." A small (12%) chance to roll one rarity tier above
   the better parent gives breeding a purpose beyond re-rolling species/buff type.
7. **No combat, PvP, or griefing surface was added.** Rentals only transfer currency
   and grant buffs; they never let one player directly affect another's Blorbs, data,
   or character beyond the buff itself. This seemed like the safer default for an
   unmoderated MVP. The server re-validates currency, ownership, and hunger on every
   single request (nothing is trusted from the client), but this hasn't been
   load-tested or exploit-tested against a malicious client spamming remotes -- do that
   before publishing.

## Not built (explicitly out of scope for this pass)

- `assets/image_gen.py` remains stubbed -- no thumbnails, icons, or Blorb textures were
  generated, and no `IMAGE_GEN_API_KEY` was used or required.
- `publish/` was not touched.
- No physical 3D level geometry was generated (see "World geometry" above) -- this
  pipeline stage has never done level layout, only scripts.
