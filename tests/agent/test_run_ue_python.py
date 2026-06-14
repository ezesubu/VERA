from vera.agent.tool import ToolContext
from vera.agent.tools.run_ue_python import RunUEPythonTool
import vera.agent.tools.run_ue_python as mod
from vera.tools.ue_conn import UEConnectionError


def test_destructive_default():
    assert RunUEPythonTool().destructive is True


def test_success(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["port"] = port
        captured["script"] = payload["script"]
        return {"success": True, "output": "HELLO"}

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = RunUEPythonTool().execute({"code": "print('x')"}, ToolContext(bridge_port=9878))
    assert res.is_error is False
    assert res.content == "HELLO"
    assert captured["port"] == 9878
    assert captured["script"] == "print('x')"


def test_failure_from_editor(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: {"success": False, "error": "boom"})
    res = RunUEPythonTool().execute({"code": "x"}, ToolContext())
    assert res.is_error is True
    assert "boom" in res.content


def test_empty_code():
    res = RunUEPythonTool().execute({"code": "   "}, ToolContext())
    assert res.is_error is True


def test_bridge_unreachable(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor closed")

    monkeypatch.setattr(mod, "send_json", boom)
    res = RunUEPythonTool().execute({"code": "x"}, ToolContext())
    assert res.is_error is True
    assert "editor closed" in res.content
