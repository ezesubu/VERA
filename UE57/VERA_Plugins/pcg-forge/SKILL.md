# PCG Forge

Automate Procedural Content Generation (PCG) inside Unreal Engine using the `unreal` Python API.

## When to use
- The user asks to scatter meshes, populate a volume, or automate procedural generation using PCG.
- The user mentions "PCG", "scatter", or filling an area procedurally.

## How
Call `build_pcg_graph`:
- `graph_path` (required) — e.g. `/Game/PCG/MyGraph`.

It loads the graph, adds a `PCGSurfaceSamplerSettings` node, a `PCGStaticMeshSpawnerSettings` node, wires them correctly using `add_edge_to` (taking into account the hidden `"Surface"` and `"In"` pin names), and assigns the appropriate static meshes bypassing the `PCGComponent` property protections.

Adding extra PCG nodes visually isn't fully supported by the basic Python API without explicit positioning and pin assignments, so this skill provides the essential blockout for surface scattering.
