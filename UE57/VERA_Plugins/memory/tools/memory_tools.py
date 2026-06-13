"""Persistent-memory tools shipped by the Memory studio plugin.

VERA gains durable, cross-conversation memory: a small JSONL store that lives
inside the plugin's own folder (``VERA_Plugins/memory/memories.jsonl``), so the
plugin is self-contained and portable.

Tools contributed:
- ``remember``      append a memory record (safe, non-destructive)
- ``recall``        substring search over content + tags (read-only)
- ``list_memories`` dump all memories, most recent first (read-only)
- ``forget``        delete one memory by id (destructive → confirmation gate)

Storage is robust to a missing / empty / corrupt file: any unreadable line is
skipped and a missing file is treated as "no memories" rather than an error.
"""
from __future__ import annotations

import datetime
import json
import os
import threading
import uuid

from vera.agent.tool import Tool, ToolContext, ToolResult

# Store lives next to this module: VERA_Plugins/memory/memories.jsonl
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))          # .../memory/tools
_STORE_PATH = os.path.join(os.path.dirname(_PLUGIN_DIR), "memories.jsonl")

# One-writer guard for read-all/rewrite (forget) and appends in-process.
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    """Short, collision-resistant id, e.g. ``mem-1a2b3c4d``."""
    return f"mem-{uuid.uuid4().hex[:8]}"


def _load() -> list:
    """Read every valid record. Missing/empty/corrupt file → []. Never raises.

    Corrupt individual lines are skipped so one bad write can't hide the rest.
    """
    try:
        with open(_STORE_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return []
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue  # skip a corrupt line, keep going
        if isinstance(obj, dict) and obj.get("id"):
            records.append(obj)
    return records


def _append(record: dict) -> None:
    """Append one record as a JSONL line (atomic-enough for one writer)."""
    with open(_STORE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _rewrite(records: list) -> None:
    """Replace the whole store with ``records`` (used by forget)."""
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _sorted_recent(records: list) -> list:
    """Most recent first. Falls back gracefully if a record lacks ``created``."""
    return sorted(records, key=lambda r: r.get("created", ""), reverse=True)


def _fmt(rec: dict) -> str:
    tags = rec.get("tags") or []
    tag_str = f" [tags: {', '.join(tags)}]" if tags else ""
    return f"- {rec.get('id')} ({rec.get('created', '?')}): {rec.get('content', '')}{tag_str}"


def _norm_tags(raw) -> list:
    """Coerce the optional ``tags`` arg into a clean list[str]."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(t).strip() for t in raw if str(t).strip()]


class RememberTool(Tool):
    name = "remember"
    description = (
        "Save a durable fact to VERA's persistent memory so it survives across "
        "conversations. Use this whenever you learn something worth keeping: project "
        "conventions, the user's preferences, decisions made, naming schemes, paths, or "
        "gotchas. Keep each memory short and factual; do NOT store transient chat. "
        "This is a safe append (no confirmation needed)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact to remember, stated concisely.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to make the memory easier to recall later.",
            },
        },
        "required": ["content"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        content = (args.get("content") or "").strip()
        if not content:
            return ToolResult("Cannot remember: 'content' is empty.", is_error=True)
        record = {
            "id": _new_id(),
            "content": content,
            "tags": _norm_tags(args.get("tags")),
            "created": _now(),
        }
        try:
            with _LOCK:
                _append(record)
        except OSError as e:
            return ToolResult(f"Failed to write memory: {e}", is_error=True)
        return ToolResult(f"Remembered ({record['id']}): {content}")


class RecallTool(Tool):
    name = "recall"
    description = (
        "Search VERA's persistent memory for facts learned in earlier conversations. "
        "Call this at the START of a task that might relate to prior context (project "
        "conventions, user preferences, past decisions) to check what you already know. "
        "Matches a case-insensitive substring against memory content and tags; returns "
        "the most recent matches first. Read-only."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Substring to search for across memory content and tags.",
            },
            "limit": {
                "type": "integer",
                "description": "Max number of matches to return (default 5).",
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
        records = _sorted_recent(_load())
        if not query:
            matches = records
        else:
            matches = []
            for rec in records:
                haystack = (rec.get("content", "") + " " + " ".join(rec.get("tags") or [])).lower()
                if query in haystack:
                    matches.append(rec)
        if not matches:
            return ToolResult(f"No memories match '{args.get('query', '')}'.")
        shown = matches[:limit]
        header = f"Found {len(matches)} match(es) for '{args.get('query', '')}', showing {len(shown)}:"
        body = "\n".join(_fmt(r) for r in shown)
        return ToolResult(f"{header}\n{body}")


class ListMemoriesTool(Tool):
    name = "list_memories"
    description = (
        "List everything in VERA's persistent memory, most recent first. Use this to "
        "review what VERA currently knows. Read-only; capped at 50 entries."
    )
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    _CAP = 50

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        records = _sorted_recent(_load())
        if not records:
            return ToolResult("No memories stored yet.")
        shown = records[: self._CAP]
        body = "\n".join(_fmt(r) for r in shown)
        note = ""
        if len(records) > self._CAP:
            note = f"\n(Showing the {self._CAP} most recent of {len(records)} total — truncated.)"
        return ToolResult(f"{len(records)} memory(ies) stored:\n{body}{note}")


class ForgetTool(Tool):
    name = "forget"
    description = (
        "Delete one memory from VERA's persistent store by its id (e.g. 'mem-1a2b3c4d'). "
        "Use this when a stored memory is wrong or no longer relevant. Destructive: it "
        "removes the record permanently."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The id of the memory to delete, as shown by recall/list_memories.",
            }
        },
        "required": ["id"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        target = (args.get("id") or "").strip()
        if not target:
            return ToolResult("Cannot forget: 'id' is empty.", is_error=True)
        try:
            with _LOCK:
                records = _load()
                kept = [r for r in records if r.get("id") != target]
                if len(kept) == len(records):
                    return ToolResult(f"Memory '{target}' not found.")
                _rewrite(kept)
        except OSError as e:
            return ToolResult(f"Failed to update memory store: {e}", is_error=True)
        return ToolResult(f"Forgot memory '{target}'.")
