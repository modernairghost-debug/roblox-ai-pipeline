"""
assembly/place_builder.py

Takes generated Luau scripts + level config and assembles a Rojo project (default
.project.json + src/) that can be built into a .rbxlx with `rojo build` and opened in
Roblox Studio. Roblox doesn't have a great headless "build a place from JSON" API, so
this targets the Rojo path (https://rojo.space) since it's scriptable outside Studio and
is the more CI-friendly long-term answer.

Scripts are keyed by their Rojo-relative path under `src/`, e.g.
"ServerScriptService/BlorbServer/Main.server.lua". The `.server.lua` / `.client.lua` /
plain `.lua` suffix convention is what Rojo uses to infer Script / LocalScript /
ModuleScript -- see https://rojo.space/docs/6.x/sync-details/ -- so this module doesn't
need to specify $className for individual files, only for the top-level service nodes.
"""

import json
import os

# Roblox services this pipeline knows how to place scripts under, and their real
# Instance ClassName (usually identical to the service name, listed for clarity).
SERVICE_CLASS_NAMES = {
    "ReplicatedStorage": "ReplicatedStorage",
    "ServerScriptService": "ServerScriptService",
    "ServerStorage": "ServerStorage",
    "StarterPlayer": "StarterPlayer",
    "StarterGui": "StarterGui",
    "StarterPack": "StarterPack",
    "Workspace": "Workspace",
}

# StarterPlayer doesn't run scripts directly -- they need to live in one of these actual
# child Instances, not a generic Folder, or Roblox won't run them for players.
STARTER_PLAYER_CONTAINERS = {
    "StarterPlayerScripts": "StarterPlayerScripts",
    "StarterCharacterScripts": "StarterCharacterScripts",
}


def _build_project_tree(scripts: dict, src_dir_name: str = "src") -> dict:
    """
    Groups script paths by top-level Roblox service (and, for StarterPlayer, the one
    required extra level of nesting) and builds the `tree` portion of a Rojo
    default.project.json. Each group gets a single $path pointing at its directory on
    disk -- Rojo mirrors the whole subtree (including nested Folders) from there.
    """
    services_seen = {}  # service_name -> set of StarterPlayer sub-containers seen (or None)

    for rel_path in scripts:
        parts = rel_path.split("/")
        service = parts[0]
        if service not in SERVICE_CLASS_NAMES:
            raise ValueError(
                f"Unknown top-level Roblox service {service!r} in script path {rel_path!r}. "
                f"Known services: {sorted(SERVICE_CLASS_NAMES)}"
            )

        sub_container = None
        if service == "StarterPlayer" and len(parts) > 1 and parts[1] in STARTER_PLAYER_CONTAINERS:
            sub_container = parts[1]

        services_seen.setdefault(service, set()).add(sub_container)

    tree = {"$className": "DataModel"}

    for service, sub_containers in services_seen.items():
        class_name = SERVICE_CLASS_NAMES[service]

        if sub_containers == {None}:
            tree[service] = {
                "$className": class_name,
                "$path": f"{src_dir_name}/{service}",
            }
            continue

        service_node = {"$className": class_name}
        for sub_container in sub_containers:
            if sub_container is None:
                continue
            service_node[sub_container] = {
                "$className": STARTER_PLAYER_CONTAINERS[sub_container],
                "$path": f"{src_dir_name}/{service}/{sub_container}",
            }
        tree[service] = service_node

    return tree


def build_rojo_project(scripts: dict, level_config: dict, out_dir: str, build_notes: str = None) -> str:
    """
    scripts: {relative_path_under_src: lua_code}, e.g.
        {"ServerScriptService/BlorbServer/Main.server.lua": "..."}
    level_config: metadata dict, must include "title"; may include
        "world_build_requirements" (list of strings describing what Studio still needs
        to build -- physical parts, CollectionService tags, etc).
    build_notes: optional markdown string written verbatim to BUILD_NOTES.md.

    Returns path to the generated project directory.
    """
    src_dir = os.path.join(out_dir, "src")

    for rel_path, code in scripts.items():
        full_path = os.path.join(src_dir, *rel_path.split("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(code)

    project_json = {
        "name": level_config.get("title", "UntitledGame"),
        "tree": _build_project_tree(scripts),
    }
    with open(os.path.join(out_dir, "default.project.json"), "w") as f:
        json.dump(project_json, f, indent=2)

    world_requirements = level_config.get("world_build_requirements", [])
    requirements_block = (
        "\n## World-building still needed in Studio\n\n"
        + "\n".join(f"- {item}" for item in world_requirements)
        + "\n"
        if world_requirements
        else ""
    )

    with open(os.path.join(out_dir, "BUILD_INSTRUCTIONS.md"), "w") as f:
        f.write(
            "# Build instructions\n\n"
            "1. Install Rojo: https://rojo.space/docs/installation/\n"
            "2. From this directory, run: `rojo build -o output.rbxlx`\n"
            "3. Open output.rbxlx in Roblox Studio to inspect before publishing\n"
            "4. Or use `rojo` + Open Cloud to push directly (see publish/ stage)\n"
            + requirements_block
        )

    if build_notes:
        with open(os.path.join(out_dir, "BUILD_NOTES.md"), "w") as f:
            f.write(build_notes)

    return out_dir


if __name__ == "__main__":
    example_scripts = {"ServerScriptService/Example/Main.server.lua": "-- placeholder\nprint('hello')"}
    example_config = {"title": "Example Game"}
    result_dir = build_rojo_project(
        example_scripts, example_config, out_dir="/tmp/example_rojo_project"
    )
    print(f"Rojo project scaffolded at: {result_dir}")
