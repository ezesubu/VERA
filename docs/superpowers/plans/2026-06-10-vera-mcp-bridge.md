# VERA MCP Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code controla el editor de Unreal vía un servidor MCP con las herramientas `ue_exec`, `ue_screenshot`, `ue_log`, `ue_status` y `vera_command` — el "loop completo con ojos".

**Architecture:** Un servidor MCP stdio (FastMCP) traduce herramientas a llamadas TCP newline-framed contra dos puertos locales: el bridge dentro del editor (9878, ejecuta Python en el main thread) y el backend de agentes VERA (9880). El bridge se muda a `UE57/Content/Python/vera_bridge.py` y auto-arranca vía `init_unreal.py`. `ue_log` lee `Saved/Logs/UE57.log` directo del disco para funcionar incluso con el editor colgado.

**Tech Stack:** Python 3.10+ (repo usa 3.14), SDK oficial `mcp` (FastMCP), pytest, sockets stdlib. Sin dependencias nuevas más allá de `mcp`.

**Spec:** `docs/superpowers/specs/2026-06-10-vera-mcp-bridge-design.md`

**Working dir para todos los comandos:** `E:\PCW\VERA` (raíz del repo). Tests corren con `python -m pytest`.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `vera/tools/ue_conn.py` (crear) | Cliente TCP newline-framed + excepciones tipadas. Única pieza que toca sockets del lado cliente. |
| `vera/tools/mcp_server.py` (crear) | Funciones puras por herramienta (testeables sin MCP) + wiring FastMCP en `main()`. |
| `UE57/Content/Python/vera_bridge.py` (crear) | Bridge dentro del editor: server TCP, exec en main thread vía slate tick, framing newline en ambas direcciones. |
| `UE57/Content/Python/init_unreal.py` (crear) | Auto-arranque: Unreal lo ejecuta al abrir el proyecto; importa bridge y UI. |
| `vera/tools/ue_bridge_server.py` (borrar) | Reemplazado por `vera_bridge.py` (Task 6). |
| `.mcp.json` (crear, raíz) | Registra el server en Claude Code. |
| `pyproject.toml` (modificar) | Agregar dependencia `mcp`. |
| `tests/conftest.py` (crear) | Fixture `fake_bridge` (server TCP efímero configurable). |
| `tests/test_ue_conn.py` (crear) | Tests del cliente TCP. |
| `tests/test_mcp_tools.py` (crear) | Tests de las funciones de herramientas. |
| `tests/test_vera_bridge.py` (crear) | Test del bridge con módulo `unreal` stubbeado. |
| `docs/mcp-bridge.md` (crear) | Setup, smoke test manual y demo de aceptación. |

Nota de entorno: los tests y el server MCP corren con el Python del sistema (3.14). El bridge corre con el Python embebido de Unreal (3.11 en UE 5.7) — `vera_bridge.py` solo usa stdlib, sin f-strings con `=` ni sintaxis >3.10.

---

### Task 1: Cliente TCP newline-framed (`ue_conn.py`)

**Files:**
- Create: `vera/tools/ue_conn.py`
- Create: `tests/conftest.py`
- Test: `tests/test_ue_conn.py`

- [ ] **Step 1: Escribir la fixture `fake_bridge`**

`tests/conftest.py`:

```python
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
            except socket.timeout:
                continue
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                payload = json.loads(data.decode("utf-8"))
                resp = state["handler"](payload)
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield state
    stop.set()
    server.close()
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_ue_conn.py`:

```python
import time

import pytest

from vera.tools.ue_conn import UEConnectionError, UETimeoutError, send_json


def test_roundtrip(fake_bridge):
    fake_bridge["handler"] = lambda p: {"echo": p["script"]}
    result = send_json(fake_bridge["port"], {"script": "print(1)"})
    assert result == {"echo": "print(1)"}


def test_connection_refused_raises_typed_error():
    # Puerto 1 está cerrado en cualquier máquina local
    with pytest.raises(UEConnectionError):
        send_json(1, {"script": "x"}, timeout=2.0)


def test_slow_server_raises_timeout(fake_bridge):
    def slow(payload):
        time.sleep(1.0)
        return {"success": True}

    fake_bridge["handler"] = slow
    with pytest.raises(UETimeoutError):
        send_json(fake_bridge["port"], {"script": "x"}, timeout=0.3)
```

- [ ] **Step 3: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_ue_conn.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.tools.ue_conn'`

- [ ] **Step 4: Implementar `ue_conn.py`**

`vera/tools/ue_conn.py`:

```python
"""Cliente TCP newline-framed para el bridge de Unreal (9878) y el backend VERA (9880)."""
import json
import socket

DEFAULT_TIMEOUT = 60.0


class UEConnectionError(RuntimeError):
    """No se pudo conectar: editor cerrado o bridge/backend no cargado."""


class UETimeoutError(RuntimeError):
    """El destino aceptó la conexión pero no respondió a tiempo."""


def send_json(port, payload, timeout=DEFAULT_TIMEOUT, host="127.0.0.1"):
    """Envía un dict como JSON + '\\n' y lee una respuesta JSON terminada en '\\n'."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except socket.timeout as e:
        raise UETimeoutError(f"sin respuesta en {timeout:.0f}s") from e
    except OSError as e:
        raise UEConnectionError(str(e)) from e
    if not buf.strip():
        raise UEConnectionError("el servidor cerró la conexión sin responder")
    return json.loads(buf.decode("utf-8").strip())
```

Nota: `socket.timeout` es alias de `TimeoutError` (subclase de `OSError`), por eso se captura **antes** que `OSError`.

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_ue_conn.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add vera/tools/ue_conn.py tests/conftest.py tests/test_ue_conn.py
git commit -m "feat: cliente TCP newline-framed para el bridge de Unreal"
```

---

### Task 2: Lectura del log del editor (`tail_log`)

**Files:**
- Create: `vera/tools/mcp_server.py` (solo la función `tail_log`; el resto llega en Tasks 3-5)
- Test: `tests/test_mcp_tools.py`

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_mcp_tools.py`:

```python
from pathlib import Path

from vera.tools.mcp_server import tail_log


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
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.tools.mcp_server'`

- [ ] **Step 3: Implementar `tail_log`**

`vera/tools/mcp_server.py`:

```python
"""Servidor MCP de VERA: expone el editor de Unreal como herramientas para Claude Code.

Las funciones de este módulo son puras/testeables; el wiring FastMCP vive en main().
"""
import os
from pathlib import Path

# Raíz del repo = dos niveles arriba de vera/tools/
_REPO_ROOT = Path(__file__).resolve().parents[2]
UE_PROJECT_DIR = Path(os.environ.get("VERA_UE_PROJECT_DIR", _REPO_ROOT / "UE57"))
LOG_PATH = UE_PROJECT_DIR / "Saved" / "Logs" / "UE57.log"


def tail_log(path, lines=100):
    """Últimas N líneas del log del editor. Lee el archivo directo: funciona
    aunque el editor esté colgado o crasheado."""
    path = Path(path)
    if not path.exists():
        return f"No existe el log en {path}. ¿El editor llegó a abrir alguna vez?"
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add vera/tools/mcp_server.py tests/test_mcp_tools.py
git commit -m "feat: tail_log lee el Output Log del editor directo del disco"
```

---

### Task 3: `run_script`, `check_status` y `send_vera_command` (lógica de herramientas)

**Files:**
- Modify: `vera/tools/mcp_server.py` (agregar funciones)
- Test: `tests/test_mcp_tools.py` (agregar tests)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_mcp_tools.py`:

```python
from vera.tools.mcp_server import (
    BRIDGE_DOWN_MSG,
    check_status,
    run_script,
    send_vera_command,
)


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
    import time

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
    # El backend responde {"status", "message"} — mismo framing
    fake_bridge["handler"] = lambda p: {"status": "success", "message": f"eco: {p['command']}"}
    result = send_vera_command("hello world", port=fake_bridge["port"])
    assert result["status"] == "success"
    assert "hello world" in result["message"]
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_script'`

- [ ] **Step 3: Implementar las funciones**

Agregar a `vera/tools/mcp_server.py` (debajo de `tail_log`):

```python
from vera.tools.ue_conn import UEConnectionError, UETimeoutError, send_json

BRIDGE_PORT = int(os.environ.get("VERA_BRIDGE_PORT", "9878"))
BACKEND_PORT = int(os.environ.get("VERA_BACKEND_PORT", "9880"))

BRIDGE_DOWN_MSG = (
    "Unreal no está corriendo o el bridge no cargó. Abrí el proyecto UE57 "
    "(el bridge auto-arranca con init_unreal.py) o ejecutá `import vera_bridge` "
    "en la consola Python del editor. Probá `ue_status` para diagnosticar."
)
BACKEND_DOWN_MSG = (
    "El backend VERA (puerto 9880) no está corriendo. "
    "Arrancalo con: python -m vera.core.vera_server"
)


def run_script(script, timeout=60.0, port=None):
    """Ejecuta Python en el main thread del editor. El traceback de UE vuelve
    como resultado normal (success=False), no como excepción — el agente lo lee
    y corrige. success=None significa timeout: el script puede seguir corriendo."""
    try:
        result = send_json(port or BRIDGE_PORT, {"script": script}, timeout=timeout)
    except UETimeoutError:
        return {
            "success": None,
            "output": (
                f"El editor no respondió en {timeout:.0f}s — el script sigue "
                "ejecutando (compilar shaders o cargar assets puede tardar). "
                "Verificá con ue_log o ue_status; no se abortó nada."
            ),
        }
    except UEConnectionError:
        return {"success": False, "output": "", "error": BRIDGE_DOWN_MSG}
    return result


def check_status(bridge_port=None, backend_port=None):
    """Ping a bridge y backend. Para el bridge pide la versión del engine."""
    status = {"bridge": {"online": False}, "backend": {"online": False}}

    version_script = "import unreal\nprint(unreal.SystemLibrary.get_engine_version())"
    try:
        result = send_json(
            bridge_port or BRIDGE_PORT, {"script": version_script}, timeout=10.0
        )
        status["bridge"]["online"] = bool(result.get("success"))
        status["bridge"]["engine_version"] = result.get("output", "").strip()
    except (UEConnectionError, UETimeoutError) as e:
        status["bridge"]["error"] = f"{BRIDGE_DOWN_MSG} ({e})"

    try:
        result = send_json(
            backend_port or BACKEND_PORT, {"command": "hello world"}, timeout=10.0
        )
        status["backend"]["online"] = result.get("status") == "success"
    except (UEConnectionError, UETimeoutError) as e:
        status["backend"]["error"] = f"{BACKEND_DOWN_MSG} ({e})"

    return status


def send_vera_command(text, timeout=300.0, port=None):
    """Comando de alto nivel al ManagerAgent (pipeline de agentes/recetas)."""
    try:
        return send_json(port or BACKEND_PORT, {"command": text}, timeout=timeout)
    except UEConnectionError:
        return {"status": "error", "message": BACKEND_DOWN_MSG}
    except UETimeoutError:
        return {
            "status": "error",
            "message": f"El backend no respondió en {timeout:.0f}s. Mirá sus logs.",
        }
```

Nota: `send_vera_command` usa timeout 300 s porque el pipeline de agentes llama a un LLM (puede tardar minutos).

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: 10 passed (3 de tail_log + 7 nuevos)

- [ ] **Step 5: Commit**

```bash
git add vera/tools/mcp_server.py tests/test_mcp_tools.py
git commit -m "feat: run_script, check_status y send_vera_command con errores accionables"
```

---

### Task 4: Screenshot del viewport (`request_screenshot`)

**Files:**
- Modify: `vera/tools/mcp_server.py`
- Test: `tests/test_mcp_tools.py`

Cómo funciona: el server manda al bridge un script que llama
`unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, "<nombre>.png")`.
Esa API es **asíncrona** (captura en los frames siguientes) y escribe en
`UE57/Saved/Screenshots/WindowsEditor/<nombre>.png`, así que después del exec
se hace polling del archivo hasta `timeout`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_mcp_tools.py`:

```python
import threading
import time

from vera.tools.mcp_server import request_screenshot


def test_request_screenshot_returns_path_when_file_appears(fake_bridge, tmp_path):
    captured = {}

    def handler(payload):
        captured["script"] = payload["script"]
        # Simula la escritura asíncrona de UE: el PNG aparece 0.3s después
        name = payload["script"].split('"')[-2]  # último string literal = nombre

        def write_later():
            time.sleep(0.3)
            (tmp_path / name).write_bytes(b"\x89PNG fake")

        threading.Thread(target=write_later, daemon=True).start()
        return {"success": True, "output": ""}

    fake_bridge["handler"] = handler
    path = request_screenshot(
        port=fake_bridge["port"], screenshots_dir=tmp_path, timeout=5.0
    )
    assert path is not None
    assert path.exists()
    assert "take_high_res_screenshot" in captured["script"]


def test_request_screenshot_returns_none_if_file_never_appears(fake_bridge, tmp_path):
    fake_bridge["handler"] = lambda p: {"success": True, "output": ""}
    path = request_screenshot(
        port=fake_bridge["port"], screenshots_dir=tmp_path, timeout=0.5
    )
    assert path is None


def test_request_screenshot_bridge_down_returns_none(tmp_path):
    path = request_screenshot(port=1, screenshots_dir=tmp_path, timeout=0.5)
    assert path is None
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'request_screenshot'`

- [ ] **Step 3: Implementar `request_screenshot`**

Agregar a `vera/tools/mcp_server.py` (los imports `time`/`uuid` van arriba con los demás):

```python
import time
import uuid

SCREENSHOTS_DIR = UE_PROJECT_DIR / "Saved" / "Screenshots" / "WindowsEditor"

_SCREENSHOT_SCRIPT = (
    "import unreal\n"
    'unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, "{name}")\n'
    'print("screenshot solicitado: {name}")'
)


def request_screenshot(timeout=20.0, port=None, screenshots_dir=None):
    """Pide una captura del viewport y espera a que el PNG aparezca en disco.

    Devuelve el Path del PNG, o None si falló (bridge caído o el archivo
    nunca apareció). take_high_res_screenshot es asíncrona: UE escribe el
    archivo unos frames después de ejecutar el script.
    """
    target_dir = Path(screenshots_dir) if screenshots_dir else SCREENSHOTS_DIR
    name = f"vera_{uuid.uuid4().hex[:8]}.png"

    result = run_script(_SCREENSHOT_SCRIPT.format(name=name), timeout=15.0, port=port)
    if result.get("success") is False:
        return None

    target = target_dir / name
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target.exists() and target.stat().st_size > 0:
            return target
        time.sleep(0.25)
    return None
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add vera/tools/mcp_server.py tests/test_mcp_tools.py
git commit -m "feat: request_screenshot captura el viewport y espera el PNG"
```

---

### Task 5: Wiring FastMCP + registro en Claude Code

**Files:**
- Modify: `vera/tools/mcp_server.py` (agregar tools + main)
- Modify: `pyproject.toml`
- Create: `.mcp.json` (raíz del repo)

- [ ] **Step 1: Instalar el SDK y declararlo**

Run: `pip install "mcp>=1.2.0"`
Expected: instala sin error.

En `pyproject.toml`, dentro de `dependencies = [...]`, agregar al final de la lista:

```toml
    "mcp>=1.2.0",
```

- [ ] **Step 2: Agregar el wiring FastMCP**

Al final de `vera/tools/mcp_server.py`:

```python
def main():
    # Import adentro de main(): los tests importan este módulo sin necesitar el SDK
    from mcp.server.fastmcp import FastMCP, Image

    mcp = FastMCP("vera-ue")

    @mcp.tool()
    def ue_exec(script: str, timeout: float = 60.0) -> str:
        """Ejecuta Python en el main thread del editor de Unreal (módulo `unreal`
        disponible). Devuelve stdout capturado, o el traceback si el script falló."""
        result = run_script(script, timeout=timeout)
        if result.get("success") is False:
            return f"ERROR:\n{result.get('error', result.get('output', 'sin detalle'))}"
        return result.get("output", "") or "(sin output)"

    @mcp.tool()
    def ue_screenshot() -> Image:
        """Captura el viewport activo del editor y devuelve el PNG."""
        path = request_screenshot()
        if path is None:
            raise RuntimeError(
                "No se pudo capturar el viewport. " + BRIDGE_DOWN_MSG
                + " Si el bridge está OK, mirá ue_log(100)."
            )
        return Image(data=path.read_bytes(), format="png")

    @mcp.tool()
    def ue_log(lines: int = 100) -> str:
        """Últimas N líneas del Output Log del editor (lee el archivo directo:
        funciona aunque el editor esté colgado)."""
        return tail_log(LOG_PATH, lines=lines)

    @mcp.tool()
    def ue_status() -> dict:
        """Estado del bridge (9878) y del backend VERA (9880), con versión del engine."""
        return check_status()

    @mcp.tool()
    def vera_command(text: str) -> str:
        """Comando de alto nivel al pipeline de agentes VERA (ManagerAgent → recetas)."""
        result = send_vera_command(text)
        return result.get("message", str(result))

    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verificar que el server arranca**

Run (PowerShell): `python -c "from vera.tools import mcp_server; mcp_server  # import ok"; echo listo`
Expected: `listo` sin traceback.

Run: `python -m vera.tools.mcp_server --help` no existe como flag — en su lugar, verificar arranque stdio con timeout corto:
`$p = Start-Process python -ArgumentList "-m","vera.tools.mcp_server" -PassThru -NoNewWindow; Start-Sleep 3; if (-not $p.HasExited) { "server vivo (stdio esperando)"; Stop-Process $p.Id } else { "MURIO al arrancar - revisar" }`
Expected: `server vivo (stdio esperando)`

- [ ] **Step 4: Crear `.mcp.json`**

`.mcp.json` (en `E:\PCW\VERA\`):

```json
{
  "mcpServers": {
    "vera-ue": {
      "command": "python",
      "args": ["-m", "vera.tools.mcp_server"],
      "env": {
        "VERA_UE_PROJECT_DIR": "E:/PCW/VERA/UE57"
      }
    }
  }
}
```

- [ ] **Step 5: Correr TODOS los tests**

Run: `python -m pytest tests/test_ue_conn.py tests/test_mcp_tools.py -v`
Expected: 16 passed

- [ ] **Step 6: Commit**

```bash
git add vera/tools/mcp_server.py pyproject.toml .mcp.json
git commit -m "feat: servidor MCP vera-ue con ue_exec/ue_screenshot/ue_log/ue_status/vera_command"
```

---

### Task 6: Bridge endurecido + auto-start en el editor

**Files:**
- Create: `UE57/Content/Python/vera_bridge.py`
- Create: `UE57/Content/Python/init_unreal.py`
- Delete: `vera/tools/ue_bridge_server.py`
- Test: `tests/test_vera_bridge.py`

Cambios vs. el bridge viejo: respuesta terminada en `\n` (framing simétrico),
espera del resultado con `threading.Event` en vez de busy-wait sobre un dict,
y auto-start desactivable para tests (`VERA_BRIDGE_NO_AUTOSTART`).

- [ ] **Step 1: Escribir el test que falla**

`tests/test_vera_bridge.py`:

```python
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
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_vera_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera_bridge'`

- [ ] **Step 3: Implementar `vera_bridge.py`**

`UE57/Content/Python/vera_bridge.py`:

```python
"""VERA Bridge — corre DENTRO del editor de Unreal (auto-arranca vía init_unreal.py).

Escucha en 127.0.0.1:9878. Recibe {"script": "..."} (JSON + newline) y ejecuta
el script en el MAIN THREAD del editor vía slate tick callback — tocar la API
de `unreal` desde un hilo de red crashea el editor. Responde JSON + newline:
{"success": bool, "output": str, "error"?: str}.

Solo stdlib. Corre en el Python embebido de Unreal.
"""
import json
import os
import queue
import socket
import threading
import traceback
import uuid

import unreal

HOST = "127.0.0.1"
PORT = 9878

# Cola de (task_id, script) hacia el main thread; resultados por task_id
_task_queue = queue.Queue()
_results = {}
_result_events = {}


def _execute_on_main_thread(task_id, script):
    """Corre en el main thread (llamado desde el slate tick)."""
    output_lines = []
    import builtins

    original_print = builtins.print

    def capture_print(*args, **kwargs):
        line = " ".join(str(a) for a in args)
        output_lines.append(line)
        unreal.log("[VERA] " + line)

    try:
        builtins.print = capture_print
        try:
            exec(script, {"unreal": unreal})  # noqa: S102
            _results[task_id] = {"success": True, "output": "\n".join(output_lines)}
        except Exception:
            _results[task_id] = {
                "success": False,
                "output": "\n".join(output_lines),
                "error": traceback.format_exc(),
            }
    finally:
        builtins.print = original_print
        _result_events[task_id].set()


def slate_tick_callback(delta_time):
    """Registrado en el slate post-tick: drena la cola en el main thread."""
    try:
        task_id, script = _task_queue.get_nowait()
    except queue.Empty:
        return
    _execute_on_main_thread(task_id, script)


def _handle_client(conn, addr):
    try:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        payload = json.loads(data.decode("utf-8").strip())
        script = payload.get("script", "")

        task_id = str(uuid.uuid4())
        event = threading.Event()
        _result_events[task_id] = event
        _task_queue.put((task_id, script))

        # Espera al main thread (el cliente maneja su propio timeout)
        event.wait()
        result = _results.pop(task_id)
        _result_events.pop(task_id, None)

        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))
    except Exception as e:
        unreal.log_error("VERA Bridge error: " + str(e))
    finally:
        conn.close()


def _serve(server):
    while True:
        conn, addr = server.accept()
        threading.Thread(target=_handle_client, args=(conn, addr), daemon=True).start()


def start(port=PORT):
    """Arranca el server en un hilo daemon. Devuelve el puerto real (útil con port=0)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen(5)
    actual_port = server.getsockname()[1]
    threading.Thread(target=_serve, args=(server,), daemon=True).start()
    unreal.log("VERA Bridge escuchando en %s:%s (main-thread safe)" % (HOST, actual_port))
    return actual_port


if not os.environ.get("VERA_BRIDGE_NO_AUTOSTART"):
    unreal.register_slate_post_tick_callback(slate_tick_callback)
    start()
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_vera_bridge.py -v`
Expected: 2 passed

- [ ] **Step 5: Crear `init_unreal.py`**

`UE57/Content/Python/init_unreal.py`:

```python
"""Unreal ejecuta este archivo automáticamente al abrir el proyecto
(convención init_unreal.py del Python Editor Script Plugin)."""
import unreal

try:
    import vera_bridge  # noqa: F401  — TCP bridge para Claude Code/VERA (puerto 9878)
except Exception as e:
    unreal.log_error("[VERA] No se pudo iniciar el bridge: " + str(e))

try:
    import vera_ui  # noqa: F401  — inyecta el botón VERA en la toolbar
except Exception as e:
    unreal.log_error("[VERA] No se pudo cargar la UI: " + str(e))
```

- [ ] **Step 6: Borrar el bridge viejo y correr todo**

```bash
git rm vera/tools/ue_bridge_server.py
```

Run: `python -m pytest tests/ -v`
Expected: los 18 tests nuevos pasan (si los tests preexistentes `test_manager.py`/`test_perception.py`/`test_python_agent.py` fallan por razones ajenas — p. ej. requieren API keys — anotarlo y no tocarlos en esta iteración; correr entonces `python -m pytest tests/test_ue_conn.py tests/test_mcp_tools.py tests/test_vera_bridge.py -v`).

- [ ] **Step 7: Commit**

```bash
git add UE57/Content/Python/vera_bridge.py UE57/Content/Python/init_unreal.py tests/test_vera_bridge.py
git commit -m "feat: bridge endurecido con framing newline y auto-start via init_unreal.py"
```

---

### Task 7: Documentación + smoke test de integración

**Files:**
- Create: `docs/mcp-bridge.md`

- [ ] **Step 1: Escribir la doc**

`docs/mcp-bridge.md`:

```markdown
# VERA MCP Bridge — uso

Claude Code controla el editor de Unreal vía el server MCP `vera-ue` (registrado
en `.mcp.json`). Herramientas: `ue_exec`, `ue_screenshot`, `ue_log`, `ue_status`,
`vera_command`.

## Requisitos

1. Proyecto `UE57` abierto en el editor (el bridge auto-arranca vía
   `Content/Python/init_unreal.py`; requiere el plugin "Python Editor Script
   Plugin" habilitado).
2. `pip install -e .[dev]` en `E:\PCW\VERA` (instala `mcp`).
3. Opcional para `vera_command`: backend corriendo — `python -m vera.core.vera_server`.

## Smoke test (manual, con el editor abierto)

Desde una sesión de Claude Code en este repo:

1. `ue_status` → bridge online, versión del engine visible.
2. `ue_exec("import unreal\nprint(unreal.SystemLibrary.get_engine_version())")`
   → imprime la versión.
3. `ue_screenshot()` → devuelve un PNG del viewport.
4. `ue_log(50)` → últimas líneas del Output Log.

## Test de aceptación — "loop con ojos"

Pedirle a Claude Code: *"Construí un puente de vidrio entre las dos plataformas
y verificá visualmente que quedó bien."* Claude debe: ejecutar scripts con
`ue_exec`, mirar el resultado con `ue_screenshot`, diagnosticar con `ue_log`
si algo falla, y corregir sin intervención del usuario.

## Variables de entorno

| Variable | Default | Para qué |
|---|---|---|
| `VERA_UE_PROJECT_DIR` | `<repo>/UE57` | Localiza `Saved/Logs` y `Saved/Screenshots` |
| `VERA_BRIDGE_PORT` | `9878` | Puerto del bridge en el editor |
| `VERA_BACKEND_PORT` | `9880` | Puerto del backend de agentes |
| `VERA_BRIDGE_NO_AUTOSTART` | (vacío) | Si está seteada, `vera_bridge` no auto-arranca (tests) |
```

- [ ] **Step 2: Commit**

```bash
git add docs/mcp-bridge.md
git commit -m "docs: setup y smoke test del VERA MCP Bridge"
```

- [ ] **Step 3: Smoke test real (requiere editor abierto — coordinar con el usuario)**

Con el editor UE57 abierto y Claude Code reiniciado (para que cargue `.mcp.json`):
ejecutar los 4 pasos del smoke test de la doc. Si `ue_status` da bridge offline,
verificar en el Output Log del editor que aparezca "VERA Bridge escuchando".

Expected: los 4 pasos pasan; el PNG del viewport es visible para Claude.

---

## Self-review (hecho al escribir el plan)

- **Cobertura del spec:** 5 herramientas (Tasks 3-5), auto-start (Task 6), framing (Tasks 1 y 6), screenshot helper (Task 4), `.mcp.json` (Task 5), errores accionables (Task 3), unit tests con fake bridge (Tasks 1-4, 6), smoke test documentado (Task 7). Fuera de alcance respetado: ni UI PySide6 ni cambio de LLM.
- **Placeholders:** ninguno — todo paso con código lo muestra completo.
- **Consistencia de tipos:** `send_json(port, payload, timeout, host)` usado igual en Tasks 1/3/4; `run_script(script, timeout, port)` igual en 3/4/5; `start(port)` del bridge devuelve int usado por el test de Task 6.
