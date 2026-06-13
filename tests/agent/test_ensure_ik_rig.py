# tests/agent/test_ensure_ik_rig.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_ik_rig import EnsureIKRigTool
import vera.agent.tools.ensure_ik_rig as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert EnsureIKRigTool().destructive is True


def test_encontrado_existente(monkeypatch):
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


def test_creado_nuevo(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"rig_path": "/Game/X/IK_VERA_SK_Y", "skeleton": "SK_Y",
         "chains": ["Spine"], "retarget_root": "pelvis", "created": True}))
    res = EnsureIKRigTool().execute({"skeleton_path": "/Game/X/SK_Y"}, ToolContext())
    assert res.is_error is False
    assert '"created": true' in res.content


def test_no_caracterizable_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "not_characterizable", "skeleton": "SK_SteampunkCar02",
         "detail": "no parece humanoide"}))
    res = EnsureIKRigTool().execute(
        {"skeleton_path": "/Game/S/SK_SteampunkCar02"}, ToolContext())
    assert res.is_error is True
    assert "not_characterizable" in res.content


def test_requiere_exactamente_una_ref(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = EnsureIKRigTool()
    assert t.execute({}, ToolContext()).is_error
    assert t.execute({"actor_name": "A", "skeleton_path": "/Game/B"},
                     ToolContext()).is_error


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = EnsureIKRigTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content
