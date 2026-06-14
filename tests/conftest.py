"""Shared fixtures: a fake TCP bridge with a configurable handler."""
import json
import socket
import threading

import pytest


@pytest.fixture
def fake_bridge():
    """Ephemeral TCP server that mimics the Unreal bridge's framing.

    Usage: fake_bridge["handler"] = lambda payload: {...}; port in fake_bridge["port"].
    """
    state = {"handler": lambda payload: {"success": True, "output": ""}}
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
            except (socket.timeout, OSError):
                continue
            with conn:
                try:
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    payload = json.loads(data.decode("utf-8"))
                    resp = state["handler"](payload)
                    conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                except Exception as e:  # a broken handler must not kill the thread
                    try:
                        err = json.dumps({"success": False, "error": f"fake_bridge handler: {e}"})
                        conn.sendall((err + "\n").encode("utf-8"))
                    except OSError:
                        pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield state
    stop.set()
    server.close()


@pytest.fixture
def garbage_bridge():
    """TCP server that responds with something that is not JSON (broken protocol)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]
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
                conn.sendall(b"this is not json\n")

    threading.Thread(target=serve, daemon=True).start()
    yield port
    stop.set()
    server.close()
