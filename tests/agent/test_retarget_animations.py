# tests/agent/test_retarget_animations.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.retarget_animations import RetargetAnimationsTool
import vera.agent.tools.retarget_animations as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_is_destructive():
    assert RetargetAnimationsTool().destructive is True


def test_batch_happy_with_play(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"created_anims": ["/Game/T/VERA_Retargeted/MM_Idle_VERA_RTG"],
                    "skipped": [], "played": "MM_Idle_VERA_RTG"})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R/RTG", "animations": ["MM_Idle"],
         "target_actor_name": "UE4Guy", "play_first": True}, ToolContext())
    assert res.is_error is False
    assert "MM_Idle_VERA_RTG" in res.content
    assert '"/Game/R/RTG"' in captured["script"]
    assert "play_first = True" in captured["script"]


def test_auto_by_default(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"created_anims": ["/Game/x"], "skipped": [], "played": None})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R/RTG"}, ToolContext())
    assert res.is_error is False
    assert '"auto"' in captured["script"]


def test_idempotent_all_skipped_is_not_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"created_anims": [], "skipped": ["MM_Idle (already retargeted)"],
         "played": None}))
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R/RTG", "animations": ["MM_Idle"]},
        ToolContext())
    assert res.is_error is False
    assert "already retargeted" in res.content


def test_nonexistent_retargeter_is_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "retargeter_not_found", "path": "/Game/Nada"}))
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/Nada"}, ToolContext())
    assert res.is_error is True


def test_play_first_requires_actor(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R", "play_first": True}, ToolContext())
    assert res.is_error is True


def test_bridge_down(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor closed")
    monkeypatch.setattr(mod, "send_json", boom)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R"}, ToolContext())
    assert res.is_error is True
