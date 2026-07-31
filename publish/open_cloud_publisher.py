"""
publish/open_cloud_publisher.py

Publishes an APPROVED, ASSEMBLED game to Roblox via the Open Cloud API. This stage
should only ever run on something that passed the review/approved/ gate -- pipeline.py
enforces that, don't bypass it by calling this module directly on unreviewed content.

Requires:
  - ROBLOX_OPEN_CLOUD_API_KEY environment variable
  - ROBLOX_UNIVERSE_ID environment variable (target experience)

Docs to check before wiring this up live (API details change):
  https://create.roblox.com/docs/cloud/open-cloud
"""

import os

import requests

OPEN_CLOUD_BASE = "https://apis.roblox.com"


def publish_place(place_file_path: str, ai_disclosure_note: str) -> dict:
    """
    STUB: real implementation should:
      1. Confirm the source idea/build actually passed human review (check
         review/approved/ record, don't trust caller blindly)
      2. Upload the place file via Open Cloud's place publish endpoint
      3. Set experience metadata including an honest description of AI involvement,
         matching Roblox's content policies -- don't omit or obscure this
      4. Log the publish (game id, timestamp, source idea file) to logs/ for tracking
      5. Return the published place/universe details

    Never call this with a real API key without having read Roblox's current Open
    Cloud + AI content policy docs first -- these are the parts most likely to have
    changed since this scaffold was written.
    """
    api_key = os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY")
    universe_id = os.environ.get("ROBLOX_UNIVERSE_ID")

    if not api_key or not universe_id:
        raise RuntimeError(
            "ROBLOX_OPEN_CLOUD_API_KEY and ROBLOX_UNIVERSE_ID must be set as environment "
            "variables before running this stage live."
        )

    raise NotImplementedError(
        "Wire up the actual Open Cloud publish call here once you've confirmed the "
        "current API endpoint/auth flow in Roblox's docs."
    )


if __name__ == "__main__":
    print("This stage requires an approved, assembled game and real Open Cloud credentials.")
    print("Not runnable standalone in the current scaffold state.")
