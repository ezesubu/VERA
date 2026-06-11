import json
import socket
import threading

import pytest

from vera.tools.mcp_server import send_vera_command
from vera.tools.ue_conn import UEConnectionError, send_json_stream


@pytest.fixture
def streaming_backend():
    """Backend falso que emite progreso + final con el protocolo streaming."""
    state = {
        "lines": [
            {"type": "progress", "agent": "Manager", "msg": "routing"},
            {"type": "image", "path": "E:/x.png"},
            {"type": "final", "status": "success", "msg": "Done."},
        ]
    }
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    state["port"] = server.getsockname()[1]
    stop = threading.Event()

    def serve():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                for line in state["lines"]:
                    conn.sendall((json.dumps(line) + "\n").encode("utf-8"))

    threading.Thread(target=serve, daemon=True).start()
    yield state
    stop.set()
    server.close()


def test_stream_collects_until_final(streaming_backend):
    events = send_json_stream(
        streaming_backend["port"], {"command": "build"}, timeout=10.0)
    assert [e["type"] for e in events] == ["progress", "image", "final"]


def test_stream_on_event_callback(streaming_backend):
    seen = []
    send_json_stream(
        streaming_backend["port"], {"command": "build"},
        on_event=seen.append, timeout=10.0)
    assert len(seen) == 3


def test_stream_connection_refused_raises():
    with pytest.raises(UEConnectionError):
        send_json_stream(1, {"command": "x"}, timeout=2.0)


def test_send_vera_command_returns_final_with_events(streaming_backend):
    result = send_vera_command("build", port=streaming_backend["port"])
    assert result["status"] == "success"
    assert result["msg"] == "Done."
    assert len(result["events"]) == 3
