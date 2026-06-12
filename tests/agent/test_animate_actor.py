# tests/agent/test_animate_actor.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.animate_actor import AnimateActorTool
import vera.agent.tools.animate_actor as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert AnimateActorTool().destructive is True


def test_animate_reproduce_animacion(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"actor": "VERA_Manny", "kind": "skeletal",
                    "strategy_used": "played_animation",
                    "animation": "MM_Idle", "looping": True})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "VERA_Manny"}, ToolContext())
    assert res.is_error is False
    assert "played_animation" in res.content
    assert '"VERA_Manny"' in captured["script"]
    assert "play_animation" in captured["script"]


def test_animate_static_reporte_honesto_no_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"actor": "CyberHead", "kind": "static", "strategy_used": "not_animable",
         "reason": "sin esqueleto"}))
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "CyberHead"}, ToolContext())
    assert res.is_error is False           # reporte honesto = resultado válido
    assert "not_animable" in res.content


def test_animate_anim_incompatible_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"actor": "VERA_Manny", "kind": "skeletal", "strategy_used": None,
         "error": "anim_not_compatible", "requested": "Samba",
         "compatible_anims": ["MM_Idle"]}))
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "VERA_Manny", "animation": "Samba"},
        ToolContext())
    assert res.is_error is True
    assert "MM_Idle" in res.content


def test_animate_actor_inexistente(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "not_found", "actor": "Nada", "candidates": ["Goal", "Lava"]}))
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "Nada"}, ToolContext())
    assert res.is_error is True
    assert "Goal" in res.content


def test_animate_requiere_actor_name(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute({"action": "animate"}, ToolContext())
    assert res.is_error is True


def test_action_invalida():
    res = AnimateActorTool().execute({"action": "bailar"}, ToolContext())
    assert res.is_error is True


def test_spawn_script_y_resultado(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"strategy_used": "spawned", "actor": "VERA_Manny",
                    "kind": "skeletal", "tag": "VERA_SPAWNED",
                    "location": [100.0, 200.0, 90.0],
                    "animation": "MF_Unarmed_Jog_Fwd", "looping": True})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = AnimateActorTool().execute(
        {"action": "spawn", "animation": "MF_Unarmed_Jog_Fwd",
         "location": [100.0, 200.0, 90.0]}, ToolContext())
    assert res.is_error is False
    assert "spawned" in res.content
    assert "SKM_Manny_Simple" in captured["script"]
    assert "VERA_SPAWNED" in captured["script"]
    assert "location = [100.0, 200.0, 90.0]" in captured["script"]


def test_spawn_anim_incompatible_no_es_error_si_spawneo(monkeypatch):
    # el actor SÍ se creó: error de anim es informativo, no fallo del sistema
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"strategy_used": "spawned", "actor": "VERA_Manny", "kind": "skeletal",
         "tag": "VERA_SPAWNED", "location": [0.0, 0.0, 90.0], "animation": None,
         "error": "anim_not_compatible", "requested": "Samba",
         "compatible_anims": ["MM_Idle"]}))
    res = AnimateActorTool().execute(
        {"action": "spawn", "animation": "Samba"}, ToolContext())
    assert res.is_error is False
    assert "anim_not_compatible" in res.content


def test_spawn_location_invalida(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute(
        {"action": "spawn", "location": [1, 2]}, ToolContext())
    assert res.is_error is True


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content


def test_error_del_editor(monkeypatch):
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": False, "error": "boom interno"})
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "boom interno" in res.content


def test_output_no_parseable_capea_el_eco(monkeypatch):
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": True, "output": "x" * 2000})
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "x" * 500 in res.content
    assert "x" * 501 not in res.content   # eco acotado por tail_of_output


def test_stop_detiene_y_restaura(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"actor": "Enemy_CyberHead", "stopped": ["procedural"],
                    "strategy_used": "stopped"})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = AnimateActorTool().execute(
        {"action": "stop", "actor_name": "Enemy_CyberHead"}, ToolContext())
    assert res.is_error is False
    assert "stopped" in res.content
    assert "vera_proc_anim" in captured["script"]


def test_stop_requiere_actor_name(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute({"action": "stop"}, ToolContext())
    assert res.is_error is True
