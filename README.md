# Roblox AI Game Pipeline (Scaffold)

A semi-automated pipeline: AI handles research, ideation, content generation, and asset
creation. **A human reviews and approves every game before it publishes.** This is by
design, not a limitation — it's what keeps this sustainable on Roblox and consistent
with their content policies (AI-assisted tooling is fine and common; undisclosed
autonomous bot publishing is not).

## Pipeline stages

```
research/        -> pulls current trending Roblox games + patterns (charts, genres, mechanics)
ideation/         -> Claude generates new game concepts grounded in that research
content_gen/      -> turns an approved concept into Luau scripts + level layout
assets/           -> generates thumbnail/icon/texture assets (pluggable: Nano Banana, etc.)
assembly/         -> assembles a Roblox place file from generated content
review/           -> local dashboard: approve/reject/edit before anything goes live
publish/          -> pushes approved game to Roblox via Open Cloud API
pipeline.py       -> orchestrates the above, stage by stage, with a human gate before publish
```

## Status: SCAFFOLD

Every stage has a real, working interface but stubbed I/O (no live API keys wired in —
you provide those via environment variables when you're ready to run it for real). This
is meant to be dropped into Claude Code, where it has actual network access, and built
out stage by stage the same way Ghost was.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your own keys, never commit this file
```

Required env vars (set these yourself — never paste keys into chat or code):
- `ANTHROPIC_API_KEY` — for ideation + Luau generation
- `IMAGE_GEN_API_KEY` — for thumbnail/asset generation (whichever model you pick)
- `ROBLOX_OPEN_CLOUD_API_KEY` — for publishing
- `ROBLOX_UNIVERSE_ID` — target experience/universe ID

## Run

```bash
python pipeline.py --stage research      # pull trending games + patterns
python pipeline.py --stage ideate        # generate N new concepts from research
python pipeline.py --stage review-ideas  # approve which concept(s) move forward
python pipeline.py --stage build         # generate Luau + assets for approved concept
python pipeline.py --stage review-build  # approve the built game before publish
python pipeline.py --stage publish       # push to Roblox via Open Cloud
```

Or `python pipeline.py --stage all` to run research -> ideate and stop (build/publish
always require an explicit human review flag, on purpose).

## Design principles baked into this scaffold

1. **Human approval gates before ideation->build and before build->publish.** Not
   optional flags — the pipeline halts and writes to `review/pending/` until you approve.
2. **Every generated game gets an AI-disclosure field** in its metadata (`ai_assisted: true`
   + a short note), matching Roblox's content policies and Andrew's own standing rule of
   not misrepresenting how content was made.
3. **Genre templates over pure randomness.** Idea generation is grounded in researched
   patterns (economy design, social hooks, LiveOps cadence) — not just "generate a random game."
4. **No credentials in code.** All keys via environment variables, matching your standing
   instruction to never store API keys anywhere persistent.
