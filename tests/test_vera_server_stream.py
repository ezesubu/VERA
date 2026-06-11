import json
import socket
import threading
import time

import pytest

from vera.core.blackboard import Blackboard
from vera.core.vera_server import VeraServer


class FakeManager:
    """Manager falso: emite 2 eventos de progreso y devuelve éxito."""

    def __init__(self, blackboard, succeed=True):
        self.blackboard = blackboard
        self.succeed = succeed

    def execute_command(self, command):
        self.blackboard.report_progress("Manager", "routed to Python")
        self.blackboard.report_progress("Python", "executing")
        return self.succeed


@pytest.fixture
def server_factory():
    servers = []

    def make(succeed=True):
        bb = Blackboard()
        srv = VeraServer(port=0, blackboard=bb, manager=FakeManager(bb, succeed))
        port = srv.start_in_thread()
        servers.append(srv)
        return port

    yield make
    for s in servers:
        s.stop()


def _send_and_read_events(port, command):
    events = []
    with socket.create_connection(("127.0.0.1", port), timeout=10.0) as s:
        s.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    events.append(json.loads(line.decode("utf-8")))
            if events and events[-1].get("type") == "final":
                return events
    return events


def test_stream_emits_progress_then_final(server_factory):
    port = server_factory(succeed=True)
    events = _send_and_read_events(port, "build a bridge")
    types = [e["type"] for e in events]
    assert types == ["progress", "progress", "final"]
    assert events[0]["agent"] == "Manager"
    assert events[-1]["status"] == "success"


def test_failed_command_final_is_error_status(server_factory):
    port = server_factory(succeed=False)
    events = _send_and_read_events(port, "imposible")
    assert events[-1]["type"] == "final"
    assert events[-1]["status"] == "error"


def test_hello_world_shortcut_single_final(server_factory):
    port = server_factory()
    events = _send_and_read_events(port, "hello world")
    assert len(events) == 1
    assert events[0]["type"] == "final"
    assert events[0]["status"] == "success"


def test_callback_cleared_after_command():
    bb = Blackboard()
    srv = VeraServer(port=0, blackboard=bb, manager=FakeManager(bb))
    port = srv.start_in_thread()
    try:
        _send_and_read_events(port, "build")
        assert bb.progress_callback is None
    finally:
        srv.stop()


def test_manager_exception_yields_error_final():
    bb = Blackboard()

    class ExplodingManager:
        def execute_command(self, command):
            raise RuntimeError("boom")

    srv = VeraServer(port=0, blackboard=bb, manager=ExplodingManager())
    port = srv.start_in_thread()
    try:
        events = _send_and_read_events(port, "explota")
        assert events[-1]["type"] == "final"
        assert events[-1]["status"] == "error"
        assert bb.progress_callback is None
    finally:
        srv.stop()


def test_concurrent_second_command_gets_busy_final():
    bb = Blackboard()

    class SlowManager:
        def __init__(self, blackboard):
            self.blackboard = blackboard
            self.release = threading.Event()

        def execute_command(self, command):
            self.blackboard.report_progress("Manager", "working")
            self.release.wait(timeout=10.0)
            return True

    mgr = SlowManager(bb)
    srv = VeraServer(port=0, blackboard=bb, manager=mgr)
    port = srv.start_in_thread()
    try:
        results = {}

        def first():
            results["a"] = _send_and_read_events(port, "lento")

        t = threading.Thread(target=first, daemon=True)
        t.start()
        deadline = time.time() + 5.0
        while not srv._busy.locked() and time.time() < deadline:
            time.sleep(0.02)
        assert srv._busy.locked(), "el primer comando nunca tomó el lock"
        results["b"] = _send_and_read_events(port, "segundo")
        assert results["b"][-1]["status"] == "error"
        assert "ocupada" in results["b"][-1]["msg"]
        mgr.release.set()
        t.join(timeout=10.0)
        assert results["a"][-1]["status"] == "success"
    finally:
        srv.stop()
