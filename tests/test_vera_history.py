import json
import os
import sys

import pytest

# Importar desde la carpeta del proyecto UE (mismo patrón que test_vera_bridge)
BRIDGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "UE57", "Content", "Python")
sys.path.insert(0, BRIDGE_DIR)

import vera_history  # noqa: E402


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    vera_history.append_event(path, {"type": "user", "msg": "hola"})
    vera_history.append_event(path, {"type": "final", "status": "success", "msg": "done"})
    events = vera_history.load_recent(path)
    assert events == [
        {"type": "user", "msg": "hola"},
        {"type": "final", "status": "success", "msg": "done"},
    ]


def test_load_recent_caps_at_n(tmp_path):
    path = tmp_path / "h.jsonl"
    for i in range(300):
        vera_history.append_event(path, {"type": "user", "msg": str(i)})
    events = vera_history.load_recent(path, n=200)
    assert len(events) == 200
    assert events[-1]["msg"] == "299"


def test_load_missing_file_returns_empty(tmp_path):
    assert vera_history.load_recent(tmp_path / "no.jsonl") == []


def test_corrupt_lines_are_skipped(tmp_path):
    path = tmp_path / "h.jsonl"
    path.write_text('{"type":"user","msg":"ok"}\nBASURA NO JSON\n', encoding="utf-8")
    events = vera_history.load_recent(path)
    assert events == [{"type": "user", "msg": "ok"}]


def test_load_negative_n_returns_empty(tmp_path):
    path = tmp_path / "h.jsonl"
    vera_history.append_event(path, {"type": "user", "msg": "x"})
    assert vera_history.load_recent(path, n=-5) == []
