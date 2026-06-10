"""Testea el bridge real con un módulo `unreal` stubbeado y el tick manual."""
import json
import os
import socket
import sys
import threading
import time
import types

import pytest


@pytest.fixture
def bridge_module(monkeypatch):
    """Importa vera_bridge con `unreal` falso y sin auto-start."""
    fake_unreal = types.SimpleNamespace(
        log=lambda msg: None,
        log_error=lambda msg: None,
        register_slate_post_tick_callback=lambda fn: object(),
    )
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)
    monkeypatch.setenv("VERA_BRIDGE_NO_AUTOSTART", "1")
    # Importar desde la carpeta del proyecto UE
    bridge_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "UE57", "Content", "Python",
    )
    monkeypatch.syspath_prepend(bridge_dir)
    sys.modules.pop("vera_bridge", None)
    import vera_bridge

    return vera_bridge


def _send(port, payload):
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as s:
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8").strip())


@pytest.fixture
def running_bridge(bridge_module):
    """Bridge escuchando en puerto efímero + bomba de tick simulando el main thread."""
    port = bridge_module.start(port=0)  # 0 = puerto efímero, devuelve el real
    stop = threading.Event()

    def tick_pump():
        while not stop.is_set():
            bridge_module.slate_tick_callback(0.0)
            time.sleep(0.01)

    t = threading.Thread(target=tick_pump, daemon=True)
    t.start()
    yield port
    stop.set()


def test_exec_roundtrip_newline_framed(running_bridge):
    result = _send(running_bridge, {"script": "print('hola UE')"})
    assert result["success"] is True
    assert "hola UE" in result["output"]


def test_exec_error_returns_traceback(running_bridge):
    result = _send(running_bridge, {"script": "variable_inexistente"})
    assert result["success"] is False
    assert "NameError" in result["error"]
