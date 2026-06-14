# tests/agent/test_ensure_ik_rig.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_ik_rig import EnsureIKRigTool
import vera.agent.tools.ensure_ik_rig as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_is_destructive():
    assert EnsureIKRigTool().destructive is True


def test_found_existing(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"rig_path": "/Game/R/IK_Mannequin", "skeleton": "SK_Mannequin",
                    "chains": ["Spine", "LeftArm"], "retarget_root": "pelvis",
                    "created": False})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = EnsureIKRigTool().execute({"actor_name": "UE4Guy"}, ToolContext())
    assert res.is_error is False
    assert '"created": false' in res.content
    assert '"UE4Guy"' in captured["script"]


def test_created_new(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"rig_path": "/Game/X/IK_VERA_SK_Y", "skeleton": "SK_Y",
         "chains": ["Spine"], "retarget_root": "pelvis", "created": True}))
    res = EnsureIKRigTool().execute({"skeleton_path": "/Game/X/SK_Y"}, ToolContext())
    assert res.is_error is False
    assert '"created": true' in res.content


def test_not_characterizable_is_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "not_characterizable", "skeleton": "SK_SteampunkCar02",
         "detail": "does not look humanoid"}))
    res = EnsureIKRigTool().execute(
        {"skeleton_path": "/Game/S/SK_SteampunkCar02"}, ToolContext())
    assert res.is_error is True
    assert "not_characterizable" in res.content


def test_requires_exactly_one_ref(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = EnsureIKRigTool()
    assert t.execute({}, ToolContext()).is_error
    assert t.execute({"actor_name": "A", "skeleton_path": "/Game/B"},
                     ToolContext()).is_error


def test_bridge_down(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor closed")
    monkeypatch.setattr(mod, "send_json", boom)
    res = EnsureIKRigTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor closed" in res.content
