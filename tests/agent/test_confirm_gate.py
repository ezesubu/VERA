import json
import socket
from types import SimpleNamespace

import vera.core.vera_server as vs


def _confirm_pair():
    """Un VeraServer sin bind ni manager + un par de sockets conectados."""
    srv = vs.VeraServer.__new__(vs.VeraServer)  # sin __init__: solo usamos _make_confirm
    # socketpair en Windows < 3.12 emula con un par TCP loopback; para este
    # test alcanza porque solo necesitamos bidireccionalidad.
    a, b = socket.socketpair()
    events = []
    return srv._make_confirm(a, events.append), a, b, events


_TOOL = SimpleNamespace(name="run_ue_python")


def test_aprueba_cuando_el_cliente_responde_approve_true():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"approve": true}\n')
    assert confirm(_TOOL, {"code": "unreal.log('x')"}) is True
    assert events[0]["type"] == "question"
    assert events[0]["tool"] == "run_ue_python"
    a.close(); b.close()


def test_deniega_cuando_el_cliente_responde_false():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"approve": false}\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_deniega_si_el_cliente_se_desconecta():
    confirm, a, b, events = _confirm_pair()
    b.close()  # desconexión antes de responder
    assert confirm(_TOOL, {}) is False
    a.close()


def test_auto_approve_saltea_el_gate(monkeypatch):
    monkeypatch.setenv("VERA_AUTO_APPROVE", "1")
    confirm, a, b, events = _confirm_pair()
    # no se envía respuesta: si el gate leyera del socket, colgaría
    assert confirm(_TOOL, {}) is True
    assert events == []  # ni siquiera pregunta
    a.close(); b.close()


def test_deniega_cuando_approve_ausente_en_json():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"ok": true}\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_deniega_cuando_json_invalido():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'no-es-json\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_deniega_respuesta_gigante_sin_newline():
    import vera.core.vera_server as _vs
    confirm, a, b, events = _confirm_pair()
    b.sendall(b"x" * (_vs.MAX_CONFIRM_BYTES + 100))
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()
