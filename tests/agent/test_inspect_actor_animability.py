# tests/agent/test_inspect_actor_animability.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.inspect_actor_animability import InspectActorAnimabilityTool
import vera.agent.tools.inspect_actor_animability as mod
from vera.tools.ue_conn import UEConnectionError


def test_es_read_only():
    assert InspectActorAnimabilityTool().destructive is False


def test_skeletal_con_anims(monkeypatch):
    data = {"actor": "VERA_Manny", "kind": "skeletal", "skeleton": "SK_Mannequin",
            "compatible_anims": ["MM_Idle"], "total_compatible_anims": 1,
            "current_anim_mode": "AnimationMode.ANIMATION_BLUEPRINT", "notes": ""}
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["port"] = port
        captured["script"] = payload["script"]
        return {"success": True, "output": json.dumps(data)}

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = InspectActorAnimabilityTool().execute(
        {"actor_name": "VERA_Manny"}, ToolContext(bridge_port=9878))
    assert res.is_error is False
    assert "SK_Mannequin" in res.content
    assert "MM_Idle" in res.content
    assert "total_compatible_anims" in res.content
    assert captured["port"] == 9878
    assert '"VERA_Manny"' in captured["script"]


def test_ruido_de_log_antes_del_json(monkeypatch):
    out = "LogTemp: warning x\n" + json.dumps(
        {"actor": "A", "kind": "static", "skeleton": None,
         "compatible_anims": [], "total_compatible_anims": 0,
         "current_anim_mode": None, "notes": "static mesh"})
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": True, "output": out})
    res = InspectActorAnimabilityTool().execute({"actor_name": "A"}, ToolContext())
    assert res.is_error is False
    assert "static" in res.content


def test_not_found_con_candidatos(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: {
        "success": True,
        "output": json.dumps({"error": "not_found", "actor": "Raton",
                              "candidates": ["Altar", "Goal"]})})
    res = InspectActorAnimabilityTool().execute({"actor_name": "Raton"}, ToolContext())
    assert res.is_error is True
    assert "Altar" in res.content and "Goal" in res.content


def test_actor_name_vacio_no_llama_al_bridge(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = InspectActorAnimabilityTool().execute({"actor_name": "   "}, ToolContext())
    assert res.is_error is True


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = InspectActorAnimabilityTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content


def test_output_no_parseable(monkeypatch):
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": True, "output": "ruido sin json"})
    res = InspectActorAnimabilityTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True


def test_error_del_editor(monkeypatch):
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": False, "error": "boom interno"})
    res = InspectActorAnimabilityTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "boom interno" in res.content
