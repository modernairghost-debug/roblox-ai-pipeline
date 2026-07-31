#!/usr/bin/env bash
#
# scripts/rebuild.sh
#
# Institutionalizes the "regenerate + rebuild from a clean slate" step that used to be
# done by hand (delete stale output, regenerate scripts, rojo build) whenever
# content_gen/luau_generator.py changes. Always do a full clean rebuild rather than
# generating on top of stale files -- that's what caught the TestWorldBuilder wiring gap
# during manual debugging. See STUDIO_TESTING_CHECKLIST.md for what to do in Studio
# after this script finishes.
#
# Usage: ./scripts/rebuild.sh [game-slug]
#   game-slug defaults to "rent-a-blorb" (the only concept with a real generator so far
#   -- see content_gen/luau_generator.py's generate_luau_for_idea()).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
GAME_SLUG="${1:-rent-a-blorb}"
GAME_TITLE="Rent-a-Blorb"
OUTPUT_DIR="$PROJECT_ROOT/output/$GAME_SLUG"
PLACE_FILE="RentABlorb.rbxlx"

cd "$PROJECT_ROOT"

echo "== 1/4: Locating rojo =="
if command -v rojo >/dev/null 2>&1; then
	ROJO_BIN="rojo"
elif [ -x "$HOME/.local/bin/rojo" ]; then
	ROJO_BIN="$HOME/.local/bin/rojo"
else
	echo "ERROR: rojo CLI not found on PATH or at ~/.local/bin/rojo." >&2
	echo "Install it from https://github.com/rojo-rbx/rojo/releases before running this script." >&2
	exit 1
fi
echo "Using: $("$ROJO_BIN" --version)"

echo
echo "== 2/4: Deleting stale generated output for '$GAME_SLUG' =="
rm -rf "$OUTPUT_DIR/src"
rm -f "$OUTPUT_DIR/default.project.json"
rm -f "$OUTPUT_DIR/$PLACE_FILE"
echo "Removed (if present): $OUTPUT_DIR/src, default.project.json, $PLACE_FILE"
echo "(BUILD_NOTES.md and BUILD_INSTRUCTIONS.md are left alone -- they're hand-maintained / regenerated separately.)"

echo
echo "== 3/4: Regenerating scripts via luau_generator.py + place_builder.py =="
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
	# shellcheck disable=SC1091
	source "$PROJECT_ROOT/venv/bin/activate"
fi

python3 - "$GAME_TITLE" "$GAME_SLUG" << 'PYEOF'
import json
import sys

sys.path.insert(0, ".")
from content_gen.luau_generator import generate_luau_for_idea
from assembly.place_builder import build_rojo_project

game_title, game_slug = sys.argv[1], sys.argv[2]

approved_dir = "review/approved"
idea = None
import os
for fname in sorted(os.listdir(approved_dir)):
    path = os.path.join(approved_dir, fname)
    try:
        data = json.load(open(path))
    except (json.JSONDecodeError, OSError):
        continue
    for candidate in data.get("ideas", []):
        if candidate.get("title") == game_title:
            idea = candidate
            break
    if idea:
        break

if idea is None:
    raise SystemExit(f"No approved idea titled {game_title!r} found under {approved_dir}/")

result = generate_luau_for_idea(idea)
print(f"Generated {len(result['scripts'])} scripts:")
for path in sorted(result["scripts"]):
    print(f"  {path}")

out_dir = build_rojo_project(result["scripts"], result["level_config"], out_dir=f"output/{game_slug}")
print(f"Wrote Rojo project to: {out_dir}")
PYEOF

echo
echo "== 4/4: Building the place file with rojo =="
cd "$OUTPUT_DIR"
"$ROJO_BIN" build -o "$PLACE_FILE"
echo "Built: $OUTPUT_DIR/$PLACE_FILE"

echo
echo "======================================================================"
echo " DONE. The place file on disk is fresh."
echo
echo " Now go CLOSE Roblox Studio fully (Cmd+Q, don't just close the tab) and"
echo " reopen $OUTPUT_DIR/$PLACE_FILE from Finder."
echo " Studio does not auto-reload a file that changed on disk while it was"
echo " open -- if you still have the old version open and hit Save, it will"
echo " silently overwrite this rebuild with the stale in-memory copy."
echo
echo " See STUDIO_TESTING_CHECKLIST.md at the project root for the full"
echo " re-open + verify checklist."
echo "======================================================================"
