# Studio Testing Checklist

Follow this exactly, in order, every time you rebuild `RentABlorb.rbxlx` (or any other
place built by `scripts/rebuild.sh`) and go test it in Roblox Studio. This exists because
a session lost real time to a false "the game is broken" diagnosis that was actually
"Studio was showing a stale cached copy of the file." Skipping steps 1-4 is how that
happens again.

## Before you rebuild

1. **Run the rebuild script**, don't regenerate by hand:
   ```bash
   ./scripts/rebuild.sh
   ```
   This deletes the stale `output/rent-a-blorb/src/`, `default.project.json`, and
   `RentABlorb.rbxlx`, regenerates everything from `content_gen/luau_generator.py` +
   `assembly/place_builder.py`, and rebuilds with `rojo build`. Always do a full clean
   rebuild -- never assume the previous build is still valid after touching the
   generator source.

## Closing out the old Studio session (do this even if you're "pretty sure" nothing's open)

2. **If `RentABlorb.rbxlx` is open in Studio, close the file without saving.**
   File > Close, and if prompted to save changes, **do not save** -- saving would
   overwrite the freshly rebuilt file on disk with Studio's stale in-memory copy.
3. **Quit Studio completely: Cmd+Q.** Closing the file/tab is not enough -- Studio can
   keep state around. A full quit guarantees a clean slate.
4. **Check for a lock file and delete it if present:**
   ```bash
   ls output/rent-a-blorb/*.lock
   rm -f output/rent-a-blorb/RentABlorb.rbxlx.lock
   ```
   A `.rbxlx.lock` file next to the place file means some Studio process still has (or
   recently had) it open. Delete it before reopening -- an orphaned lock file is the
   single most likely reason Studio shows you an outdated version of the file.

## Reopening

5. **Reopen fresh from Finder**, not from Studio's "Recent Files" list (Recent Files can
   sometimes reopen a cached reference rather than reading the file fresh off disk).
   Navigate to `output/rent-a-blorb/RentABlorb.rbxlx` in Finder and double-click it.

## Before you hit Play

6. **Enable the Output panel via the Mac menu bar: View > Output.** Do this from the top
   menu bar, not the ribbon/toolbar inside the Studio window -- the ribbon's Output
   toggle is easy to miss or click past. Confirm the Output panel is actually visible and
   docked somewhere before testing, not just enabled in a menu you didn't check.
7. **Use Test > Play, not Run.** Run mode does not spawn a player character, which can
   look identical to "the game is broken" for a completely different reason (no
   character to walk around with). Play mode spawns you in as a real client, which is
   what actually exercises `Players.PlayerAdded`, `TestWorldBuilder.Build()`, and the
   rest of the server startup path.

## What you should see in Output on a successful start

With the defensive-loading pattern now baked into `Main.server.lua` (see
`content_gen/luau_generator.py`), a healthy start prints, in order:

```
RentABlorb: all server modules loaded OK.
RentABlorb: TestWorldBuilder.Build() completed OK -- check Workspace.TestWorld.
RentABlorb: server initialization complete -- Remotes wired, background loops running.
```

If you see a `warn()` banner (a block of `=====` lines) instead, read the message
between the banners -- it names the exact module or WaitForChild path that failed, which
is the actual root cause. Do not go looking at Workspace/Explorer first; the Output
panel will already tell you why the world looks empty.

## If Output shows no errors but the world still looks empty

8. **Check Explorer > Workspace for whether the tagged parts actually exist.** Expand
   `Workspace` and look for a `Folder` named `TestWorld`.
   - **`TestWorld` is missing entirely**: `TestWorldBuilder.Build()` never ran or
     errored before creating the folder. Re-check Output -- you likely missed a warning.
   - **`TestWorld` exists but is missing children** (`Baseplate`, `DefaultSpawn`,
     `EggStall_Basic`, `PlayerBasePlot_1`): the build partially ran and then errored.
     Check Output for the specific line.
   - **`TestWorld` exists complete** but you still don't see anything: check your
     character's spawn position relative to the built parts (the default spawn is at
     roughly `(0, 1, -10)`), and check for a stale camera / being stuck underground.

## Command bar diagnostic (fastest manual check, once Studio is fully reopened per steps 2-5)

Paste this into Studio's Command Bar (View > Command Bar) while in Edit mode (not
Play mode) to directly re-run `TestWorldBuilder.Build()` and see the raw result without
waiting for a full Play session:

```lua
local ok, err = pcall(function()
	require(game.ServerScriptService.BlorbServer.TestWorldBuilder).Build()
end)
return ok, err
```

- `true, nil` -- it ran successfully. If `Workspace.TestWorld` still doesn't show up,
  something else is wrong (e.g. you're looking at the wrong Workspace, or a script
  elsewhere is deleting it).
- `false, <error message>` -- the error message is your root cause. Common causes:
  `TestWorldBuilder` module missing entirely (rebuild didn't actually include it --
  re-run `scripts/rebuild.sh` and check its script list output), or a typo'd service/
  property name inside `TestWorldBuilder.lua`.

Note this only tests `TestWorldBuilder.Build()` in isolation -- it does not test the
full `Main.server.lua` require chain or Remote wiring, which only run when the actual
server `Script` starts (i.e. in Play mode).
