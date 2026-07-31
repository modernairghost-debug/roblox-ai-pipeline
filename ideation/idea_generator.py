"""
ideation/idea_generator.py

Takes the research snapshot and generates N new Roblox game concepts, grounded in
observed genre patterns rather than pure randomness. Uses the Anthropic API directly.

Requires: ANTHROPIC_API_KEY environment variable (never hardcode it, never commit it).
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from research.trending_scraper import get_trending_snapshot  # noqa: E402

try:
    import anthropic
except ImportError:
    anthropic = None

IDEAS_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "review", "pending")

SYSTEM_PROMPT = """You are a Roblox game design analyst. You generate NEW original game
concepts grounded in researched platform trends -- not clones of existing games.

Rules:
- Never propose copying an existing game's name, IP, or exact mechanics wholesale.
- Each concept must clearly state which genre pattern it draws from and WHY that pattern
  fits (economy design, social hooks, LiveOps potential, etc).
- Prefer concepts with a real core loop that could sustain a trading/scarcity economy or
  genuine social hook -- not just a reskin.
- Flag realistic build complexity (low/medium/high) honestly. Don't oversell.
- Output must be valid JSON matching the requested schema exactly, nothing else.
"""

USER_PROMPT_TEMPLATE = """Here is current Roblox trend research:

{research_json}

Generate {n} new, original Roblox game concepts. For each, use this JSON schema:

{{
  "title": "working title",
  "genre_pattern": "which pattern from genre_patterns this draws from",
  "core_loop": "1-2 sentences describing the actual gameplay loop",
  "hook": "what makes this specific to try, not just a generic entry in the genre",
  "economy_or_social_design": "how it creates player-to-player value or a real economy",
  "build_complexity": "low | medium | high",
  "ai_disclosure_note": "one honest sentence describing what would be AI-generated vs human-designed if built"
}}

Return ONLY a JSON array of {n} objects matching this schema. No preamble, no markdown fences.
"""


def generate_ideas(n: int = 5, model: str = "claude-sonnet-4-6") -> list:
    if anthropic is None:
        raise RuntimeError("pip install anthropic first (see requirements.txt)")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Set it as an environment variable -- "
            "never paste it into code or chat."
        )

    client = anthropic.Anthropic(api_key=api_key)
    research = get_trending_snapshot(live=False)

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                research_json=json.dumps(research, indent=2), n=n
            ),
        }],
    )

    raw_text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    raw_text = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    ideas = json.loads(raw_text)
    return ideas


def save_ideas_for_review(ideas: list) -> str:
    os.makedirs(IDEAS_OUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(IDEAS_OUT_DIR, f"ideas_{timestamp}.json")
    with open(out_path, "w") as f:
        json.dump({"generated_at": timestamp, "status": "pending_review", "ideas": ideas}, f, indent=2)
    return out_path


if __name__ == "__main__":
    ideas = generate_ideas(n=5)
    path = save_ideas_for_review(ideas)
    print(f"Generated {len(ideas)} ideas -> {path}")
    print("Run `python pipeline.py --stage review-ideas` to approve one before building.")
