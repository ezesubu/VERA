import time

import pytest

from vera.tools.ue_conn import UEConnectionError, UETimeoutError, send_json


def test_roundtrip(fake_bridge):
    fake_bridge["handler"] = lambda p: {"echo": p["script"]}
    result = send_json(fake_bridge["port"], {"script": "print(1)"})
    assert result == {"echo": "print(1)"}


def test_connection_refused_raises_typed_error():
    # Port 1 is closed on any local machine
    with pytest.raises(UEConnectionError):
        send_json(1, {"script": "x"}, timeout=2.0)


def test_slow_server_raises_timeout(fake_bridge):
    def slow(payload):
        time.sleep(1.0)
        return {"success": True}

    fake_bridge["handler"] = slow
    with pytest.raises(UETimeoutError):
        send_json(fake_bridge["port"], {"script": "x"}, timeout=0.3)


def test_malformed_response_raises_typed_error(garbage_bridge):
    with pytest.raises(UEConnectionError):
        send_json(garbage_bridge, {"script": "x"}, timeout=5.0)
