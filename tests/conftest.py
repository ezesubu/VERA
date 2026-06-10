"""Fixtures compartidas: un bridge TCP falso con handler configurable."""
import json
import socket
import threading

import pytest


@pytest.fixture
def fake_bridge():
    """Server TCP efímero que imita el framing del bridge de Unreal.

    Uso: fake_bridge["handler"] = lambda payload: {...}; puerto en fake_bridge["port"].
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
                except Exception as e:  # un handler roto no debe matar el thread
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
