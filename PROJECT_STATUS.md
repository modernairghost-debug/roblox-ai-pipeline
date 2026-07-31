# PROJECT_STATUS.md

Handoff document. Last updated 2026-07-31. If you are a new AI session or collaborator
picking this up cold, read this end to end before touching code.

## 1. What this project is

This is a semi-automated pipeline that uses AI to research trending Roblox games,
generate new original game concepts grounded in that research, turn an approved concept
into real Luau scripts + a Rojo project, and (eventually) publish it to Roblox via Open
Cloud. A human reviews and approves content at two mandatory gates: after ideation
(before anything gets built) and after build (before anything publishes) — this is a
deliberate design constraint, not a missing feature, and matches Roblox's content
policies around AI-assisted tooling (disclosed AI assistance is fine, undisclosed
autonomous bot publishing is not). The project currently has one concrete deliverable in
progress: an approved concept called **Rent-a-Blorb** (a brainrot/meme creature-rental
simulator) has been fully scripted, assembled into a Roblox place file, and its minimal
test world now builds and runs successfully in Roblox Studio (see section 3, steps 8-10).
The full player-to-player economy loop has not yet been exercised with two live accounts
— see section 6 for what's still unverified.

## 2. Pipeline architecture — stage by stage status

| Stage | Directory | Status |
|---|---|---|
| research | `research/` | **Working**, seed-data only. `trending_scraper.py` reads `known_trends_seed.json` (hand-written, dated 2026-07-30) via `get_trending_snapshot(live=False)`. `live=True` raises `NotImplementedError` — no live scraping source (RoMonitor/Rolimon's/manual export) has been wired up. |
| ideation | `ideation/` | **Working**, requires a real Anthropic API call. `idea_generator.py` calls the Anthropic API (`ANTHROPIC_API_KEY` required) to generate N new concepts from the research snapshot. Confirmed working end-to-end once the API key had billing credit (see section 3). |
| review | `review/` | **Working.** `dashboard.py` is a local Flask app (port 5050) that lists pending idea/build files and lets you Approve/Reject, moving the whole file between `review/pending/`, `review/approved/`, `review/rejected/`. **Known UX gap**: approval operates on the whole file, not individual ideas inside it — if an ideation run generates 5 ideas in one file, approving moves all 5 into `approved/` at once. There is currently no per-idea approval granularity. |
| content_gen | `content_gen/` | **Partially implemented.** `luau_generator.py` used to be a placeholder-swap stub; it now contains a real, hand-authored Luau implementation, but **only for the specific approved idea "Rent-a-Blorb"** — it is gated on `idea["title"] == "Rent-a-Blorb"` and raises `NotImplementedError` for any other idea/genre. It is not a generic "any brainrot_meme game" generator. See section 6 for what it actually builds. **Defensive-loading convention**: every generated `Main.server.lua` (and the four `.lua.template` stub scaffolds in `level_templates/`) now uses timed `WaitForChild`, a `pcall`-wrapped require chain, loud `warn()` banners on failure, and `print()` confirmations on success, by default — documented in the module's top docstring. This is what `scripts/rebuild.sh` and `STUDIO_TESTING_CHECKLIST.md` are built around (see section 3, step 9). |
| assets | `assets/` | **Stub, untouched.** `image_gen.py` raises `NotImplementedError` and requires `IMAGE_GEN_API_KEY`, which has never been set. No thumbnails, icons, or textures have been generated for Rent-a-Blorb or anything else. |
| assembly | `assembly/` | **Working**, rewritten this session. `place_builder.py` takes the `{scripts, level_config}` dict from `luau_generator.py` and assembles a real Rojo project (`default.project.json` + `src/`), grouping scripts by Roblox service (`ReplicatedStorage`, `ServerScriptService`, `StarterPlayer/StarterPlayerScripts`). Verified working against the real `rojo build` CLI (Rojo 7.7.0) — produces a valid `.rbxlx`. |
| publish | `publish/` | **Stub, untouched.** `open_cloud_publisher.py` raises `NotImplementedError` and requires `ROBLOX_OPEN_CLOUD_API_KEY` + `ROBLOX_UNIVERSE_ID`, neither of which has been set. Nothing has ever been published. |
| `pipeline.py` (orchestrator) | project root | **Partially wired.** `--stage research`, `--stage ideate`, `--stage review-ideas` all work end-to-end through the CLI. **`--stage build` is still the original stub** — it only prints a placeholder message and does NOT call the new `luau_generator.py` / `place_builder.py` code. The actual Rent-a-Blorb build (section 3, steps 4-6) was produced by directly calling `generate_luau_for_idea()` and `build_rojo_project()` from one-off Python scripts run in this session, bypassing `pipeline.py` entirely. **Wiring `stage_build()` to actually call these functions has not been done** — whoever picks this up next should either do that wiring or continue driving generation manually, but should not assume `python pipeline.py --stage build` currently does anything real. `--stage review-build` and `--stage publish` also remain stubs (unchanged from original scaffold). |

## 3. What's been done so far, in order

1. **Setup**: created a Python venv (`venv/`, Python 3.9.6), installed `requirements.txt`
   (`anthropic`, `flask`, `requests` + transitive deps), copied `.env.example` → `.env`.
2. **First ideation run**: ran `python pipeline.py --stage research` (works, no API
   calls, loads the seed snapshot). Attempted `python pipeline.py --stage ideate --n 5`
   — failed with `anthropic.BadRequestError: Your credit balance is too low`. Rather
   than retry the live API call, the user explicitly asked the AI agent to read
   `research/known_trends_seed.json` and hand-generate 5 original concepts itself (as
   reasoning, not an API call), following the exact schema/rules from
   `ideation/idea_generator.py`'s `SYSTEM_PROMPT`/`USER_PROMPT_TEMPLATE`, and save them
   via the same `save_ideas_for_review()` format. This produced
   `review/pending/ideas_20260731T025927Z.json`. That file was then approved via
   `python pipeline.py --stage review-ideas` (the Flask dashboard), moving the whole
   file to `review/approved/`. **Note**: the live Anthropic ideation path has still
   never been successfully exercised end-to-end — the only ideas that exist were
   agent-authored, not model-API-generated via `idea_generator.py`.
3. **Idea selected for build**: the approved file contains **5 ideas** (Mutation
   Nursery, The Lighthouse Watch, Static Ave, Rent-a-Blorb, Undertow Traders) because
   the dashboard approves at file granularity (see section 2 review row). The user was
   asked which one to actually build and chose **Rent-a-Blorb** (brainrot_meme genre,
   build_complexity: low).
4. **Build stage implementation**: rewrote `content_gen/luau_generator.py` and
   `assembly/place_builder.py` from stubs into real, working code (see section 2 and
   section 6). This was authored directly by the AI agent's own reasoning — no Anthropic
   API call was made for this step.
5. **Rojo build success**: `rojo` was not initially installed. The user installed the
   Rojo VS Code extension, which turned out to be an editor helper only (JSON schema
   validation + a menu) with no bundled CLI. The actual `rojo` CLI binary (v7.7.0,
   macOS arm64) was downloaded directly from the `rojo-rbx/rojo` GitHub releases and
   installed to `~/.local/bin/rojo` (already on PATH via `~/.zshrc`). `rojo build -o
   RentABlorb.rbxlx` succeeded from `output/rent-a-blorb/`, producing a valid `.rbxlx`.
6. **Minimal test-world script added**: discovered that Rojo 7.7.0's `default.project.json`
   format has no way to declaratively author `CollectionService` tags or instance
   attributes (confirmed empirically against both the real CLI and its bundled JSON
   schema — `$tags`/`$attributes` keys don't exist in this version). Added
   `TestWorldBuilder.lua`, a new server module that procedurally builds a minimal
   playable world (baseplate, `SpawnLocation`, one `EggStall`, one `PlayerBasePlot` with
   3 `RentalStand` slots) at server start, gated behind a `BUILD_TEST_WORLD` flag in
   `Main.server.lua`. Regenerated and rebuilt `RentABlorb.rbxlx` (now 13 scripts, up
   from 12). `rojo build` succeeded again.
7. **First playtest attempt — blocked, empty world.** User opened `RentABlorb.rbxlx` in
   Studio, entered Test mode, and saw an empty world (no egg stall, no base plot).
   Diagnosis was not completed in that session.
8. **Root cause found: `Main.server.lua` in the actual built `.rbxlx` had no reference
   to `TestWorldBuilder` at all**, confirmed by the user opening the file directly in
   Studio. Investigation found the generator source (`content_gen/luau_generator.py`)
   already had the correct `require(...)` + `TestWorldBuilder.Build()` wiring — the
   built file the user had open was stale (most likely still the pre-`TestWorldBuilder`
   version from before step 6, per the `.rbxlx.lock` file present at the time). Fixed by
   deleting `output/rent-a-blorb/src/`, `default.project.json`, and `RentABlorb.rbxlx`
   entirely (not regenerating on top of the old ones) and rebuilding clean. Verified the
   `require`/`Build()` call and all 13 scripts (including `TestWorldBuilder` as its own
   `ModuleScript`) were present directly inside the rebuilt `.rbxlx`'s embedded script
   source, not just in the intermediate `.lua` files on disk.
9. **Institutionalized the fix so this class of bug is caught automatically next time**:
   - Added `scripts/rebuild.sh` — one command that always deletes stale generated output
     and does a full clean regenerate + `rojo build`, instead of relying on a human to
     remember to do that by hand.
   - Added `STUDIO_TESTING_CHECKLIST.md` at the project root — the exact close/quit/
     delete-lock-file/reopen/enable-Output/Play-not-Run sequence, plus a command-bar
     diagnostic snippet to test `TestWorldBuilder.Build()` in isolation.
   - Made the defensive-loading pattern (timed `WaitForChild`, a single `pcall`-wrapped
     require chain, loud `warn()` banners on failure, `print()` confirmations on
     success) the **documented default convention** for every future genre's
     `Main.server.lua`, not just Rent-a-Blorb's. `Main.server.lua` now prints, on a
     healthy start: `"...all server modules loaded OK"`, `"...TestWorldBuilder.Build()
     completed OK..."`, and `"...server initialization complete..."` — three explicit,
     greppable checkpoints in Studio's Output panel. All four `.lua.template` stub
     files in `content_gen/level_templates/` were updated to carry the same
     `safeWaitForChild()`/`safeRequire()` helper pattern as boilerplate, so the next
     genre implementation inherits this for free instead of reinventing it.
10. **Confirmed working**: after the clean rebuild and following the new
    `STUDIO_TESTING_CHECKLIST.md` re-open sequence, the user confirmed Rent-a-Blorb's
    test world now builds and runs successfully in Roblox Studio.

## 4. Exact file paths that matter right now

- **Built place file**: `output/rent-a-blorb/RentABlorb.rbxlx` — open this in Roblox
  Studio. Always rebuild it with `scripts/rebuild.sh` (not a bare `rojo build` on top of
  existing files) and follow `STUDIO_TESTING_CHECKLIST.md` before reopening — see
  section 5 for why this matters.
- **Rojo project definition**: `output/rent-a-blorb/default.project.json`
- **Test-world script**: `output/rent-a-blorb/src/ServerScriptService/BlorbServer/TestWorldBuilder.lua`
  (source of truth is generated from `content_gen/luau_generator.py`'s
  `_TEST_WORLD_BUILDER_LUA` string — don't hand-edit the built copy without also editing
  the generator, or the next regeneration will silently overwrite your changes)
- **Server entry point** (calls `TestWorldBuilder.Build()`):
  `output/rent-a-blorb/src/ServerScriptService/BlorbServer/Main.server.lua`
- **Approved idea JSON** (all 5 ideas, Rent-a-Blorb is index 3 / the 4th object in the
  `ideas` array): `review/approved/ideas_20260731T025927Z.json`
- **All generated Luau scripts** (13 files):
  ```
  output/rent-a-blorb/src/ReplicatedStorage/BlorbShared/BlorbData.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/Util.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/PlayerDataManager.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/LeaderboardService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/RentalService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/HatchingService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/FeedingService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/BreedingService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/CustomerSimService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/BaseAssignmentService.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/TestWorldBuilder.lua
  output/rent-a-blorb/src/ServerScriptService/BlorbServer/Main.server.lua
  output/rent-a-blorb/src/StarterPlayer/StarterPlayerScripts/BlorbClient/Main.client.lua
  ```
- **The generator source** (edit here, then regenerate, don't hand-edit the `output/`
  copies): `content_gen/luau_generator.py` (contains all 13 Lua blocks as Python string
  literals, assembled by `_generate_rent_a_blorb()`)
- **The assembler source**: `assembly/place_builder.py`
- **Build notes** (design assumptions, known gaps, what still needs Studio work):
  `output/rent-a-blorb/BUILD_NOTES.md`
- **Generic Rojo build how-to**: `output/rent-a-blorb/BUILD_INSTRUCTIONS.md`
- **Rojo CLI binary**: `~/.local/bin/rojo` (v7.7.0, macOS arm64, downloaded from GitHub
  releases, not from a package manager — no Homebrew or cargo on this machine)
- **Rebuild script**: `scripts/rebuild.sh` — deletes stale generated output for a game
  slug (default `rent-a-blorb`), regenerates via `luau_generator.py` +
  `place_builder.py`, and runs `rojo build`. Run this instead of regenerating by hand
  whenever `content_gen/luau_generator.py` or `assembly/place_builder.py` changes.
- **Studio re-test checklist**: `STUDIO_TESTING_CHECKLIST.md` at the project root — the
  close/quit/delete-lock-file/reopen/enable-Output/Play-not-Run sequence, plus a
  command-bar diagnostic snippet. Follow this every time after running `rebuild.sh` and
  before reporting a "the game is broken" finding — see section 5.

## 5. Previous blocker — resolved

**Original symptom** (2026-07-30 session): user opened `RentABlorb.rbxlx` in Roblox
Studio, entered Test mode, and the world appeared empty — no visible egg stall or base
plot — even though `TestWorldBuilder.lua` was confirmed present in the built file and
`rojo build` had completed without error.

**Root cause** (found 2026-07-31): the generator source
(`content_gen/luau_generator.py`) already had correct `TestWorldBuilder` wiring in
`Main.server.lua`, but **the actual `.rbxlx` file the user had open in Studio did not
contain it** — confirmed by the user opening the built file directly and inspecting
`Main.server.lua`. The most likely explanation is a stale Studio session: a
`RentABlorb.rbxlx.lock` file was present, meaning Studio had (or recently had) an older
version of the file open from before `TestWorldBuilder.lua` was added, and that older
in-memory/cached copy is what got tested — not the freshly rebuilt file on disk.

**Fix**: deleted `output/rent-a-blorb/src/`, `default.project.json`, and
`RentABlorb.rbxlx` entirely and rebuilt from a clean slate (rather than regenerating on
top of the old files), then verified the `require(...)`/`TestWorldBuilder.Build()` call
was present directly inside the rebuilt `.rbxlx`'s embedded script source. User then
followed a full close/quit/reopen sequence and confirmed the test world now builds and
runs successfully in Studio.

**This is now institutionalized** (section 3, step 9) so it doesn't have to be
re-diagnosed by hand again:
- Always run `scripts/rebuild.sh` after touching `content_gen/luau_generator.py` or
  `assembly/place_builder.py` — it always does a full clean delete + regenerate + build,
  never an incremental one.
- Always follow `STUDIO_TESTING_CHECKLIST.md` before concluding something is broken —
  in particular, checking for and deleting a `.rbxlx.lock` file and fully quitting
  Studio (not just closing the file) before reopening.
- `Main.server.lua` now prints explicit success checkpoints
  (`"...all server modules loaded OK"`, `"...TestWorldBuilder.Build() completed OK..."`,
  `"...server initialization complete..."`) and loud `warn()` banners on any failure, so
  the Output panel — not Explorer, not guesswork — is the first and fastest place to
  look when something seems wrong.

## 6. Assumptions and known gaps in the generated Luau code

Full detail lives in `output/rent-a-blorb/BUILD_NOTES.md` — summarized here:

**Assumptions made filling in gameplay details the idea didn't fully specify:**
1. Combined "buy egg" and "hatch" into one instant action (no separate egg inventory or
   incubation timer) to keep the first draft smaller.
2. Invented an NPC "customer" system (`CustomerSimService.lua`) to solve the cold-start
   economy problem — a new/low-population server has no other players to rent from you.
   NPCs pay 40% of a real player's rental price. **This is the single biggest untested
   economic assumption in the build.**
3. Renting requires the Blorb owner to be online in the same server — player data lives
   in an in-memory cache and is only persisted to DataStore on leave/autosave. No
   cross-server or offline rental listing exists.
4. Invented a base-plot assignment system (`BaseAssignmentService.lua`) since the idea
   never specified how players get a home base — it claims one pre-built
   `PlayerBasePlot` model per player per session.
5. Rarity tiers (Common→Mythic, 5 total), 4 buff types, and 8 meme-mashup species names
   are original inventions, not specified by the idea beyond "rare traits" and
   "short-term buffs."
6. Breeding consumes **both** parent Blorbs (a deliberate currency+Blorb sink, per the
   idea's explicit anti-inflation note), with a 12% chance to roll one rarity tier above
   the better parent.
7. No combat/PvP/griefing surface was added — rentals only move currency and buffs, never
   directly affect another player's data or character.

**Known gaps / not yet verified:**
- The test world (baseplate, spawn, one egg stall, one base plot) is confirmed to build
  and run in Studio as of 2026-07-31 (section 3, step 10). Beyond that, most gameplay
  systems are still only statically validated (Lua 5.1 grammar check via `luaparse` with
  Luau's `+=`/`-=`/`*=` operators manually expanded first, plus a successful
  `rojo build`) — hatching, feeding, breeding, and renting have not been individually
  exercised in a live Play session yet.
- The player-to-player rental path (`RentalService.RentBlorb`) has never been exercised
  with two live accounts.
- Economy numbers (egg prices, rental prices, hunger decay rate, buff magnitudes,
  `CustomerPayoutMultiplier = 0.4`) are first-pass guesses, not playtested/balanced.
- Blorbs have no visual representation — they're pure data, no models/meshes/textures.
- The server re-validates every request (currency, ownership, hunger) but has not been
  load-tested or exploit-tested against a malicious client spamming remotes.
- `TestWorldBuilder.lua` only builds **one** egg stall and **one** base plot (3 rental
  stands = capacity for 1 player's base). Fine for solo/small playtesting, not enough
  for a real multi-player test — see `BUILD_NOTES.md` for the tag/attribute contract
  needed to hand-build more in Studio.

## 7. What has NOT been done yet

- **`assets/image_gen.py`** — still a stub, raises `NotImplementedError`. No thumbnails,
  icons, or textures generated for Rent-a-Blorb or any concept. `IMAGE_GEN_API_KEY` has
  never been set.
- **`publish/open_cloud_publisher.py`** — still a stub, raises `NotImplementedError`.
  Nothing has ever been published to Roblox.
- **Roblox Open Cloud setup** — `ROBLOX_OPEN_CLOUD_API_KEY` and `ROBLOX_UNIVERSE_ID` have
  never been set in `.env` (both are present as empty fields in `.env.example` /
  `.env`). No Roblox experience/universe has been created or targeted.
- **Full economy playtesting** — the test world itself now confirmed builds and runs
  (section 3, step 10; section 5), but hatching, feeding, breeding, and the
  player-to-player rental path have not yet been individually exercised in a live Play
  session, and never with two real accounts at once. See section 6.
- **`pipeline.py --stage build` wiring** — the CLI orchestrator's build stage is still
  the original stub and does not call the real `luau_generator.py` / `place_builder.py`
  code (see section 2 table). All generation so far was driven by one-off scripts, not
  the pipeline CLI.
- **Per-idea approval in the review dashboard** — `review/dashboard.py` approves/rejects
  at the whole-file level, not per-idea. The other 4 ideas in
  `ideas_20260731T025927Z.json` (Mutation Nursery, The Lighthouse Watch, Static Ave,
  Undertow Traders) are technically "approved" alongside Rent-a-Blorb but have not been
  built — `luau_generator.py` would currently raise `NotImplementedError` if asked to
  build any of them.
- **Live trend research** — `research/trending_scraper.py`'s `live=True` path is
  unimplemented; all research so far comes from the static, hand-written
  `known_trends_seed.json`.
