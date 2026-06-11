import threading
import time
from pathlib import Path

from vera.tools.mcp_server import (
    BRIDGE_DOWN_MSG,
    check_status,
    request_screenshot,
    run_script,
    send_vera_command,
    tail_log,
)


def test_tail_log_returns_last_n_lines(tmp_path):
    log = tmp_path / "UE57.log"
    log.write_text("\n".join(f"linea {i}" for i in range(200)), encoding="utf-8")
    out = tail_log(log, lines=5)
    assert out.splitlines() == ["linea 195", "linea 196", "linea 197", "linea 198", "linea 199"]


def test_tail_log_missing_file_returns_message(tmp_path):
    out = tail_log(tmp_path / "no_existe.log", lines=10)
    assert "No existe el log" in out


def test_tail_log_tolerates_bad_encoding(tmp_path):
    log = tmp_path / "UE57.log"
    log.write_bytes(b"ok\n\xff\xfe rotas\nfin\n")
    out = tail_log(log, lines=10)
    assert "fin" in out


def test_tail_log_zero_or_negative_lines_returns_empty(tmp_path):
    log = tmp_path / "UE57.log"
    log.write_text("a\nb\nc\n", encoding="utf-8")
    assert tail_log(log, lines=0) == ""
    assert tail_log(log, lines=-5) == ""


def test_run_script_returns_output(fake_bridge):
    fake_bridge["handler"] = lambda p: {"success": True, "output": "Hola desde UE"}
    result = run_script("print('Hola desde UE')", port=fake_bridge["port"])
    assert result["success"] is True
    assert result["output"] == "Hola desde UE"


def test_run_script_returns_ue_traceback_as_result(fake_bridge):
    fake_bridge["handler"] = lambda p: {
        "success": False,
        "output": "",
        "error": "Traceback...\nNameError: name 'foo' is not defined",
    }
    result = run_script("foo()", port=fake_bridge["port"])
    assert result["success"] is False
    assert "NameError" in result["error"]


def test_run_script_editor_down_gives_actionable_message():
    result = run_script("print(1)", port=1)
    assert result["success"] is False
    assert result["error"] == BRIDGE_DOWN_MSG


def test_run_script_timeout_says_still_running(fake_bridge):
    def slow(payload):
        time.sleep(1.0)
        return {"success": True, "output": ""}

    fake_bridge["handler"] = slow
    result = run_script("largo()", port=fake_bridge["port"], timeout=0.3)
    assert result["success"] is None
    assert "sigue ejecutando" in result["output"]


def test_check_status_both_down():
    status = check_status(bridge_port=1, backend_port=1)
    assert status["bridge"]["online"] is False
    assert status["backend"]["online"] is False


def test_check_status_bridge_up(fake_bridge):
    fake_bridge["handler"] = lambda p: {"success": True, "output": "5.7.0"}
    status = check_status(bridge_port=fake_bridge["port"], backend_port=1)
    assert status["bridge"]["online"] is True
    assert status["bridge"]["engine_version"] == "5.7.0"


def test_send_vera_command(fake_bridge):
    # El backend ahora responde streaming; el fake emite solo la final
    fake_bridge["handler"] = lambda p: {
        "type": "final", "status": "success", "msg": f"eco: {p['command']}"}
    result = send_vera_command("hello world", port=fake_bridge["port"])
    assert result["status"] == "success"
    assert "hello world" in result["msg"]


def test_check_status_survives_garbage_bridge(garbage_bridge):
    # Un bridge que habla mal el protocolo no debe crashear el diagnóstico
    status = check_status(bridge_port=garbage_bridge, backend_port=1)
    assert status["bridge"]["online"] is False
    assert status["backend"]["online"] is False


def test_request_screenshot_returns_path_when_file_appears(fake_bridge, tmp_path):
    captured = {}

    def handler(payload):
        captured["script"] = payload["script"]
        # Simula la escritura asíncrona de UE: el PNG aparece en dos chunks
        name = payload["script"].split('"')[-2]  # último string literal = nombre

        def write_later():
            time.sleep(0.3)
            f = tmp_path / name
            f.write_bytes(b"\x89PNG ")          # primera mitad: tamaño aún creciendo
            time.sleep(0.4)
            with f.open("ab") as fh:
                fh.write(b"fake resto")          # tamaño final

        threading.Thread(target=write_later, daemon=True).start()
        return {"success": True, "output": ""}

    fake_bridge["handler"] = handler
    path = request_screenshot(
        port=fake_bridge["port"], screenshots_dir=tmp_path, timeout=5.0
    )
    assert path is not None
    assert path.exists()
    assert "take_high_res_screenshot" in captured["script"]
    assert path.read_bytes() == b"\x89PNG fake resto"


def test_request_screenshot_returns_none_if_file_never_appears(fake_bridge, tmp_path):
    fake_bridge["handler"] = lambda p: {"success": True, "output": ""}
    path = request_screenshot(
        port=fake_bridge["port"], screenshots_dir=tmp_path, timeout=0.5
    )
    assert path is None


def test_request_screenshot_bridge_down_returns_none(tmp_path):
    path = request_screenshot(port=1, screenshots_dir=tmp_path, timeout=0.5)
    assert path is None
