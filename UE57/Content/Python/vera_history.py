"""VERA chat history — append-only JSONL, same schema as the protocol.
Stdlib only (runs in Unreal's embedded Python).
Assumptions: a SINGLE writer process (the editor window); best-effort durability (no fsync — a crash may lose the last few events)."""
import json
import os
from collections import deque


def append_event(path, event):
    """Appends an event as a JSON line. Creates the directory if missing."""
    path = os.fspath(path)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_recent(path, n=200):
    """Last n events. Corrupt lines are skipped (history never prevents the
    window from opening)."""
    path = os.fspath(path)
    if n <= 0:
        return []
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in deque(f, maxlen=n):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events
