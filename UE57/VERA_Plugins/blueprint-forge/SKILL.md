# Blueprint Forge

Create Actor Blueprints with the `unreal` Python Graph API — programmatically,
no clicking and no perception.

## When to use
- The user asks to create a Blueprint class ("make a BP_SpikeTrap", "create a
  pickup blueprint with a static mesh and a box collision").

## How
Call `create_blueprint`:
- `bp_name` (required) — e.g. `BP_SpikeTrap`.
- `package_path` — content path, default `/Game/VERA_Autogen`.
- `parent_class` — unreal class name, default `Actor`.
- `components` — optional list under a scene root: `static_mesh`,
  `box_collision`, `sphere_collision`, `capsule_collision`, `point_light`.

The asset is created, components added, compiled and saved. It asks for
confirmation first (it writes a new asset into the project).

Adding graph **nodes/logic** is not exposed by the Python API — for that, build
the components here and tell the user which nodes to wire, or script behaviour on
a parent C++/Python class instead.
