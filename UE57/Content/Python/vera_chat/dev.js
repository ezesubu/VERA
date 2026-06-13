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
  // a thinking gap → the ASCII spinner shows here
  d({ type: "progress", agent: "inspect_level", msg: 'filter="floor" → 1 StaticMeshActor SM_MazeFloor' }, 2200);
  d({ type: "progress", agent: "run_ue_python", msg: "spawn lava plane + radial damage" }, 3200);
  d({
    type: "question", msg: "VERA wants to save the blueprint and the map.",
    args_preview: 'save_asset("/Game/VERA/BP_LavaHazard")\nsave_asset("/Game/Maps/ForestMaze")',
  }, 4000);
  d({
    type: "final", status: "success",
    msg: "Done. Added `BP_LavaHazard` at the center of the maze: an emissive lava plane and a `RadialDamage` of 250 dps.\n\n```python\nactor.set_actor_scale3d(unreal.Vector(35.5, 3.0, 0.2))\n```\n\nWant me to add Niagara spark particles?",
  }, 4800);
}

document.getElementById("demo-btn").addEventListener("click", demo);
window.addEventListener("load", devSeed);
