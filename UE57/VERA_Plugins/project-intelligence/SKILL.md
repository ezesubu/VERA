# Project Intelligence

VERA ships with project-intelligence tools that read the project straight from disk
(no editor bridge required). Use them to ground your reasoning in what actually
exists before you propose changes.

## Tools

- **`analyze_project`** — Get an overview of the project: which engine it targets,
  which plugins are active, which are available to enable, which are missing, and a
  high-level asset overview. Call this BEFORE reasoning about the project or
  proposing changes (e.g. adding features, enabling plugins, planning work), so your
  conclusions match reality instead of assumptions.

- **`find_asset`** — Locate an asset by name. Pass a (partial, case-insensitive)
  `name` and get back matching `/Game/...`-style content paths. Use this when you
  need to confirm an asset exists or find its exact path before referencing it.

## Notes

- Both tools reflect the **on-disk project** as it is right now. They do not need the
  editor to be running.
- Combine these findings with your memory: when `analyze_project` surfaces something
  notable (a missing plugin, an unusual engine version, a large asset library),
  remember it so you don't have to re-discover it every session.
