"""git_commit tool: stage EXPLICIT paths and commit (gated / destructive)."""
from __future__ import annotations

import os
import re
from typing import List, Tuple

from vera.agent.tool import Tool, ToolContext, ToolResult

from _git import GitError, current_branch, run_git

# Paths that must NEVER be staged: anything that looks like a secrets file.
# Matched against the basename and the full path, case-insensitive.
_SECRET_RE = re.compile(r"(^|[\\/])\.env(\.[^\\/]*)?$", re.IGNORECASE)

# Binary / game-asset extensions: allowed, but warned about (large/non-diffable).
_ASSET_EXTENSIONS = {".uasset", ".umap"}


def _looks_like_secret(path: str) -> bool:
    norm = path.replace("\\", "/")
    return bool(_SECRET_RE.search(norm))


def _classify(paths: List[str]) -> Tuple[List[str], List[str]]:
    """Return (secret_paths, asset_paths) found in the requested paths."""
    secrets, assets = [], []
    for p in paths:
        if _looks_like_secret(p):
            secrets.append(p)
        if os.path.splitext(p)[1].lower() in _ASSET_EXTENSIONS:
            assets.append(p)
    return secrets, assets


class GitCommitTool(Tool):
    name = "git_commit"
    description = (
        "Stage the EXPLICIT paths you provide and create a git commit. Use this "
        "to save your work once changes are reviewed. You MUST list every file "
        "to commit in `paths` -- this tool never stages everything (the repo "
        "holds large game assets and an .env with secrets). Write a clear "
        "conventional-commit message. This action writes history and asks the "
        "user for confirmation before it runs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message (prefer conventional commits, e.g. 'feat: ...').",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "REQUIRED. Explicit list of files/dirs to stage and commit. "
                    "Never use '.' or '*' -- name each path."
                ),
                "minItems": 1,
            },
        },
        "required": ["message", "paths"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        message = (args.get("message") or "").strip()
        paths = args.get("paths") or []

        if not message:
            return ToolResult("git_commit refused: a commit message is required.", is_error=True)
        if not isinstance(paths, list) or not paths:
            return ToolResult(
                "git_commit refused: `paths` must be a non-empty list of explicit "
                "paths. This tool never stages everything.",
                is_error=True,
            )
        paths = [str(p).strip() for p in paths if str(p).strip()]
        if not paths:
            return ToolResult("git_commit refused: no valid paths provided.", is_error=True)

        # Hard refusal: never let a secret-looking path be staged/committed.
        secrets, assets = _classify(paths)
        if any(p == "." or p == "*" or p.endswith("/*") for p in paths):
            return ToolResult(
                "git_commit refused: wildcard/'add all' paths are not allowed. "
                "List each file explicitly.",
                is_error=True,
            )
        if secrets:
            return ToolResult(
                "git_commit refused: these paths look like secret files and must "
                f"never be committed: {secrets}",
                is_error=True,
            )

        warning = ""
        if assets:
            warning = (
                "WARNING: committing binary/game-asset files (large, non-diffable): "
                f"{assets}\n"
            )

        try:
            # Stage only the requested paths.
            add_code, add_out, add_err = run_git(["add", "--", *paths])
            if add_code != 0:
                return ToolResult(
                    f"git add failed: {(add_err or add_out).strip() or 'unknown error'}",
                    is_error=True,
                )

            # Commit. With pathspec staging this only commits what we added.
            commit_code, commit_out, commit_err = run_git(["commit", "-m", message])
            if commit_code != 0:
                detail = (commit_err or commit_out).strip() or "unknown error"
                return ToolResult(f"git commit failed: {detail}", is_error=True)

            hash_code, hash_out, _ = run_git(["rev-parse", "--short", "HEAD"])
            commit_hash = hash_out.strip() if hash_code == 0 else "(unknown)"
            branch = current_branch()
        except GitError as exc:
            return ToolResult(f"git_commit failed: {exc}", is_error=True)

        return ToolResult(
            f"{warning}Committed {commit_hash} on branch {branch}.\n"
            f"Message: {message}\nStaged paths: {paths}"
        )
