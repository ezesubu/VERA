# tests/agent/test_ensure_retargeter.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_retargeter import EnsureRetargeterTool
import vera.agent.tools.ensure_retargeter as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_is_destructive():
    assert EnsureRetargeterTool().destructive is True


def test_found_or_created_returns_mapping(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"retargeter_path": "/Game/R/RTG_VERA_A_to_B",
                    "chain_mapping": [["LeftArm", "LeftArm"], ["Spine", "Spine"]],
                    "unmapped_chains": ["LeftPinky"], "created": True})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = EnsureRetargeterTool().execute(
        {"source": "/Game/A/SKM_Manny", "target": "UE4Guy"}, ToolContext())
    assert res.is_error is False
    assert "LeftArm" in res.content and "LeftPinky" in res.content
    assert '"/Game/A/SKM_Manny"' in captured["script"]
    assert '"UE4Guy"' in captured["script"]


def test_missing_rig_is_error_pointing_to_ensure_ik_rig(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "missing_ik_rig", "missing": ["target"],
         "detail": "use ensure_ik_rig first (one gate per asset)"}))
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True
    assert "ensure_ik_rig" in res.content


def test_zero_chains_mapped_is_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "no_chains_mapped", "created_then_deleted": True,
         "target_chains": ["Tentacle1"], "detail": "no pairs"}))
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True


def test_requires_source_and_target(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = EnsureRetargeterTool()
    assert t.execute({"source": "A"}, ToolContext()).is_error
    assert t.execute({"target": "B"}, ToolContext()).is_error


def test_bridge_down(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor closed")
    monkeypatch.setattr(mod, "send_json", boom)
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True
