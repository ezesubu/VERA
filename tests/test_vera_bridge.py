"""Tests the real bridge with a stubbed `unreal` module and a manual tick."""
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
    """Imports vera_bridge with a fake `unreal` and no auto-start."""
    fake_unreal = types.SimpleNamespace(
        log=lambda msg: None,
        log_error=lambda msg: None,
        register_slate_post_tick_callback=lambda fn: object(),
    )
    monkeypatch.setitem(sys.modules, "unreal", fake_unreal)
    monkeypatch.setenv("VERA_BRIDGE_NO_AUTOSTART", "1")
    # Import from the UE project folder
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
    """Bridge listening on an ephemeral port + tick pump simulating the main thread."""
    port = bridge_module.start(port=0)  # 0 = ephemeral port, returns the real one
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
    result = _send(running_bridge, {"script": "print('hello UE')"})
    assert result["success"] is True
    assert "hello UE" in result["output"]


def test_exec_error_returns_traceback(running_bridge):
    result = _send(running_bridge, {"script": "nonexistent_variable"})
    assert result["success"] is False
    assert "NameError" in result["error"]


def test_tick_stall_returns_timeout_and_no_leaks(bridge_module, monkeypatch):
    # Bridge WITHOUT a tick pump: nobody drains the queue → server-side timeout
    monkeypatch.setattr(bridge_module, "MAIN_THREAD_TIMEOUT", 0.5)
    port = bridge_module.start(port=0)
    result = _send(port, {"script": "print('never')"})
    assert result["success"] is None
    assert "did not process" in result["error"]
    # no leaks: the dicts are clean after the timeout
    time.sleep(0.1)
    assert bridge_module._results == {}
    assert bridge_module._result_events == {}


def test_two_concurrent_clients_get_own_results(running_bridge):
    results = {}

    def call(tag):
        results[tag] = _send(running_bridge, {"script": "print('%s')" % tag})

    t1 = threading.Thread(target=call, args=("one",))
    t2 = threading.Thread(target=call, args=("two",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert results["one"]["output"] == "one"
    assert results["two"]["output"] == "two"
