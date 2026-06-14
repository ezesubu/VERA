import json
import socket
from types import SimpleNamespace

import vera.core.vera_server as vs


def _confirm_pair():
    """A VeraServer with no bind or manager + a pair of connected sockets."""
    srv = vs.VeraServer.__new__(vs.VeraServer)  # no __init__: we only use _make_confirm
    # socketpair on Windows < 3.12 emulates with a TCP loopback pair; for this
    # test that is enough because we only need bidirectionality.
    a, b = socket.socketpair()
    events = []
    return srv._make_confirm(a, events.append), a, b, events


_TOOL = SimpleNamespace(name="run_ue_python")


def test_approves_when_client_responds_approve_true():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"approve": true}\n')
    assert confirm(_TOOL, {"code": "unreal.log('x')"}) is True
    assert events[0]["type"] == "question"
    assert events[0]["tool"] == "run_ue_python"
    a.close(); b.close()


def test_denies_when_client_responds_false():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"approve": false}\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_denies_if_the_client_disconnects():
    confirm, a, b, events = _confirm_pair()
    b.close()  # disconnect before responding
    assert confirm(_TOOL, {}) is False
    a.close()


def test_auto_approve_skips_the_gate(monkeypatch):
    monkeypatch.setenv("VERA_AUTO_APPROVE", "1")
    confirm, a, b, events = _confirm_pair()
    # no response is sent: if the gate read from the socket, it would hang
    assert confirm(_TOOL, {}) is True
    assert events == []  # it does not even ask
    a.close(); b.close()


def test_denies_when_approve_absent_in_json():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"ok": true}\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_denies_when_json_invalid():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'not-json\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_denies_giant_response_without_newline():
    import vera.core.vera_server as _vs
    confirm, a, b, events = _confirm_pair()
    b.sendall(b"x" * (_vs.MAX_CONFIRM_BYTES + 100))
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()
