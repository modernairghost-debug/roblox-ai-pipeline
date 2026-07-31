"""
research/trending_scraper.py

Pulls current Roblox trend data. Right now this loads the seed snapshot; the TODOs
mark where to wire in live sources once you're running this with real network access
(e.g. in Claude Code, not this sandbox).

Candidate live sources (check each one's ToS/API terms before scraping):
  - RoMonitor Stats  (https://romonitorstats.com) - has some public data/API
  - Rolimon's        (https://www.rolimons.com) - has a documented public API for some data
  - Roblox's own charts / Discover page (official, but no public "trending" API as of writing;
    may require polite scraping with rate limiting, or manual export)

Design: keep this module's OUTPUT SHAPE stable (see `get_trending_snapshot()` return
format) even if you swap out where the data comes from underneath.
"""

import json
import os
from datetime import datetime, timezone

SEED_PATH = os.path.join(os.path.dirname(__file__), "known_trends_seed.json")


def load_seed_snapshot() -> dict:
    with open(SEED_PATH, "r") as f:
        return json.load(f)


def get_trending_snapshot(live: bool = False) -> dict:
    """
    Returns a dict shaped like known_trends_seed.json.

    If live=True, this SHOULD hit real sources instead of the seed file.
    Currently raises NotImplementedError to make it obvious this hasn't been wired up yet
    -- fill this in once you have network access and have picked a data source.
    """
    if live:
        raise NotImplementedError(
            "Live trend fetching not wired up yet. Pick a source (RoMonitor / Rolimon's / "
            "manual chart export), implement _fetch_live(), and swap this flag on."
        )
    snapshot = load_seed_snapshot()
    snapshot["_meta"]["fetched_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["_meta"]["source"] = "seed_file"
    return snapshot


def _fetch_live() -> dict:
    """
    TODO: implement live fetching. Suggested shape to preserve:
    {
      "_meta": {"fetched_at": ..., "source": ...},
      "top_games_snapshot": [{"name", "genre", "why_it_works"}, ...],
      "genre_patterns": {genre_key: {"growth_shape", "core_loop", "risk"}, ...},
      "cross_cutting_success_factors": [str, ...]
    }
    """
    raise NotImplementedError


if __name__ == "__main__":
    data = get_trending_snapshot(live=False)
    print(json.dumps(data, indent=2))
