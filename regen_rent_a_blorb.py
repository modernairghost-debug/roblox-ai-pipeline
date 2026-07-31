"""
One-off regeneration script -- mirrors what the previous session ran manually to produce
output/rent-a-blorb/ the first time (see PROJECT_STATUS.md section 3, step 4-6).
Re-reads the approved Rent-a-Blorb idea, regenerates the 13 Luau scripts from the
(now-fixed) content_gen/luau_generator.py, and rewrites the Rojo project under
output/rent-a-blorb/. Does NOT touch BUILD_NOTES.md (build_notes=None -> left alone).

Run from the project root:
    python3 regen_rent_a_blorb.py
"""

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from content_gen.luau_generator import generate_luau_for_idea
from assembly.place_builder import build_rojo_project

approved_files = sorted(glob.glob(os.path.join(ROOT, "review", "approved", "ideas_*.json")))
if not approved_files:
    raise SystemExit("No approved ideas file found under review/approved/")

# There may be more than one approved batch over time -- search all of them for the
# Rent-a-Blorb idea rather than assuming it's in the newest file.
idea = None
source_file = None
for path in approved_files:
    with open(path) as f:
        payload = json.load(f)
    ideas = payload.get("ideas", payload) if isinstance(payload, dict) else payload
    for candidate in ideas:
        if candidate.get("title") == "Rent-a-Blorb":
            idea = candidate
            source_file = path
            break
    if idea:
        break

if not idea:
    raise SystemExit("Could not find a 'Rent-a-Blorb' idea in any review/approved/ideas_*.json file")

print(f"Using idea from: {source_file}")

result = generate_luau_for_idea(idea)
out_dir = os.path.join(ROOT, "output", "rent-a-blorb")
build_rojo_project(result["scripts"], result["level_config"], out_dir=out_dir)

print(f"Regenerated {len(result['scripts'])} scripts into {out_dir}")
for path in sorted(result["scripts"]):
    print(f"  {path}")
