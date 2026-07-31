# LEARNINGS.md

Append-only running log for the daily automated build (`trig_01FNydVeCfVzXcJKJn9N73ER`).
Every day's scheduled agent session reads this FIRST, before generating anything, and
appends a new entry at the end after building. The goal is for quality to compound over
time instead of every day starting from zero -- treat this like a growing style guide
written by the agent, for the agent.

Each entry should be short and specific: what happened, why, and the resulting rule (if
any). Promote anything that becomes a hard, always-apply rule up into
`content_gen/luau_generator.py`'s `LLM_SYSTEM_PROMPT` itself (not just this file) once
it's proven itself more than once -- this file is for newer, less-proven observations
and for a running history of what's been built so far.

## Hard rules already baked into LLM_SYSTEM_PROMPT (don't relitigate these, just follow them)

1. Never call `DataStoreService:GetDataStore()` / `GetOrderedDataStore()` unprotected at
   module load time -- pcall it, nil-fallback gracefully. (Origin: this exact bug broke
   Rent-a-Blorb's first build on 2026-07-31 -- an unpublished place throws on that call,
   which cascaded through the whole require chain and left Workspace silently empty.)
2. Wrap Main.server.lua's require chain and TestWorldBuilder.Build() call each in their
   own pcall with loud warn()/print() -- never let a startup failure be silent.
3. TestWorldBuilder must build a genuinely playable minimal world procedurally (no
   hand-placed Studio parts required) and guard against double-building.
4. Every RemoteEvent handler pcall-wrapped, user-facing errors via a Notify remote.
5. Keep scope to one clear core loop -- a working MVP beats an elaborate broken one.

## Ideas built so far (check this before generating a new one -- avoid repeats/near-repeats)

- **Rent-a-Blorb** (brainrot_meme) -- hand-authored, playtested, working. Creature
  rental/breeding economy sim.

## Running log

### 2026-07-31 -- session 2 (setup)
Fixed the DataStore bug above, generalized the generator beyond Rent-a-Blorb, wired
`pipeline.py --stage build`, added `lint_scripts()` heuristic QA, set up the daily
scheduled task. Pivoted the daily job away from Anthropic-API-key generation (user
doesn't want per-token billing) to the scheduled agent session generating content
itself on the subscription. No automated daily run has fired yet -- this file's next
entry should be written by that first real run.

<!-- Next entry goes here. Format suggestion:
### YYYY-MM-DD -- <game title>
What you built, genre_pattern, one-line hook. Anything that broke lint and how you fixed
it. Anything you noticed that's worth turning into a rule (either here as a
still-proving-itself observation, or promoted straight into LLM_SYSTEM_PROMPT if you're
confident). Rojo build result. Whether you pushed successfully.
-->
