# VERA UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ventana de chat de VERA rediseñada: UI completa en HTML (QWebEngineView), timeline de progreso de agentes en vivo vía protocolo streaming, markdown, historial JSONL e imágenes del viewport.

**Architecture:** El backend (`vera_server.py`, puerto 9880) pasa de respuesta única a stream de líneas JSON (`progress`/`image`/`error` + `final`), alimentado por `Blackboard.report_progress`. La ventana Qt conserva solo el marco; el interior es un `QWebEngineView` que carga `vera_chat/index.html` — eventos Python→JS por `runJavaScript(veraChat.dispatch(...))`, comandos JS→Python por `QWebChannel`. Fallback automático a la UI de burbujas actual si WebEngine falta.

**Tech Stack:** Python 3.11 (embebido UE) / 3.14 (tests), PySide6 6.11 (QtWebEngineWidgets), marked.js 12.0.2 + highlight.js 11.9.0 vendorizados, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-vera-ui-redesign-design.md`
**Working dir para comandos:** `E:\PCW\VERA`. Tests: `python -m pytest`.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `vera/core/blackboard.py` (modificar) | + `progress_callback` / `report_progress` / `report_image` — único punto de emisión. |
| `vera/core/vera_server.py` (modificar) | Streaming: conecta el callback al socket del cliente activo, emite `final`. Server inyectable para tests. |
| `vera/core/manager_agent.py` (modificar) | Helper `_progress()` + emisiones en ruteo y delegación. |
| `vera/tools/ue_conn.py` (modificar) | + `send_json_stream()` — lee líneas hasta `final`. |
| `vera/tools/mcp_server.py` (modificar) | `send_vera_command` consume el stream (devuelve final + eventos). |
| `UE57/Content/Python/vera_chat/index.html` + `chat.js` + `chat.css` (crear) | La UI: header con chips, chat con timeline, input con mic. |
| `UE57/Content/Python/vera_chat/dev.html` (crear) | Harness: misma UI + botones que inyectan eventos falsos (desarrollo sin Unreal). |
| `UE57/Content/Python/vera_chat/vendor/` (crear) | marked.min.js, highlight.min.js, github-dark.min.css (pinneados, sin CDN en runtime). |
| `UE57/Content/Python/vera_history.py` (crear) | Historial JSONL puro (append/load), testeable sin unreal. |
| `UE57/Content/Python/vera_ui.py` (modificar) | Shell: QWebEngineView + QWebChannel + hilo lector del stream + fallback a burbujas. |
| `UE57/Content/Python/init_unreal.py` (modificar) | `AA_ShareOpenGLContexts` antes de cualquier QApplication. |
| `tests/test_blackboard_progress.py`, `tests/test_vera_server_stream.py`, `tests/test_ue_conn_stream.py`, `tests/test_vera_history.py` (crear) | Unit tests sin Unreal. |

Nota de entorno: `vera_chat/` y `vera_history.py` corren en el Python embebido de UE (3.11) — stdlib only. Los tests corren con Python 3.14 del sistema. `tests/conftest.py` ya tiene `fake_bridge`/`garbage_bridge`.

---

### Task 1: `Blackboard.report_progress`

**Files:**
- Modify: `vera/core/blackboard.py` (agregar al final de `__init__` y nuevos métodos)
- Test: `tests/test_blackboard_progress.py` (crear)

- [ ] **Step 1: Test que falla**

`tests/test_blackboard_progress.py`:

```python
from vera.core.blackboard import Blackboard


def test_report_progress_without_callback_is_noop():
    bb = Blackboard()
    bb.report_progress("Manager", "routing")  # no debe lanzar


def test_report_progress_calls_callback_with_event():
    bb = Blackboard()
    events = []
    bb.progress_callback = events.append
    bb.report_progress("Architect", "plan: 3 pasos")
    assert events == [{"type": "progress", "agent": "Architect", "msg": "plan: 3 pasos"}]


def test_report_image_emits_image_event():
    bb = Blackboard()
    events = []
    bb.progress_callback = events.append
    bb.report_image("E:/shots/vera_x.png")
    assert events == [{"type": "image", "path": "E:/shots/vera_x.png"}]


def test_broken_callback_does_not_break_agents():
    bb = Blackboard()

    def boom(event):
        raise RuntimeError("ui desconectada")

    bb.progress_callback = boom
    bb.report_progress("QA", "testing")  # no debe propagar
```

- [ ] **Step 2: Verificar FAIL**

Run: `python -m pytest tests/test_blackboard_progress.py -v`
Expected: FAIL — `AttributeError: 'Blackboard' object has no attribute 'report_progress'`

- [ ] **Step 3: Implementar**

En `vera/core/blackboard.py`, dentro de `__init__` (después de `self._context_timestamps = {}`):

```python
        # Canal de progreso hacia la UI (lo conecta vera_server por conexión)
        self.progress_callback = None
```

Y como métodos nuevos de la clase:

```python
    def report_progress(self, agent: str, msg: str) -> None:
        """Emite un evento de progreso hacia la UI. Sin callback conectado es no-op;
        un callback roto jamás interrumpe a los agentes."""
        self._emit({"type": "progress", "agent": agent, "msg": msg})

    def report_image(self, path: str) -> None:
        """Emite una imagen (captura del viewport) hacia la UI."""
        self._emit({"type": "image", "path": path})

    def _emit(self, event: dict) -> None:
        cb = self.progress_callback
        if cb is None:
            return
        try:
            cb(event)
        except Exception:
            logger.warning("[Blackboard] progress_callback falló; se ignora", exc_info=True)
```

- [ ] **Step 4: Verificar PASS**

Run: `python -m pytest tests/test_blackboard_progress.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add vera/core/blackboard.py tests/test_blackboard_progress.py
git commit -m "feat: Blackboard.report_progress como canal de eventos hacia la UI"
```

---

### Task 2: Streaming en `vera_server.py`

**Files:**
- Modify: `vera/core/vera_server.py` (reescritura de `__init__`, `handle_client`, `start`)
- Test: `tests/test_vera_server_stream.py` (crear)

El protocolo pasa de 1 línea de respuesta a N: `progress`/`image`/`error` y SIEMPRE una `final` al final, todas JSON+`\n`. Asunción documentada: un solo cliente UI activo a la vez (el callback del blackboard apunta a la conexión en curso).

- [ ] **Step 1: Tests que fallan**

`tests/test_vera_server_stream.py`:

```python
import json
import socket
import threading

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


def test_callback_cleared_after_command(server_factory):
    port = server_factory()
    _send_and_read_events(port, "build")
    # tras terminar, el blackboard no retiene el socket muerto
    # (accedemos al server vía el factory: el último creado)
```

Borrar el cuerpo vacío del último test y reemplazarlo por esta versión completa (verificación real):

```python
def test_callback_cleared_after_command():
    bb = Blackboard()
    srv = VeraServer(port=0, blackboard=bb, manager=FakeManager(bb))
    port = srv.start_in_thread()
    try:
        _send_and_read_events(port, "build")
        assert bb.progress_callback is None
    finally:
        srv.stop()
```

- [ ] **Step 2: Verificar FAIL**

Run: `python -m pytest tests/test_vera_server_stream.py -v`
Expected: FAIL — `TypeError: VeraServer.__init__() got an unexpected keyword argument 'port'`... (la firma actual es `(self, host, port)` sin inyección; cualquier error de construcción cuenta como fail esperado)

- [ ] **Step 3: Reescribir `vera/core/vera_server.py`**

Contenido completo del archivo:

```python
import json
import logging
import os
import socket
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class VeraServer:
    """Backend de agentes de VERA. Protocolo streaming: por cada comando responde
    N líneas JSON (progress/image/error) y SIEMPRE una final:
        {"type":"final","status":"success"|"error","msg":"..."}
    Asunción: un solo cliente UI activo a la vez (progress_callback apunta a la
    conexión en curso)."""

    def __init__(self, host="127.0.0.1", port=9880, blackboard=None, manager=None):
        self.host = host
        self.port = port
        # Inyectables para tests; en producción se crean los reales.
        if blackboard is None:
            from vera.core.blackboard import Blackboard
            blackboard = Blackboard()
        self.blackboard = blackboard
        if manager is None:
            from vera.core.manager_agent import ManagerAgent
            manager = ManagerAgent(self.blackboard)
        self.manager = manager
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stop = threading.Event()

    # ---- emisión ----

    def _make_emitter(self, conn, lock):
        def emit(event):
            with lock:
                conn.sendall((json.dumps(event) + "\n").encode("utf-8"))
        return emit

    def handle_client(self, conn, addr):
        logger.info(f"[VeraServer] Connection from {addr}")
        lock = threading.Lock()
        emit = self._make_emitter(conn, lock)
        try:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data.strip():
                return

            payload = json.loads(data.decode("utf-8").strip())
            command = payload.get("command", "")
            if not command:
                emit({"type": "final", "status": "error", "msg": "Comando vacío."})
                return

            if command.strip().lower() in ("hello world", "hello world!"):
                emit({"type": "final", "status": "success",
                      "msg": "Hello World! The VERA-Unreal communication bridge is online."})
                return

            self.blackboard.progress_callback = emit
            try:
                success = self.manager.execute_command(command)
                if success:
                    emit({"type": "final", "status": "success", "msg": "Done."})
                else:
                    emit({"type": "final", "status": "error",
                          "msg": "No pude completar el comando. Revisá la timeline y los logs del servidor."})
            except Exception as llm_error:
                logger.error(f"[VeraServer] Error: {llm_error}")
                emit({"type": "final", "status": "error",
                      "msg": f"Error procesando el comando: {llm_error}"})
            finally:
                self.blackboard.progress_callback = None
        except Exception as e:
            logger.error(f"[VeraServer] Error handling client: {e}")
        finally:
            conn.close()

    # ---- ciclo de vida ----

    def _load_env(self):
        if not os.environ.get("GEMINI_API_KEY"):
            env_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        if line.startswith("GEMINI_API_KEY="):
                            os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip()

    def _bind(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.port = self.server_socket.getsockname()[1]
        return self.port

    def _accept_loop(self):
        self.server_socket.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, addr = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

    def start_in_thread(self):
        """Para tests: bindea (port=0 → efímero) y acepta en un hilo. Devuelve el puerto."""
        port = self._bind()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return port

    def stop(self):
        self._stop.set()
        self.server_socket.close()

    def start(self):
        """Modo producción: bloqueante."""
        self._load_env()
        self._bind()
        logger.info(f"[VeraServer] VERA streaming server on {self.host}:{self.port}")
        self._accept_loop()


if __name__ == "__main__":
    VeraServer().start()
```

- [ ] **Step 4: Verificar PASS**

Run: `python -m pytest tests/test_vera_server_stream.py tests/test_blackboard_progress.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add vera/core/vera_server.py tests/test_vera_server_stream.py
git commit -m "feat: vera_server emite stream de eventos de progreso + final"
```

---

### Task 3: Cliente streaming (`ue_conn` + MCP `vera_command`)

**Files:**
- Modify: `vera/tools/ue_conn.py` (agregar `send_json_stream` al final)
- Modify: `vera/tools/mcp_server.py` (función `send_vera_command`)
- Test: `tests/test_ue_conn_stream.py` (crear)

- [ ] **Step 1: Tests que fallan**

`tests/test_ue_conn_stream.py`:

```python
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
```

- [ ] **Step 2: Verificar FAIL**

Run: `python -m pytest tests/test_ue_conn_stream.py -v`
Expected: FAIL — `ImportError: cannot import name 'send_json_stream'`

- [ ] **Step 3: Implementar**

Agregar al final de `vera/tools/ue_conn.py`:

```python
def send_json_stream(port, payload, timeout=DEFAULT_TIMEOUT, host="127.0.0.1", on_event=None):
    """Envía un payload y lee un STREAM de líneas JSON hasta el evento
    {"type":"final"} (o cierre de conexión). Devuelve la lista de eventos.
    on_event(evento) se invoca por cada línea a medida que llega."""
    events = []
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except ValueError as e:
                        raise UEConnectionError(f"evento malformado: {e}") from e
                    events.append(event)
                    if on_event is not None:
                        try:
                            on_event(event)
                        except Exception:
                            pass
                    if event.get("type") == "final":
                        return events
    except socket.timeout as e:
        raise UETimeoutError(f"stream sin final en {timeout:.0f}s") from e
    except OSError as e:
        raise UEConnectionError(str(e)) from e
    if not events:
        raise UEConnectionError("el servidor cerró sin enviar eventos")
    return events
```

Nota: igual que en `send_json`, el `socket.timeout` del connect en Windows debe mapear a `UEConnectionError` — copiar el patrón de dos fases de `send_json` si los tests de puerto cerrado fallan con `UETimeoutError` (leer `send_json` actual antes de implementar).

Reemplazar `send_vera_command` en `vera/tools/mcp_server.py`:

```python
def send_vera_command(text, timeout=300.0, port=None):
    """Comando de alto nivel al pipeline de agentes (protocolo streaming).
    Devuelve el evento final + la lista completa en "events"."""
    from vera.tools.ue_conn import send_json_stream
    try:
        events = send_json_stream(port or BACKEND_PORT, {"command": text}, timeout=timeout)
    except UEConnectionError:
        return {"status": "error", "message": BACKEND_DOWN_MSG, "events": []}
    except UETimeoutError:
        return {
            "status": "error",
            "message": f"El backend no respondió en {timeout:.0f}s. Mirá sus logs.",
            "events": [],
        }
    final = events[-1]
    return {
        "status": final.get("status", "error"),
        "msg": final.get("msg", ""),
        "message": final.get("msg", ""),  # compat con el tool vera_command existente
        "events": events,
    }
```

- [ ] **Step 4: Verificar PASS (incluye no-regresión)**

Run: `python -m pytest tests/test_ue_conn_stream.py tests/test_mcp_tools.py tests/test_ue_conn.py -v`
Expected: los 4 nuevos pasan. ATENCIÓN: `test_send_vera_command` en `test_mcp_tools.py` usa `fake_bridge` que responde UNA línea `{"status","message"}` sin `type:final` — ese test va a colgar/fallar con el nuevo protocolo. Actualizarlo así (reemplazar el test existente):

```python
def test_send_vera_command(fake_bridge):
    # El backend ahora responde streaming; el fake emite solo la final
    fake_bridge["handler"] = lambda p: {
        "type": "final", "status": "success", "msg": f"eco: {p['command']}"}
    result = send_vera_command("hello world", port=fake_bridge["port"])
    assert result["status"] == "success"
    assert "hello world" in result["msg"]
```

Expected final: todos los tests de los 3 archivos pasan.

- [ ] **Step 5: Commit**

```bash
git add vera/tools/ue_conn.py vera/tools/mcp_server.py tests/test_ue_conn_stream.py tests/test_mcp_tools.py
git commit -m "feat: cliente streaming send_json_stream; vera_command consume el stream"
```

---

### Task 4: Emisiones de progreso en `ManagerAgent`

**Files:**
- Modify: `vera/core/manager_agent.py`

Sin unit test propio: el constructor de `ManagerAgent` instancia clientes LLM y sub-agentes con dependencias externas (API keys). La cobertura viene de `test_vera_server_stream.py` (protocolo) y del smoke test (Task 9). Verificación de esta task: la suite completa sigue verde + revisión de código.

- [ ] **Step 1: Agregar helper** (después de `__init__`, antes de `_route_command`):

```python
    def _progress(self, agent: str, msg: str) -> None:
        self.blackboard.report_progress(agent, msg)
```

- [ ] **Step 2: Insertar emisiones** (anclas = líneas existentes con `logger.info`):

| Ancla existente | Insertar inmediatamente después |
|---|---|
| `logger.info(f"[Manager] Received command: '{command}'")` | `self._progress("Manager", "command received")` |
| `logger.info(f"[Manager] Cache HIT! Replaying recipe...")` | `self._progress("Manager", "cache hit — replaying recipe")` |
| `logger.info("[Manager] Cache MISS. Delegating task to Crew...")` | `self._progress("Manager", "thinking…")` |
| `print(f"\n[VERA] 🤔 {question}")` (rama ambigua) | `self._progress("Manager", f"need clarification: {question}")` |
| `logger.info(f"[Manager] Route selected: {route}")` | `self._progress("Manager", f"routed to {route.title()}")` |
| `if route == "ARCHITECT":` (primera línea del branch) | `self._progress("Architect", "planning project")` |
| `logger.info("[Manager] LLM Routed to Blueprint Generator.")` | `self._progress("Blueprint", "generating blueprint")` |
| `logger.info("[Manager] LLM Routed to QA Agent.")` | `self._progress("QA", "running tests")` |
| `logger.info("[Manager] LLM Routed to GitAgent.")` | `self._progress("Git", "version control")` |
| `logger.info("[Manager] LLM Routed to ArtCriticAgent.")` | `self._progress("Critic", "analyzing scene")` |
| `logger.info("[Manager] LLM Routed to LogQAAgent.")` | `self._progress("LogQA", "scanning editor log")` |
| `logger.info("[Manager] LLM Routed to UE Python Agent.")` | `self._progress("Python", "writing & executing script")` |
| `logger.info("[Manager] LLM Routed to Perception/UI Agent.")` | `self._progress("Perception", "reading the screen")` |

(Cuidar la indentación de cada inserción al nivel del ancla. Leer el archivo completo primero.)

- [ ] **Step 3: Verificar no-regresión**

Run: `python -m pytest tests/ --ignore=tests/test_manager.py --ignore=tests/test_perception.py --ignore=tests/test_python_agent.py -q`
Expected: todos pasan (los 3 ignorados requieren API keys — preexistente).
Además: `python -c "import ast; ast.parse(open('vera/core/manager_agent.py', encoding='utf-8').read()); print('sintaxis ok')"`

- [ ] **Step 4: Commit**

```bash
git add vera/core/manager_agent.py
git commit -m "feat: ManagerAgent emite progreso por agente en cada ruta"
```

---

### Task 5: Historial JSONL (`vera_history.py`)

**Files:**
- Create: `UE57/Content/Python/vera_history.py`
- Test: `tests/test_vera_history.py`

- [ ] **Step 1: Tests que fallan**

`tests/test_vera_history.py`:

```python
import json
import os
import sys

import pytest

# Importar desde la carpeta del proyecto UE (mismo patrón que test_vera_bridge)
BRIDGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "UE57", "Content", "Python")
sys.path.insert(0, BRIDGE_DIR)

import vera_history  # noqa: E402


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "chat_history.jsonl"
    vera_history.append_event(path, {"type": "user", "msg": "hola"})
    vera_history.append_event(path, {"type": "final", "status": "success", "msg": "done"})
    events = vera_history.load_recent(path)
    assert events == [
        {"type": "user", "msg": "hola"},
        {"type": "final", "status": "success", "msg": "done"},
    ]


def test_load_recent_caps_at_n(tmp_path):
    path = tmp_path / "h.jsonl"
    for i in range(300):
        vera_history.append_event(path, {"type": "user", "msg": str(i)})
    events = vera_history.load_recent(path, n=200)
    assert len(events) == 200
    assert events[-1]["msg"] == "299"


def test_load_missing_file_returns_empty(tmp_path):
    assert vera_history.load_recent(tmp_path / "no.jsonl") == []


def test_corrupt_lines_are_skipped(tmp_path):
    path = tmp_path / "h.jsonl"
    path.write_text('{"type":"user","msg":"ok"}\nBASURA NO JSON\n', encoding="utf-8")
    events = vera_history.load_recent(path)
    assert events == [{"type": "user", "msg": "ok"}]
```

- [ ] **Step 2: Verificar FAIL**

Run: `python -m pytest tests/test_vera_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera_history'`

- [ ] **Step 3: Implementar**

`UE57/Content/Python/vera_history.py`:

```python
"""Historial del chat de VERA — JSONL append-only, mismo schema que el protocolo.
Stdlib only (corre en el Python embebido de Unreal)."""
import json
import os


def append_event(path, event):
    """Appendea un evento como línea JSON. Crea el directorio si falta."""
    path = os.fspath(path)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_recent(path, n=200):
    """Últimos n eventos. Líneas corruptas se saltan (el historial nunca
    impide abrir la ventana)."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events[-n:]
```

- [ ] **Step 4: Verificar PASS**

Run: `python -m pytest tests/test_vera_history.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add UE57/Content/Python/vera_history.py tests/test_vera_history.py
git commit -m "feat: historial JSONL del chat (append/load, tolerante a corrupcion)"
```

---

### Task 6: UI HTML (`vera_chat/`) + vendor + dev harness

**Files:**
- Create: `UE57/Content/Python/vera_chat/vendor/marked.min.js`, `vendor/highlight.min.js`, `vendor/github-dark.min.css`
- Create: `UE57/Content/Python/vera_chat/index.html`, `chat.css`, `chat.js`, `dev.html`

- [ ] **Step 1: Vendorizar librerías (pinneadas)**

```powershell
$d = "E:\PCW\VERA\UE57\Content\Python\vera_chat\vendor"
New-Item -ItemType Directory -Force $d
Invoke-WebRequest "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js" -OutFile "$d\marked.min.js"
Invoke-WebRequest "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js" -OutFile "$d\highlight.min.js"
Invoke-WebRequest "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/styles/github-dark.min.css" -OutFile "$d\github-dark.min.css"
```
Verificar: los 3 archivos > 10 KB cada uno.

- [ ] **Step 2: `index.html`**

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="vendor/github-dark.min.css">
<link rel="stylesheet" href="chat.css">
</head>
<body>
<div id="header">
  <div id="brand"><b>VERA</b><span id="status" class="off">● Offline</span></div>
  <div id="chips"></div>
</div>
<div id="chat"></div>
<div id="inputbar">
  <textarea id="input" rows="1" placeholder="Type an instruction…"></textarea>
  <button id="mic" title="Voice input">🎤</button>
  <button id="send" title="Send">➤</button>
</div>
<script src="vendor/marked.min.js"></script>
<script src="vendor/highlight.min.js"></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="chat.js"></script>
</body>
</html>
```

Nota: en `dev.html` (navegador normal) `qrc://` falla en silencio — `chat.js` ya lo contempla (`typeof QWebChannel === "undefined"`).

- [ ] **Step 3: `chat.css`** (tema GitHub-dark del mockup final aprobado)

```css
* { box-sizing: border-box; margin: 0; }
html, body { height: 100%; }
body { display: flex; flex-direction: column; background: #0d1117; color: #c9d1d9;
       font: 13px "Segoe UI", sans-serif; }

#header { background: #161b22; border-bottom: 1px solid #21262d; padding: 8px 12px; }
#brand { display: flex; justify-content: space-between; align-items: center;
         font-size: 14px; letter-spacing: .5px; }
#status { font-size: 11px; color: #3fb950; }
#status.off { color: #f85149; }
#chips { display: flex; gap: 6px; margin-top: 7px; flex-wrap: wrap; }
.chip { font-size: 10px; padding: 2px 9px; border-radius: 9px;
        background: #21262d; color: #8b949e; }
.chip.working { background: #9e6a0333; color: #e3b341; }
.chip.done { background: #1f6feb33; color: #79c0ff; }

#chat { flex: 1; overflow-y: auto; padding: 12px; }
#chat::-webkit-scrollbar { width: 9px; }
#chat::-webkit-scrollbar-thumb { background: #21262d; border-radius: 5px; }

.bubble { border-radius: 12px; padding: 8px 12px; margin: 8px 0;
          max-width: 86%; width: fit-content; word-wrap: break-word; }
.bubble.user { background: #1f6feb; color: #fff; margin-left: auto;
               border-bottom-right-radius: 2px; }
.bubble.vera { background: #161b22; border: 1px solid #21262d;
               border-bottom-left-radius: 2px; }
.bubble.error { background: #2d1418; border: 1px solid #6e2c34; color: #f0a8ae; }

.tl-item { border-left: 2px solid #30363d; padding: 2px 0 2px 10px;
           font-size: 12px; color: #8b949e; }
.tl-item.working { color: #e3b341; }
.tl-item.interrupted { color: #f85149; }
.tl-item b { color: #c9d1d9; }

.bubble .md p { margin: 4px 0; }
.bubble .md pre { background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
                  padding: 8px; overflow-x: auto; margin: 6px 0; }
.bubble .md code { font-family: Consolas, monospace; font-size: 12px; }

.shot { display: block; width: 220px; border-radius: 6px; margin: 8px 0 4px 10px;
        cursor: pointer; border: 1px solid #21262d; }

#inputbar { display: flex; gap: 8px; padding: 10px 12px; align-items: flex-end;
            background: #161b22; border-top: 1px solid #21262d; }
#input { flex: 1; resize: none; background: #0d1117; color: #c9d1d9;
         border: 1px solid #21262d; border-radius: 8px; padding: 8px 12px;
         font: 13px "Segoe UI", sans-serif; max-height: 110px; outline: none; }
#input:focus { border-color: #1f6feb; }
#inputbar button { background: none; border: 1px solid #21262d; border-radius: 8px;
                   color: #8b949e; font-size: 15px; padding: 7px 11px; cursor: pointer; }
#inputbar button:hover { border-color: #1f6feb; color: #79c0ff; }
#mic.recording { color: #f85149; border-color: #f85149;
                 animation: pulse 1.1s infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 10px #f8514966; } }
```

- [ ] **Step 4: `chat.js`** (API única: `veraChat.dispatch(evento)`; comandos hacia Python por QWebChannel)

```javascript
"use strict";

const AGENTS = ["Manager", "Architect", "Python", "Blueprint", "QA",
                "Perception", "Critic", "Git", "LogQA"];
let pybridge = null;          // objeto Python via QWebChannel (null en dev.html)
let currentTimeline = null;   // burbuja vera en curso (timeline activa)

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);

function scrollBottom() { const c = $("chat"); c.scrollTop = c.scrollHeight; }

function md(text) {
  const html = marked.parse(text || "");
  const div = document.createElement("div");
  div.className = "md";
  div.innerHTML = html;
  div.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));
  return div;
}

function bubble(cls) {
  const b = document.createElement("div");
  b.className = "bubble " + cls;
  $("chat").appendChild(b);
  return b;
}

function ensureTimeline() {
  if (!currentTimeline) currentTimeline = bubble("vera");
  return currentTimeline;
}

// ---------- chips ----------
function renderChips(working) {
  const chips = $("chips");
  chips.innerHTML = "";
  for (const a of AGENTS.slice(0, 5)) {
    const s = document.createElement("span");
    s.className = "chip" + (a === working ? " working" : "");
    s.textContent = a + (a === working ? " ●" : "");
    chips.appendChild(s);
  }
  const more = document.createElement("span");
  more.className = "chip";
  more.textContent = "+" + (AGENTS.length - 5);
  chips.appendChild(more);
}

// ---------- dispatch (único punto de entrada Python→JS) ----------
window.veraChat = {
  dispatch(e) {
    switch (e.type) {
      case "user": {
        currentTimeline = null;
        bubble("user").textContent = e.msg;
        renderChips("Manager");
        break;
      }
      case "progress": {
        const tl = ensureTimeline();
        tl.querySelectorAll(".tl-item.working")
          .forEach((el) => el.classList.remove("working"));
        const item = document.createElement("div");
        item.className = "tl-item working";
        item.innerHTML = "<b>" + e.agent + "</b> — " + e.msg;
        tl.appendChild(item);
        renderChips(e.agent);
        break;
      }
      case "image": {
        const img = document.createElement("img");
        img.className = "shot";
        img.src = "file:///" + String(e.path).replace(/\\/g, "/");
        img.onclick = () => pybridge && pybridge.open_image(e.path);
        ensureTimeline().appendChild(img);
        break;
      }
      case "final": {
        const tl = ensureTimeline();
        tl.querySelectorAll(".tl-item.working")
          .forEach((el) => el.classList.remove("working"));
        tl.appendChild(md(e.msg));
        if (e.status === "error") tl.classList.add("error");
        currentTimeline = null;
        renderChips(null);
        break;
      }
      case "error": {
        bubble("error").appendChild(md(e.msg));
        break;
      }
      case "interrupted": {
        const tl = ensureTimeline();
        const items = tl.querySelectorAll(".tl-item.working");
        items.forEach((el) => { el.classList.remove("working");
                                el.classList.add("interrupted"); });
        const note = document.createElement("div");
        note.className = "tl-item interrupted";
        note.textContent = "interrumpido — el backend dejó de responder";
        tl.appendChild(note);
        currentTimeline = null;
        renderChips(null);
        break;
      }
      case "status": {
        const st = $("status");
        st.textContent = e.online ? ("● Online · " + (e.version || "UE")) : "● Offline";
        st.className = e.online ? "" : "off";
        break;
      }
      case "history": {
        (e.events || []).forEach((ev) => window.veraChat.dispatch(ev));
        break;
      }
    }
    scrollBottom();
  },
};

// ---------- input ----------
function sendCurrent() {
  const text = $("input").value.trim();
  if (!text) return;
  $("input").value = "";
  $("input").style.height = "auto";
  window.veraChat.dispatch({ type: "user", msg: text });
  if (pybridge) pybridge.send_command(text);
}

$("send").onclick = sendCurrent;
$("input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendCurrent(); }
});
$("input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 110) + "px";
});

// Mic: solo estados visuales en esta iteración (Whisper = iteración aparte)
$("mic").onclick = function () { this.classList.toggle("recording"); };

// ---------- QWebChannel (ausente en dev.html → modo standalone) ----------
if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    pybridge = channel.objects.pybridge;
    pybridge.js_ready();
  });
}

renderChips(null);
```

- [ ] **Step 5: `dev.html`** (harness sin Unreal)

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="vendor/github-dark.min.css">
<link rel="stylesheet" href="chat.css">
<style>#devbar{position:fixed;top:4px;right:4px;z-index:9}#devbar button{font-size:10px}</style>
</head>
<body>
<div id="header">
  <div id="brand"><b>VERA</b><span id="status" class="off">● Offline</span></div>
  <div id="chips"></div>
</div>
<div id="chat"></div>
<div id="inputbar">
  <textarea id="input" rows="1" placeholder="Type an instruction…"></textarea>
  <button id="mic" title="Voice input">🎤</button>
  <button id="send" title="Send">➤</button>
</div>
<div id="devbar"><button onclick="demo()">▶ demo</button></div>
<script src="vendor/marked.min.js"></script>
<script src="vendor/highlight.min.js"></script>
<script src="chat.js"></script>
<script>
function demo() {
  const d = (e, ms) => setTimeout(() => veraChat.dispatch(e), ms);
  d({type:"status", online:true, version:"UE 5.7"}, 0);
  d({type:"user", msg:"Build a glass bridge between the east and west columns"}, 200);
  d({type:"progress", agent:"Manager", msg:"routed to Architect"}, 700);
  d({type:"progress", agent:"Architect", msg:"plan: material, geometry, verification"}, 1500);
  d({type:"progress", agent:"Python", msg:"executing step 2 of 3"}, 2400);
  d({type:"final", status:"success",
     msg:"Done. Glass bridge spanning `3550 units`, verified visually.\n\n```python\nactor.set_actor_scale3d(unreal.Vector(35.5, 3.0, 0.2))\n```"}, 3400);
}
</script>
</body>
</html>
```

- [ ] **Step 6: Verificación estructural + visual**

```powershell
Get-ChildItem "E:\PCW\VERA\UE57\Content\Python\vera_chat" -Recurse -File | Select-Object Name, Length
Start-Process "E:\PCW\VERA\UE57\Content\Python\vera_chat\dev.html"
```
Expected: 7 archivos; el navegador abre dev.html — clic en "▶ demo" muestra: status Online, burbuja usuario, timeline de 3 agentes (chips reaccionando), final con markdown y código coloreado, sin errores en la consola JS (F12). El controlador hará además una revisión visual con captura.

- [ ] **Step 7: Commit**

```bash
git add UE57/Content/Python/vera_chat/
git commit -m "feat: UI HTML del chat VERA (layout C, timeline, markdown vendorizado, dev harness)"
```

---

### Task 7: Shell Python (`vera_ui.py` con WebEngine + fallback)

**Files:**
- Modify: `UE57/Content/Python/vera_ui.py` (REEMPLAZO COMPLETO del archivo — el contenido actual de burbujas se conserva embebido como fallback)

Sin unit tests (requiere Qt + unreal): la lógica testeable ya vive en `vera_history` (Task 5) y el protocolo en Tasks 2-3. Cobertura: smoke (Task 9). Leer el `vera_ui.py` actual ANTES de reemplazar: las clases `Bubble`, `ChatInputEdit`, `VeraChatWindow` actuales se copian SIN CAMBIOS dentro de la sección "FALLBACK UI" (verificar al pegar).

- [ ] **Step 1: Reemplazar `vera_ui.py`**

Estructura nueva del archivo (completa salvo la sección fallback, que se copia textual del archivo actual):

```python
"""VERA Chat UI — shell Qt con interior HTML (QWebEngineView).
Fallback automático a la UI de burbujas si QtWebEngineWidgets no está disponible."""
import json
import os
import threading

import unreal

# ---------- disponibilidad de Qt / WebEngine ----------
HAS_PYSIDE = False
HAS_WEBENGINE = False
try:
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PySide6.QtCore import Qt, QObject, QUrl, Slot
    HAS_PYSIDE = True
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebChannel import QWebChannel
        HAS_WEBENGINE = True
    except ImportError:
        pass
except ImportError:
    class QWidget(object):
        pass
    class QObject(object):
        pass

import vera_history

CHAT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vera_chat")
HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Saved", "VERA", "chat_history.jsonl")
BACKEND = ("127.0.0.1", 9880)
STREAM_FINAL_TIMEOUT = 300.0

_pending_events = []          # eventos del hilo lector → tick de Qt → JS
global_vera_window = None


def module_level_tick_qt(delta_time):
    """Tick global (registrado una vez): bombea Qt y drena eventos hacia JS."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            return
        app.processEvents()
        global _pending_events, global_vera_window
        if global_vera_window:
            while _pending_events:
                event = _pending_events.pop(0)
                global_vera_window.handle_event(event)
    except Exception as e:
        unreal.log_error(f"[VERA UI] tick error: {e}")


# ---------- puente JS→Python ----------
class PyBridge(QObject):
    def __init__(self, window):
        super().__init__()
        self._window = window

    @Slot()
    def js_ready(self):
        self._window.on_js_ready()

    @Slot(str)
    def send_command(self, text):
        self._window.send_command(text)

    @Slot(str)
    def open_image(self, path):
        try:
            os.startfile(path)  # visor del sistema
        except OSError as e:
            unreal.log_error(f"[VERA UI] no pude abrir la imagen: {e}")


# ---------- ventana WebEngine ----------
class VeraWebWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VERA")
        self.resize(460, 720)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView()
        self.channel = QWebChannel()
        self.pybridge = PyBridge(self)
        self.channel.registerObject("pybridge", self.pybridge)
        self.view.page().setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(os.path.join(CHAT_DIR, "index.html")))
        layout.addWidget(self.view)
        self.setLayout(layout)

    # --- eventos hacia JS (siempre desde el main thread vía tick) ---
    def handle_event(self, event):
        if event.get("type") in ("user", "progress", "image", "final", "error"):
            try:
                vera_history.append_event(HISTORY_PATH, event)
            except OSError as e:
                unreal.log_warning(f"[VERA UI] historial no disponible: {e}")
        js = "veraChat.dispatch(" + json.dumps(event, ensure_ascii=False) + ")"
        self.view.page().runJavaScript(js)

    def on_js_ready(self):
        # Historial primero, después estado de conexión
        events = vera_history.load_recent(HISTORY_PATH)
        if events:
            self.view.page().runJavaScript(
                "veraChat.dispatch(" + json.dumps(
                    {"type": "history", "events": events}, ensure_ascii=False) + ")")
        else:
            self.handle_event({"type": "final", "status": "success",
                               "msg": "Hi, I'm VERA. What are we building today?"})
        threading.Thread(target=self._check_status, daemon=True).start()

    # --- backend ---
    def send_command(self, text):
        # El JS ya pintó la burbuja del usuario; acá solo persistimos y enviamos
        try:
            vera_history.append_event(HISTORY_PATH, {"type": "user", "msg": text})
        except OSError:
            pass
        threading.Thread(target=self._stream_command, args=(text,), daemon=True).start()

    def _stream_command(self, text):
        import socket
        global _pending_events
        try:
            with socket.create_connection(BACKEND, timeout=STREAM_FINAL_TIMEOUT) as s:
                s.settimeout(STREAM_FINAL_TIMEOUT)
                s.sendall((json.dumps({"command": text}) + "\n").encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        _pending_events.append({"type": "interrupted"})
                        return
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line.decode("utf-8"))
                        except ValueError:
                            continue
                        _pending_events.append(event)
                        if event.get("type") == "final":
                            return
        except ConnectionRefusedError:
            _pending_events.append({"type": "error",
                "msg": "El backend VERA no está corriendo. "
                       "Arrancalo con: `python -m vera.core.vera_server`"})
            _pending_events.append({"type": "status", "online": False})
        except OSError:
            _pending_events.append({"type": "interrupted"})

    def _check_status(self):
        import socket
        global _pending_events
        try:
            with socket.create_connection(BACKEND, timeout=3.0) as s:
                s.settimeout(5.0)
                s.sendall((json.dumps({"command": "hello world"}) + "\n").encode("utf-8"))
                s.recv(4096)
            _pending_events.append({"type": "status", "online": True, "version": "UE 5.7"})
        except OSError:
            _pending_events.append({"type": "status", "online": False})


# ==============================================================================
# FALLBACK UI (burbujas QFrame) — COPIA TEXTUAL de las clases actuales de
# vera_ui.py: Bubble, ChatInputEdit, VeraChatWindow (y su _pending_vera_responses
# renombrado para no chocar). Pegar aquí SIN CAMBIOS funcionales.
# ==============================================================================
# [el implementador copia aquí las clases del archivo original, líneas 42-364]


# ---------- apertura ----------
def install_pyside_and_open():
    """Conservar la función actual de vera_ui.py (instala PySide6 con pip del
    engine) — copia textual de las líneas 366-420 del archivo original, con un
    cambio: tras instalar, reintentar los imports de ESTE módulo via importlib:

        import importlib, sys
        importlib.reload(sys.modules[__name__])
    """


def open_vera_ui():
    global global_vera_window
    if not HAS_PYSIDE:
        if not install_pyside_and_open():
            return

    app = QApplication.instance()
    if not app:
        app = QApplication([])

    if global_vera_window is None:
        if HAS_WEBENGINE:
            global_vera_window = VeraWebWindow()
        else:
            unreal.log_warning("[VERA] QtWebEngine no disponible — usando UI básica.")
            global_vera_window = VeraChatWindow()  # fallback de burbujas
        try:
            unreal.parent_external_window_to_slate(global_vera_window.winId())
        except Exception:
            pass
        if not hasattr(unreal, "_vera_qt_tick_registered_v6"):
            unreal._vera_tick_func = module_level_tick_qt
            unreal.register_slate_post_tick_callback(unreal._vera_tick_func)
            unreal._vera_qt_tick_registered_v6 = True

    global_vera_window.show()


# ---------- menú toolbar (sin cambios) ----------
# [copia textual de create_vera_menu() y su invocación, líneas 452-482 del original]
```

Reglas para el implementador:
1. Las secciones marcadas "[copia textual…]" se rellenan con el código del `vera_ui.py` actual (leerlo entero primero; está en git en `UE57/Content/Python/vera_ui.py`). El fallback `VeraChatWindow` y su tick usan `_pending_vera_responses` — conservar esa lista global aparte de `_pending_events`.
2. El fallback debe seguir funcionando si `HAS_WEBENGINE` es False: la función de tick del fallback ya está cubierta por `module_level_tick_qt` original — integrar ambos drenajes en el mismo tick (eventos web y `_pending_vera_responses`).
3. `install_pyside_and_open` devuelve bool como hoy.

- [ ] **Step 2: Verificación de sintaxis + suite**

```powershell
python -c "import ast; ast.parse(open('UE57/Content/Python/vera_ui.py', encoding='utf-8').read()); print('sintaxis ok')"
python -m pytest tests/ --ignore=tests/test_manager.py --ignore=tests/test_perception.py --ignore=tests/test_python_agent.py -q
```
Expected: sintaxis ok; suite completa verde (vera_ui no se importa en tests — depende de unreal).

- [ ] **Step 3: Commit**

```bash
git add UE57/Content/Python/vera_ui.py
git commit -m "feat: vera_ui con interior WebEngine, stream de progreso y fallback a burbujas"
```

---

### Task 8: `init_unreal.py` — flag OpenGL

**Files:**
- Modify: `UE57/Content/Python/init_unreal.py`

- [ ] **Step 1: Insertar ANTES de los imports de vera_bridge/vera_ui** (después de `import unreal`):

```python
# QtWebEngine exige este flag ANTES de crear cualquier QApplication.
# Se setea acá (arranque del editor) para que open_vera_ui lo herede.
try:
    from PySide6.QtCore import Qt, QCoreApplication
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
except ImportError:
    pass  # PySide6 se instala on-demand al abrir la UI por primera vez
```

- [ ] **Step 2: Verificación**

`python -c "import ast; ast.parse(open('UE57/Content/Python/init_unreal.py', encoding='utf-8').read()); print('ok')"` → ok

- [ ] **Step 3: Commit**

```bash
git add UE57/Content/Python/init_unreal.py
git commit -m "feat: AA_ShareOpenGLContexts al arranque del editor (requisito WebEngine)"
```

---

### Task 9: Smoke test en el editor (con el usuario)

Sin archivos. Checklist manual — el usuario está presente y testea en vivo.

- [ ] 1. Arrancar el backend: `python -m vera.core.vera_server` (terminal aparte, con `GEMINI_API_KEY`).
- [ ] 2. Reiniciar el editor UE57 (carga `init_unreal.py` nuevo: flag + bridge + UI).
- [ ] 3. Clic en 🤖 VERA → la ventana abre con la UI nueva (header VERA, chips, input).
- [ ] 4. `hello world` → final inmediata "Hello World!…" en burbuja con markdown.
- [ ] 5. Comando real (ej. "spawn a cube at the origin") → timeline en vivo: Manager → ruta → agente; final al terminar; chips reaccionando.
- [ ] 6. Cerrar y reabrir la ventana → el historial reaparece.
- [ ] 7. Apagar el backend y mandar un comando → burbuja de error accionable + status Offline.
- [ ] 8. (Fallback) En la consola Python del editor: `import vera_ui; vera_ui.HAS_WEBENGINE = False; vera_ui.global_vera_window = None; vera_ui.open_vera_ui()` → abre la UI de burbujas clásica.
- [ ] 9. Commit final de ajustes que surjan del smoke.

---

## Self-review (hecho al escribir el plan)

- **Cobertura del spec:** protocolo streaming (T2), report_progress (T1), emisiones Manager (T4), UI HTML layout C + copy profesional + timeline + markdown vendorizado + chips + mic visual (T6), QWebChannel + shell + hilo lector + fallback (T7), historial JSONL (T5 + persistencia en T7), imágenes (evento `image` T1-T3, render T6, open_image T7), `AA_ShareOpenGLContexts` (T8), `vera_command` compat (T3), interrupted/offline/error (T6-T7), dev harness (T6), smoke con usuario (T9). Fuera de alcance respetado (sin Whisper, sin temas alternativos).
- **Placeholders:** las secciones "[copia textual]" de T7 NO son placeholders — referencian código existente en git con rangos de líneas exactos y reglas de integración; el resto del plan muestra código completo.
- **Consistencia:** evento `{"type":"progress","agent","msg"}` idéntico en T1/T2/T3/T6/T7; `final` con `status`+`msg` en T2/T3/T6/T7; `send_json_stream(port, payload, timeout, host, on_event)` consistente; `veraChat.dispatch` único punto JS en T6/T7; `vera_history.append_event/load_recent` en T5/T7.
- **Gap conocido (documentado):** la pregunta de ambigüedad del DecisionAgent llega como `progress`, no como `final` interactiva — limitación preexistente, fuera de alcance.
