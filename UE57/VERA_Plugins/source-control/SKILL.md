# Source control (git)

VERA can use source control to **save its own work**. Four git tools are
available: `git_status`, `git_diff`, `git_log`, and `git_commit`. They operate
directly on the project's git repository via the `git` command line.

## How to use them

1. **Always check `git_status` first.** Before committing anything, look at the
   branch you are on and the exact list of changed/untracked files. Never commit
   blind.
2. **Review with `git_diff`** when you want to confirm what actually changed in a
   file (pass `path` to focus on one file, `staged=true` to see what is staged).
3. **Commit with EXPLICIT paths only.** `git_commit` requires a `paths` list and
   stages only those paths. There is **no "add all"** -- this repo contains large
   game assets (`.uasset`, `.umap`) and an `.env` file with secrets that must
   **never** be committed. Name every file you intend to commit.
   - `.env`-style paths are hard-refused.
   - `.uasset` / `.umap` are allowed but warned about; avoid committing them
     unless explicitly asked.
4. **Write clear conventional-commit messages** (e.g. `feat: ...`, `fix: ...`,
   `docs: ...`), matching the style you see in `git_log`.
5. **Prefer a `feature/*` branch.** The user's current working branch is
   `feature/ui-redesign`; keep VERA's commits on a feature branch, not on `main`.

## Safety

`git_commit` is **destructive** (it writes history) and is **gated** -- it asks
the user for confirmation before running. The read-only tools (`git_status`,
`git_diff`, `git_log`) run without confirmation.
