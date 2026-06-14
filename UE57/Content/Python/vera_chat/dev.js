"use strict";
// Dev harness: injects fake events so the UI can be seen without Unreal.
// External (not inline) to run under the same CSP as production.

// Seed the picker and pick a local model on load, so the dock "lives".
function devSeed() {
  veraChat.dispatch({
    type: "models", provider: "LOCAL", status: "online",
    models: ["qwen3-coder-30b-a3b-instruct", "qwen2.5-coder-14b-instruct", "llama-3.3-70b-instruct"],
  });
  veraChat.dispatch({
    type: "commands", commands: [
      { name: "set_vibe", desc: "Instantly set the level's cinematic mood.", plugin: "Scene Vibe",
        args: [{ name: "mood", required: true, enum: ["cyberpunk", "horror", "golden_hour", "noir", "aztec_dusk"] }] },
      { name: "analyze_project", desc: "Scan the project (engine, plugins, assets).", plugin: "Project Intelligence", args: [] },
      { name: "find_asset", desc: "Find an asset by name.", plugin: "Project Intelligence", args: [{ name: "name", required: true, enum: null }] },
      { name: "recall", desc: "Search VERA's persistent memory.", plugin: "Memory", args: [{ name: "query", required: true, enum: null }] },
      { name: "git_status", desc: "Show working tree status and branch.", plugin: "Source Control", args: [] },
      { name: "inspect_level", desc: "Read the open level (actors, lights, meshes).", plugin: null, args: [] },
      { name: "run_ue_python", desc: "Run Python in the live editor.", plugin: null, args: [{ name: "code", required: true, enum: null }] },
      { name: "capture_actor", desc: "Isolate and screenshot an actor.", plugin: null, args: [{ name: "actor_name", required: true, enum: null }] },
    ],
  });
  veraChat.dispatch({
    type: "plugins", plugins: [
      { id: "perforce-pipeline", name: "Perforce Pipeline", version: "1.0", author: "Studio",
        description: "Export and submit assets through our Perforce flow.",
        enabled: true, tools: ["export_p4", "submit_changelist"], has_skill: true },
      { id: "aztec-naming", name: "Aztec Naming", version: "0.2", author: "Eze",
        description: "Asset naming conventions for the PCW project.",
        enabled: false, tools: [], has_skill: true },
    ],
  });
}

function demo() {
  const d = (e, ms) => setTimeout(() => veraChat.dispatch(e), ms);
  d({ type: "status", online: true, version: "UE 5.7" }, 0);
  d({ type: "user", msg: "Add a lava hazard to the forest maze that damages the player" }, 200);
  // narration + tool calls → you SEE what VERA is doing, not just thinking
  d({ type: "say", msg: "I'll add a lava hazard. First let me find the maze floor." }, 1300);
  d({ type: "tool_use", agent: "inspect_level", input: { filter: "floor" } }, 1700);
  d({ type: "progress", agent: "inspect_level", msg: "1 StaticMeshActor → SM_MazeFloor (4200×4200)" }, 2200);
  d({ type: "say", msg: "Found it. Now I'll spawn an emissive lava plane and a radial-damage volume on top." }, 2900);
  d({ type: "tool_use", agent: "run_ue_python", input: { code: "import unreal\\n# spawn lava plane + RadialDamage 250dps" } }, 3300);
  d({ type: "progress", agent: "run_ue_python", msg: "spawned BP_LavaHazard · DamageVolume 250 dps" }, 3900);
  d({
    type: "question", msg: "VERA wants to save the blueprint and the map.",
    args_preview: 'save_asset("/Game/VERA/BP_LavaHazard")\nsave_asset("/Game/Maps/ForestMaze")',
  }, 4500);
  d({
    type: "final", status: "success",
    msg: "Done. Added `BP_LavaHazard` at the center of the maze: an emissive lava plane and a `RadialDamage` of 250 dps.\n\n```python\nactor.set_actor_scale3d(unreal.Vector(35.5, 3.0, 0.2))\n```\n\nWant me to add Niagara spark particles?",
  }, 5300);
}

document.getElementById("demo-btn").addEventListener("click", demo);
window.addEventListener("load", devSeed);
