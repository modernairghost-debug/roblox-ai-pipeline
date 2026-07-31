"""
assets/image_gen.py

Generates thumbnail/icon/texture assets for an approved game concept.
Deliberately pluggable -- swap ENGINE below for whichever image model you want to use
(Gemini "Nano Banana", or anything else). Interface stays the same regardless of engine.

Requires: IMAGE_GEN_API_KEY environment variable, set per whichever engine you pick.
"""

import os
from dataclasses import dataclass

ENGINE = os.environ.get("IMAGE_GEN_ENGINE", "gemini-nano-banana")  # swap freely


@dataclass
class AssetRequest:
    game_title: str
    genre_pattern: str
    style_notes: str = ""


@dataclass
class AssetResult:
    thumbnail_path: str
    icon_path: str
    notes: str


def generate_assets(request: AssetRequest, out_dir: str) -> AssetResult:
    """
    STUB: real implementation should:
      1. Build a prompt from request.game_title + genre conventions
         (e.g. brainrot_meme -> bright/high-contrast/meme-referential;
               horror_survival -> dark/atmospheric/high-contrast silhouettes)
      2. Call the configured image engine's API
      3. Save outputs to out_dir, matching Roblox's thumbnail/icon size requirements
         (check current Roblox asset spec before going live -- these change)
      4. Return paths + any content-safety flags the engine returned

    Never call a real API here without IMAGE_GEN_API_KEY set via environment variable.
    """
    api_key = os.environ.get("IMAGE_GEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"IMAGE_GEN_API_KEY not set (engine={ENGINE}). Set it as an environment "
            "variable before running this stage live."
        )

    os.makedirs(out_dir, exist_ok=True)
    raise NotImplementedError(
        f"Wire up the actual {ENGINE} API call here. Interface (AssetRequest -> "
        "AssetResult) is stable -- swap the engine implementation freely."
    )


if __name__ == "__main__":
    req = AssetRequest(
        game_title="Example Game",
        genre_pattern="simulator",
        style_notes="bright, colorful, clear silhouette at small thumbnail size",
    )
    print(f"Would generate assets for: {req}")
    print("Set IMAGE_GEN_API_KEY and implement generate_assets() to run live.")
