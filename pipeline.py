"""
pipeline.py

Orchestrates the stages. Human review gates between ideate->build and build->publish
are enforced here, not optional -- EXCEPT for `--stage daily`, which is a deliberate,
explicitly-opted-into exception for unattended/scheduled runs: it generates exactly ONE
idea (not several to silently pick from) and auto-promotes only that one, so there's no
unsupervised "pick the best of many" judgment call, but there's also no dashboard click
blocking a daily cadence. `--stage build`/`--stage publish` on their own still require the
normal review-ideas / review-build gates. See README.md for the full stage list.
"""

import argparse
import glob
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(__file__))

from ideation.idea_generator import generate_ideas, save_ideas_for_review  # noqa: E402
from research.trending_scraper import get_trending_snapshot  # noqa: E402
from content_gen.luau_generator import generate_luau_for_idea, lint_scripts  # noqa: E402
from assembly.place_builder import build_rojo_project  # noqa: E402

ROOT = os.path.dirname(__file__)
APPROVED_DIR = os.path.join(ROOT, "review", "approved")
PENDING_DIR = os.path.join(ROOT, "review", "pending")
OUTPUT_DIR = os.path.join(ROOT, "output")

# Pinned so a daily unattended run doesn't silently pick up a breaking Rojo release.
ROJO_VERSION = "7.4.4"
ROJO_BIN_DIR = os.path.join(ROOT, ".rojo_bin")


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled-game"


def _iter_approved_ideas():
    """Yields (idea_dict, source_file_path) for every idea across every approved file."""
    if not os.path.isdir(APPROVED_DIR):
        return
    for path in sorted(glob.glob(os.path.join(APPROVED_DIR, "*.json"))):
        with open(path) as f:
            payload = json.load(f)
        ideas = payload.get("ideas", payload) if isinstance(payload, dict) else payload
        for idea in ideas:
            yield idea, path


def _find_approved_idea(idea_title: str = None):
    all_ideas = list(_iter_approved_ideas())
    if not all_ideas:
        return None

    if idea_title:
        for idea, path in all_ideas:
            if idea.get("title") == idea_title:
                return idea
        raise ValueError(f"No approved idea titled {idea_title!r}. Approved: {[i.get('title') for i, _ in all_ideas]}")

    if len(all_ideas) == 1:
        return all_ideas[0][0]

    titles = [i.get("title") for i, _ in all_ideas]
    raise ValueError(
        f"{len(all_ideas)} approved ideas found, ambiguous which to build: {titles}. "
        "Pass --idea \"<title>\" to pick one."
    )


def _ensure_rojo_binary() -> str:
    """
    Returns a path to a working `rojo` executable -- the one already on PATH if present
    (e.g. on a Mac where it was installed manually), otherwise downloads a pinned release
    into .rojo_bin/ so this also works unattended in a fresh cloud sandbox with no prior
    setup. Linux-only download target; on macOS with rojo missing from PATH, this raises
    and tells you to install it instead (matches BUILD_INSTRUCTIONS.md).
    """
    on_path = shutil.which("rojo")
    if on_path:
        return on_path

    local_bin = os.path.join(ROJO_BIN_DIR, "rojo")
    if os.path.isfile(local_bin):
        return local_bin

    if sys.platform != "linux":
        raise RuntimeError(
            "rojo not found on PATH and auto-download is only implemented for Linux "
            "(this looks like macOS) -- install the CLI manually, see BUILD_INSTRUCTIONS.md."
        )

    os.makedirs(ROJO_BIN_DIR, exist_ok=True)
    url = f"https://github.com/rojo-rbx/rojo/releases/download/v{ROJO_VERSION}/rojo-{ROJO_VERSION}-linux-x86_64.zip"
    zip_path = os.path.join(ROJO_BIN_DIR, "rojo.zip")
    print(f"rojo not found -- downloading v{ROJO_VERSION} for Linux...")
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(ROJO_BIN_DIR)
    os.remove(zip_path)
    os.chmod(local_bin, os.stat(local_bin).st_mode | stat.S_IEXEC)
    return local_bin


def stage_research():
    snapshot = get_trending_snapshot(live=False)
    print(f"Loaded trend snapshot ({snapshot['_meta'].get('source', 'unknown')}):")
    for g in snapshot["top_games_snapshot"]:
        print(f"  - {g['name']} ({g['genre']}): {g['why_it_works']}")
    return snapshot


def stage_ideate(n: int = 5):
    ideas = generate_ideas(n=n)
    path = save_ideas_for_review(ideas)
    print(f"Generated {len(ideas)} ideas -> {path}")
    print("Run with --stage review-ideas (or `python review/dashboard.py`) to approve one.")
    return ideas, path


def stage_review_ideas():
    print("Launching review dashboard at http://localhost:5050 ...")
    os.system(f"{sys.executable} {os.path.join('review', 'dashboard.py')}")


def stage_build(idea_title: str = None):
    if not os.path.isdir(APPROVED_DIR) or not os.listdir(APPROVED_DIR):
        print("Nothing approved yet. Run --stage review-ideas first and approve a concept.")
        return None

    idea = _find_approved_idea(idea_title)
    print(f"Building: {idea['title']} ({idea.get('genre_pattern', '?')})")

    result = generate_luau_for_idea(idea)
    findings = lint_scripts(result["scripts"])
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    for f in findings:
        print(f"  [{f['severity'].upper()}] {f['script']}: {f['message']}")

    if errors:
        print(f"BUILD ABORTED: {len(errors)} lint error(s) -- not handing this to rojo build.")
        return None

    slug = _slugify(idea["title"])
    out_dir = os.path.join(OUTPUT_DIR, slug)
    build_rojo_project(result["scripts"], result["level_config"], out_dir=out_dir)
    print(f"Wrote Rojo project to {out_dir} ({len(result['scripts'])} scripts"
          f"{f', {len(warnings)} lint warning(s)' if warnings else ''})")

    rojo_bin = _ensure_rojo_binary()
    rbxlx_path = os.path.join(out_dir, f"{slug}.rbxlx")
    proc = subprocess.run(
        [rojo_bin, "build", "-o", rbxlx_path],
        cwd=out_dir, capture_output=True, text=True,
    )
    print(proc.stdout.strip())
    if proc.returncode != 0:
        print(f"rojo build FAILED:\n{proc.stderr}")
        return None

    print(f"Built {rbxlx_path} -- open it in Roblox Studio to review before publishing.")
    return rbxlx_path


def stage_daily(n_ideas: int = 1):
    """
    Unattended daily pipeline: research -> ideate(n=1) -> auto-promote straight to
    approved/ (no dashboard click -- see module docstring for why this is an explicit,
    scoped exception to the normal human gate) -> build -> lint -> rojo build. Never
    touches publish/ -- that gate stays fully manual regardless.
    """
    print("=== stage: research ===")
    stage_research()

    print("\n=== stage: ideate ===")
    ideas, pending_path = stage_ideate(n=n_ideas)
    idea = ideas[0]

    print(f"\n=== auto-promoting {idea['title']!r} straight to approved/ (daily mode, no dashboard gate) ===")
    os.makedirs(APPROVED_DIR, exist_ok=True)
    approved_path = os.path.join(APPROVED_DIR, os.path.basename(pending_path))
    shutil.move(pending_path, approved_path)

    print("\n=== stage: build ===")
    rbxlx_path = stage_build(idea_title=idea["title"])

    if rbxlx_path:
        print(f"\nDAILY RUN OK: {idea['title']!r} built to {rbxlx_path}. "
              "Not published -- review in Studio and publish manually if you like it.")
    else:
        print(f"\nDAILY RUN FAILED at build stage for {idea['title']!r}. See lint findings above.")
    return rbxlx_path


def stage_review_build():
    print("STUB: same review-dashboard pattern as review-ideas, but gating build output before publish.")


def stage_publish():
    print(
        "STUB: would call publish/open_cloud_publisher.py on a build that passed review-build. "
        "Refusing to implement auto-publish without an explicit approved build present."
    )


STAGES = {
    "research": stage_research,
    "ideate": stage_ideate,
    "review-ideas": stage_review_ideas,
    "build": stage_build,
    "review-build": stage_review_build,
    "publish": stage_publish,
    "daily": stage_daily,
}


def main():
    parser = argparse.ArgumentParser(description="Roblox AI game pipeline")
    parser.add_argument("--stage", choices=list(STAGES.keys()) + ["all"], required=True)
    parser.add_argument("--n", type=int, default=5, help="number of ideas to generate (ideate stage)")
    parser.add_argument("--idea", type=str, default=None, help="approved idea title to build (build stage; auto-picked if only one approved)")
    args = parser.parse_args()

    if args.stage == "all":
        stage_research()
        stage_ideate(n=args.n)
        print("\nStopped after ideation -- build/publish always require explicit human review stages.")
        return

    if args.stage == "ideate":
        STAGES[args.stage](n=args.n)
    elif args.stage == "build":
        STAGES[args.stage](idea_title=args.idea)
    elif args.stage == "daily":
        STAGES[args.stage](n_ideas=args.n if args.n != 5 else 1)
    else:
        STAGES[args.stage]()


if __name__ == "__main__":
    main()
