"""Recipe book for the Local IQ plugin.

Lets VERA save a proven sequence of steps for a task and find it again later, so a
small local model can replay a working path instead of reasoning from scratch every
time. Distinct from the Memory plugin: Memory stores *facts*, this stores *procedures*
(task -> ordered steps).

Storage is a JSONL file inside the plugin folder (``local-iq/recipes.jsonl``), so the
plugin is self-contained and portable. Robust to a missing / empty / corrupt file.
"""
from __future__ import annotations

import datetime
import json
import os
import threading
import uuid

from vera.agent.tool import Tool, ToolContext, ToolResult

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../local-iq
_STORE_PATH = os.path.join(_PLUGIN_DIR, "recipes.jsonl")
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return f"rcp-{uuid.uuid4().hex[:8]}"


def _load() -> list:
    """Read every valid record. Missing/empty/corrupt file -> []. Never raises."""
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("id"):
            out.append(obj)
    return out


def _append(record: dict) -> None:
    with open(_STORE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _norm_steps(raw) -> list:
    """Coerce steps into a clean list[str] (accepts a single string too)."""
    if not raw:
        return []
    if isinstance(raw, str):
        # split on newlines if a single multi-line string was passed
        parts = [s.strip(" -\t") for s in raw.splitlines()]
        return [s for s in parts if s]
    return [str(s).strip() for s in raw if str(s).strip()]


def _norm_tags(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(t).strip() for t in raw if str(t).strip()]


def _fmt(rec: dict) -> str:
    steps = rec.get("steps") or []
    tags = rec.get("tags") or []
    tag_str = f"  [tags: {', '.join(tags)}]" if tags else ""
    head = f"- {rec.get('id')} | {rec.get('task', '')}{tag_str}"
    body = "\n".join(f"    {i + 1}. {s}" for i, s in enumerate(steps))
    return f"{head}\n{body}" if body else head


class SaveRecipeTool(Tool):
    name = "save_recipe"
    description = (
        "Save a PROVEN sequence of steps for a task so it can be replayed later. Call "
        "this after you successfully complete a multi-step task, so a future session (or "
        "a smaller model) can reuse the working path instead of reasoning from scratch. "
        "Store concrete, ordered steps. Safe append (no confirmation needed)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Short description of what the recipe accomplishes.",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered, concrete steps that worked.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to make the recipe easier to find.",
            },
        },
        "required": ["task", "steps"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        task = (args.get("task") or "").strip()
        steps = _norm_steps(args.get("steps"))
        if not task:
            return ToolResult("Cannot save recipe: 'task' is empty.", is_error=True)
        if not steps:
            return ToolResult("Cannot save recipe: 'steps' is empty.", is_error=True)
        record = {
            "id": _new_id(),
            "task": task,
            "steps": steps,
            "tags": _norm_tags(args.get("tags")),
            "created": _now(),
        }
        try:
            with _LOCK:
                _append(record)
        except OSError as e:
            return ToolResult(f"Failed to save recipe: {e}", is_error=True)
        return ToolResult(f"Saved recipe ({record['id']}) for: {task} ({len(steps)} steps)")


class FindRecipeTool(Tool):
    name = "find_recipe"
    description = (
        "Search the recipe book for a proven approach to a task. Call this at the START "
        "of a task to see if you've already solved something like it. Case-insensitive "
        "substring match over the recipe task and tags; returns the most recent matches "
        "with their steps. Read-only."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Substring to search for across recipe tasks and tags.",
            },
            "limit": {
                "type": "integer",
                "description": "Max number of recipes to return (default 5).",
            },
        },
        "required": ["query"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = (args.get("query") or "").strip().lower()
        try:
            limit = int(args.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        if limit <= 0:
            limit = 5
        records = sorted(_load(), key=lambda r: r.get("created", ""), reverse=True)
        if query:
            records = [
                r for r in records
                if query in (r.get("task", "") + " " + " ".join(r.get("tags") or [])).lower()
            ]
        if not records:
            return ToolResult(f"No recipes match '{args.get('query', '')}'.")
        shown = records[:limit]
        header = f"Found {len(records)} recipe(s), showing {len(shown)}:"
        body = "\n".join(_fmt(r) for r in shown)
        return ToolResult(f"{header}\n{body}")
