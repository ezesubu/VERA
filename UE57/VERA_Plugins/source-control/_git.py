"""Shared git helpers for the source-control plugin.

Files starting with `_` are ignored by the plugin tool loader (they are not
Tool modules), so this is a safe place for code shared across the git tools.

Everything here shells out to the real `git` binary via subprocess with an
explicit argv list (never shell=True) inside the resolved repository root.
"""
from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Tuple

# Cache the resolved repo root so we only call `git rev-parse` once per process.
_REPO_ROOT_CACHE: Optional[str] = None
_REPO_ROOT_RESOLVED = False

DEFAULT_PROJECT_ROOT = "E:/PCW/VERA/UE57"
GIT_TIMEOUT = 30


class GitError(Exception):
    """A git invocation failed in a way the tool should surface to the model."""


def _project_root() -> str:
    return os.environ.get("VERA_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)


def resolve_repo_root() -> str:
    """Find the git repository root, starting from VERA_PROJECT_ROOT.

    Runs `git rev-parse --show-toplevel` (the repo root may be the project root
    or any parent of it). The result is cached for the life of the process.

    Raises GitError if git is not installed or the project is not in a repo.
    """
    global _REPO_ROOT_CACHE, _REPO_ROOT_RESOLVED
    if _REPO_ROOT_RESOLVED:
        if _REPO_ROOT_CACHE is None:
            raise GitError(
                "Not inside a git repository (and none of the parents of "
                f"{_project_root()!r} are one)."
            )
        return _REPO_ROOT_CACHE

    _REPO_ROOT_RESOLVED = True
    start = _project_root()
    if not os.path.isdir(start):
        # Fall back to the current working directory if the configured root is
        # missing; git will still tell us whether that is a repo.
        start = os.getcwd()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        _REPO_ROOT_CACHE = None
        raise GitError(
            "git executable not found on PATH. Install git or fix PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        _REPO_ROOT_CACHE = None
        raise GitError("git rev-parse timed out while resolving the repo root.") from exc

    if proc.returncode != 0:
        _REPO_ROOT_CACHE = None
        msg = (proc.stderr or proc.stdout or "").strip()
        raise GitError(
            f"{start!r} is not inside a git repository: {msg or 'unknown error'}"
        )

    _REPO_ROOT_CACHE = proc.stdout.strip()
    return _REPO_ROOT_CACHE


def run_git(args: List[str]) -> Tuple[int, str, str]:
    """Run `git <args>` in the repo root. Returns (returncode, stdout, stderr).

    Raises GitError only for environment-level failures (git missing, not a
    repo, timeout). A non-zero git exit code is returned, not raised, so each
    tool can format its own error message.
    """
    repo = resolve_repo_root()
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {GIT_TIMEOUT}s.") from exc
    return proc.returncode, proc.stdout, proc.stderr


def current_branch() -> str:
    """Return the current branch name (or 'HEAD' when detached)."""
    code, out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if code == 0 else "(unknown)"
