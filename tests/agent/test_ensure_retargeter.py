# tests/agent/test_ensure_retargeter.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_retargeter import EnsureRetargeterTool
import vera.agent.tools.ensure_retargeter as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert EnsureRetargeterTool().destructive is True


def test_encontrado_o_creado_devuelve_mapping(monkeypatch):
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


def test_rig_faltante_es_error_que_apunta_a_ensure_ik_rig(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "missing_ik_rig", "missing": ["target"],
         "detail": "usa ensure_ik_rig primero (un gate por asset)"}))
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True
    assert "ensure_ik_rig" in res.content


def test_cero_chains_mapeadas_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "no_chains_mapped", "created_then_deleted": True,
         "target_chains": ["Tentacle1"], "detail": "sin pares"}))
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True


def test_requiere_source_y_target(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = EnsureRetargeterTool()
    assert t.execute({"source": "A"}, ToolContext()).is_error
    assert t.execute({"target": "B"}, ToolContext()).is_error


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True
