# VERA Cerebro Agéntico — Fase 1 (Núcleo) — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el cerebro agéntico mínimo de VERA: un bucle de tool-use sobre el SDK de Anthropic, con un registro de herramientas auto-descubiertas y la tool universal `run_ue_python`.

**Architecture:** Un `AgentLoop` corre el bucle de tool-use (el modelo razona → elige tools → ve resultados → repite). Un `ToolRegistry` auto-descubre clases `Tool` de `vera/agent/tools/` y construye el `tools[]` para la API. La primera tool, `run_ue_python`, ejecuta código Python en el editor vía el bridge 9878. El `vera_server` puede rutear al loop detrás de un flag, dejando el Manager viejo como fallback.

**Tech Stack:** Python 3.11, SDK `anthropic` (vendored en `.ue_deps`), `pytest`. Bridge TCP existente (`vera/tools/ue_conn.py` → puerto 9878).

**Spec:** `docs/superpowers/specs/2026-06-11-vera-agentic-brain-design.md`

**Cómo correr los tests:** desde `E:/PCW/VERA`, ejecutar `python -m pytest tests/agent/ -v`. Ninguno requiere el editor vivo ni la API (todo mockeado).

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `vera/agent/__init__.py` | Paquete del cerebro |
| `vera/agent/tool.py` | Contrato `Tool` (base), `ToolResult`, `ToolContext` |
| `vera/agent/registry.py` | `ToolRegistry`: registro + auto-discovery + schema Anthropic |
| `vera/agent/loop.py` | `AgentLoop`: el bucle de tool-use |
| `vera/agent/tools/__init__.py` | Paquete de tools auto-descubiertas |
| `vera/agent/tools/run_ue_python.py` | `RunUEPythonTool` (Capa 0, bash-core) |
| `tests/agent/*` | Tests unitarios de cada pieza |
| `vera/core/vera_server.py` | (modificar) ruteo opcional al `AgentLoop` detrás de flag |

---

## Task 1: Contrato `Tool`

**Files:**
- Create: `vera/agent/__init__.py`
- Create: `vera/agent/tool.py`
- Test: `tests/agent/__init__.py`, `tests/agent/test_tool.py`

- [ ] **Step 1: Crear los paquetes vacíos**

Create `vera/agent/__init__.py` con contenido:
```python
"""VERA: cerebro agéntico (bucle de tool-use)."""
```
Create `tests/agent/__init__.py` vacío (un archivo de 0 bytes).

- [ ] **Step 2: Escribir el test que falla**

Create `tests/agent/test_tool.py`:
```python
from vera.agent.tool import Tool, ToolResult, ToolContext


def test_toolresult_defaults():
    r = ToolResult("hola")
    assert r.content == "hola"
    assert r.is_error is False


def test_tool_to_anthropic_schema():
    class Dummy(Tool):
        name = "dummy"
        description = "desc"
        input_schema = {"type": "object", "properties": {}}

    t = Dummy()
    assert t.to_anthropic() == {
        "name": "dummy",
        "description": "desc",
        "input_schema": {"type": "object", "properties": {}},
    }
    assert t.destructive is False  # default


def test_toolcontext_report_emits():
    seen = []
    ctx = ToolContext(emit=seen.append)
    ctx.report("A", "msg")
    assert seen == [{"type": "progress", "agent": "A", "msg": "msg"}]


def test_toolcontext_report_noop_without_emit():
    ctx = ToolContext()
    ctx.report("A", "msg")  # no debe lanzar excepción
```

- [ ] **Step 3: Correr el test para verificar que falla**

Run: `python -m pytest tests/agent/test_tool.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vera.agent.tool'`

- [ ] **Step 4: Implementar `tool.py`**

Create `vera/agent/tool.py`:
```python
"""Contrato de herramientas del cerebro de VERA."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ToolResult:
    """Resultado de ejecutar una tool. `content` vuelve al modelo."""
    content: str
    is_error: bool = False


@dataclass
class ToolContext:
    """Servicios que el AgentLoop le pasa a cada tool en execute()."""
    bridge_port: int = 9878
    emit: Optional[Callable[[dict], None]] = None  # emisor de eventos a la UI
    llm: Any = None                                 # cliente LLM para sub-llamadas

    def report(self, agent: str, msg: str) -> None:
        """Emite un evento de progreso si hay canal conectado (best-effort)."""
        if self.emit:
            self.emit({"type": "progress", "agent": agent, "msg": msg})


class Tool:
    """Clase base de toda herramienta. Subclasealá y definí los atributos.

    Un contribuidor agrega una capacidad creando un archivo en
    vera/agent/tools/ con una subclase de Tool — el ToolRegistry la descubre.
    """
    name: str = ""
    description: str = ""           # qué hace + CUÁNDO usarla (lo lee el modelo)
    input_schema: dict = {}         # JSON Schema de los argumentos
    destructive: bool = False       # ¿requiere confirmación? (irreversible)

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def to_anthropic(self) -> dict:
        """Forma que espera el parámetro `tools` de la Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `python -m pytest tests/agent/test_tool.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add vera/agent/__init__.py vera/agent/tool.py tests/agent/__init__.py tests/agent/test_tool.py
git commit -m "feat(agent): contrato Tool, ToolResult y ToolContext"
```

---

## Task 2: `ToolRegistry` (registro y schema)

**Files:**
- Create: `vera/agent/registry.py`
- Test: `tests/agent/test_registry.py`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/agent/test_registry.py`:
```python
import pytest

from vera.agent.tool import Tool, ToolResult
from vera.agent.registry import ToolRegistry


class FakeTool(Tool):
    name = "fake"
    description = "una tool fake"
    input_schema = {"type": "object", "properties": {}}

    def execute(self, args, ctx):
        return ToolResult("ok")


def test_register_and_get():
    reg = ToolRegistry()
    t = FakeTool()
    reg.register(t)
    assert reg.get("fake") is t
    assert reg.all() == [t]


def test_get_missing_returns_none():
    assert ToolRegistry().get("nope") is None


def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(FakeTool())
    with pytest.raises(ValueError):
        reg.register(FakeTool())


def test_to_anthropic_shape():
    reg = ToolRegistry()
    reg.register(FakeTool())
    assert reg.to_anthropic() == [
        {
            "name": "fake",
            "description": "una tool fake",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/agent/test_registry.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vera.agent.registry'`

- [ ] **Step 3: Implementar `registry.py` (sin discover todavía)**

Create `vera/agent/registry.py`:
```python
"""Registro y auto-descubrimiento de herramientas."""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import List, Optional

from vera.agent.tool import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool duplicada: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def to_anthropic(self) -> List[dict]:
        return [t.to_anthropic() for t in self._tools.values()]
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/agent/test_registry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add vera/agent/registry.py tests/agent/test_registry.py
git commit -m "feat(agent): ToolRegistry con register/get/all/to_anthropic"
```

---

## Task 3: `RunUEPythonTool` (Capa 0 — bash-core)

**Files:**
- Create: `vera/agent/tools/__init__.py`
- Create: `vera/agent/tools/run_ue_python.py`
- Test: `tests/agent/test_run_ue_python.py`

- [ ] **Step 1: Crear el paquete de tools**

Create `vera/agent/tools/__init__.py` con contenido:
```python
"""Herramientas auto-descubiertas del cerebro de VERA."""
```

- [ ] **Step 2: Escribir el test que falla**

Create `tests/agent/test_run_ue_python.py`:
```python
from vera.agent.tool import ToolContext
from vera.agent.tools.run_ue_python import RunUEPythonTool
import vera.agent.tools.run_ue_python as mod
from vera.tools.ue_conn import UEConnectionError


def test_destructive_default():
    assert RunUEPythonTool().destructive is True


def test_success(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["port"] = port
        captured["script"] = payload["script"]
        return {"success": True, "output": "HOLA"}

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = RunUEPythonTool().execute({"code": "print('x')"}, ToolContext(bridge_port=9878))
    assert res.is_error is False
    assert res.content == "HOLA"
    assert captured["port"] == 9878
    assert captured["script"] == "print('x')"


def test_failure_from_editor(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: {"success": False, "error": "boom"})
    res = RunUEPythonTool().execute({"code": "x"}, ToolContext())
    assert res.is_error is True
    assert "boom" in res.content


def test_empty_code():
    res = RunUEPythonTool().execute({"code": "   "}, ToolContext())
    assert res.is_error is True


def test_bridge_unreachable(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")

    monkeypatch.setattr(mod, "send_json", boom)
    res = RunUEPythonTool().execute({"code": "x"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content
```

- [ ] **Step 3: Correr el test para verificar que falla**

Run: `python -m pytest tests/agent/test_run_ue_python.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vera.agent.tools.run_ue_python'`

- [ ] **Step 4: Implementar `run_ue_python.py`**

Create `vera/agent/tools/run_ue_python.py`:
```python
"""Capa 0 (bash-core): ejecutar Python arbitrario dentro del editor de UE."""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class RunUEPythonTool(Tool):
    name = "run_ue_python"
    description = (
        "Ejecuta código Python dentro del editor de Unreal Engine (main-thread safe) "
        "vía el bridge. Usá esto para CUALQUIER operación en el editor que no tenga una "
        "tool dedicada: crear/modificar actors, leer el nivel, ajustar settings, etc. "
        "El módulo `unreal` ya está disponible. Usá print() para devolver datos."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Código Python a ejecutar en el editor.",
            }
        },
        "required": ["code"],
    }
    destructive = True  # Decisión MVP: destructiva por defecto (pide OK siempre)

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        code = (args.get("code") or "").strip()
        if not code:
            return ToolResult("Error: el argumento 'code' está vacío.", is_error=True)
        ctx.report("UEPython", "ejecutando script en el editor")
        try:
            resp = send_json(ctx.bridge_port, {"script": code})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"No se pudo ejecutar en el editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or "(sin salida)")
        return ToolResult(resp.get("error") or "fallo desconocido en el editor", is_error=True)
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `python -m pytest tests/agent/test_run_ue_python.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add vera/agent/tools/__init__.py vera/agent/tools/run_ue_python.py tests/agent/test_run_ue_python.py
git commit -m "feat(agent): tool run_ue_python (bash-core via bridge 9878)"
```

---

## Task 4: Auto-discovery en `ToolRegistry`

**Files:**
- Modify: `vera/agent/registry.py` (agregar método `discover`)
- Test: `tests/agent/test_registry.py` (agregar test de discovery)

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/agent/test_registry.py`:
```python
def test_discover_finds_run_ue_python():
    import vera.agent.tools as tools_pkg

    reg = ToolRegistry()
    reg.discover(tools_pkg)
    tool = reg.get("run_ue_python")
    assert tool is not None
    assert tool.destructive is True
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/agent/test_registry.py::test_discover_finds_run_ue_python -v`
Expected: FAIL con `AttributeError: 'ToolRegistry' object has no attribute 'discover'`

- [ ] **Step 3: Agregar `discover()` a `registry.py`**

Agregar este método dentro de la clase `ToolRegistry` en `vera/agent/registry.py` (después de `to_anthropic`):
```python
    def discover(self, package) -> None:
        """Importa todos los módulos de `package` y registra cada subclase de Tool
        definida en ellos (instanciada sin argumentos)."""
        for _, modname, _ in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package.__name__}.{modname}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, Tool)
                    and obj is not Tool
                    and obj.__module__ == module.__name__
                ):
                    self.register(obj())
                    logger.info("[ToolRegistry] tool descubierta: %s", obj().name)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/agent/test_registry.py -v`
Expected: PASS (5 tests, incluido el de discovery)

- [ ] **Step 5: Commit**

```bash
git add vera/agent/registry.py tests/agent/test_registry.py
git commit -m "feat(agent): auto-discovery de tools en ToolRegistry"
```

---

## Task 5: `AgentLoop` (el bucle de tool-use)

**Files:**
- Create: `vera/agent/loop.py`
- Test: `tests/agent/test_loop.py`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/agent/test_loop.py`:
```python
from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.tool import Tool, ToolResult


# --- fakes que imitan la forma del SDK de Anthropic ---
class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUse:
    type = "tool_use"

    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


class FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}
    destructive = False

    def execute(self, args, ctx):
        return ToolResult(f"echo:{args.get('x')}")


def _reg():
    r = ToolRegistry()
    r.register(EchoTool())
    return r


def test_end_turn_immediately():
    client = FakeClient([_Resp("end_turn", [_Text("listo")])])
    out = AgentLoop(_reg(), client).run("hola")
    assert out == {"status": "success", "msg": "listo"}


def test_tool_use_then_end():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "echo", {"x": 5})]),
        _Resp("end_turn", [_Text("hecho")]),
    ])
    out = AgentLoop(_reg(), client).run("usá echo")
    assert out["status"] == "success"
    assert out["msg"] == "hecho"
    user_msg = client.messages.calls[1]["messages"][-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"][0]["type"] == "tool_result"
    assert "echo:5" in user_msg["content"][0]["content"]


def test_unknown_tool_reports_error():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "nope", {})]),
        _Resp("end_turn", [_Text("fin")]),
    ])
    AgentLoop(_reg(), client).run("x")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True
    assert "nope" in tr["content"]


def test_destructive_confirm_reject():
    class Danger(Tool):
        name = "danger"
        description = "d"
        input_schema = {"type": "object", "properties": {}}
        destructive = True

        def execute(self, args, ctx):
            raise AssertionError("no debe ejecutarse")

    reg = ToolRegistry()
    reg.register(Danger())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "danger", {})]),
        _Resp("end_turn", [_Text("fin")]),
    ])
    AgentLoop(reg, client, confirm=lambda tool, args: False).run("borrá todo")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True
    assert "rechaz" in tr["content"].lower()


def test_emit_events():
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "echo", {"x": 1})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    events = []
    AgentLoop(_reg(), client).run("x", emit=events.append)
    types = [e["type"] for e in events]
    assert "tool_use" in types
    assert "tool_result" in types
    assert "final" in types
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/agent/test_loop.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vera.agent.loop'`

- [ ] **Step 3: Implementar `loop.py`**

Create `vera/agent/loop.py`:
```python
"""AgentLoop: bucle de tool-use de VERA sobre la Messages API de Anthropic."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from vera.agent.tool import ToolContext, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
MAX_ITERATIONS = 20


def _final_text(content) -> str:
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return "\n".join(parts) if parts else "(sin texto)"


def _tool_result(tool_use_id: str, content: str, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


class AgentLoop:
    """Corre el bucle: el modelo razona → elige tools → ve resultados → repite.

    `llm_client` es un cliente con forma de `anthropic.Anthropic`
    (`.messages.create(...)`), inyectable para tests.
    `confirm(tool, args) -> bool` gatea tools destructivas; None = sin gate.
    """

    def __init__(
        self,
        registry,
        llm_client,
        *,
        model: str = DEFAULT_MODEL,
        system: str = "",
        bridge_port: int = 9878,
        confirm: Optional[Callable] = None,
    ) -> None:
        self.registry = registry
        self.llm = llm_client
        self.model = model
        self.system = system
        self.bridge_port = bridge_port
        self.confirm = confirm

    def run(self, command: str, emit: Optional[Callable[[dict], None]] = None) -> dict:
        ctx = ToolContext(bridge_port=self.bridge_port, emit=emit, llm=self.llm)
        messages = [{"role": "user", "content": command}]
        tools = self.registry.to_anthropic()

        for _ in range(MAX_ITERATIONS):
            resp = self.llm.messages.create(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=self.system,
                tools=tools,
                messages=messages,
            )

            if resp.stop_reason == "end_turn":
                text = _final_text(resp.content)
                if emit:
                    emit({"type": "final", "status": "success", "msg": text})
                return {"status": "success", "msg": text}

            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue

            # stop_reason == "tool_use"
            messages.append({"role": "assistant", "content": resp.content})
            results = [
                self._run_tool(block, ctx, emit)
                for block in resp.content
                if getattr(block, "type", None) == "tool_use"
            ]
            messages.append({"role": "user", "content": results})

        if emit:
            emit({"type": "final", "status": "error", "msg": "límite de iteraciones"})
        return {"status": "error", "msg": "límite de iteraciones alcanzado"}

    def _run_tool(self, block, ctx: ToolContext, emit) -> dict:
        tool = self.registry.get(block.name)
        if tool is None:
            return _tool_result(block.id, f"tool desconocida: {block.name}", True)
        if emit:
            emit({"type": "tool_use", "agent": tool.name, "input": block.input})
        if tool.destructive and self.confirm and not self.confirm(tool, block.input):
            return _tool_result(block.id, "El usuario rechazó la acción.", True)
        try:
            result = tool.execute(block.input, ctx)
        except Exception as e:  # una tool rota nunca tumba el loop
            logger.exception("[AgentLoop] la tool %s lanzó excepción", tool.name)
            result = ToolResult(f"excepción en la tool: {e}", is_error=True)
        if emit:
            emit({"type": "tool_result", "agent": tool.name, "is_error": result.is_error})
        return _tool_result(block.id, result.content, result.is_error)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/agent/test_loop.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Correr toda la suite del cerebro**

Run: `python -m pytest tests/agent/ -v`
Expected: PASS (19 tests en total)

- [ ] **Step 6: Commit**

```bash
git add vera/agent/loop.py tests/agent/test_loop.py
git commit -m "feat(agent): AgentLoop (bucle de tool-use con gate destructivo)"
```

---

## Task 6: Integrar el `AgentLoop` en `vera_server` (detrás de flag)

**Objetivo:** que el `vera_server` pueda rutear comandos al `AgentLoop` cuando la env var `VERA_USE_AGENT_LOOP` esté activa, dejando el `ManagerAgent` viejo como comportamiento por defecto (fallback seguro, reversible).

**Files:**
- Create: `vera/agent/factory.py` (construye un `AgentLoop` listo para producción)
- Test: `tests/agent/test_factory.py`
- Modify: `vera/core/vera_server.py` (rama opcional al loop)

- [ ] **Step 1: Escribir el test que falla (factory)**

Create `tests/agent/test_factory.py`:
```python
from vera.agent.factory import build_agent_loop


class _DummyLLM:
    pass


def test_build_agent_loop_discovers_run_ue_python():
    loop = build_agent_loop(llm_client=_DummyLLM())
    assert loop.registry.get("run_ue_python") is not None
    # el system prompt no está vacío (define el rol de VERA)
    assert loop.system.strip() != ""
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/agent/test_factory.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'vera.agent.factory'`

- [ ] **Step 3: Implementar `factory.py`**

Create `vera/agent/factory.py`:
```python
"""Construcción del AgentLoop de producción."""
from __future__ import annotations

from vera.agent.loop import AgentLoop, DEFAULT_MODEL
from vera.agent.registry import ToolRegistry

SYSTEM_PROMPT = (
    "Sos VERA, un ingeniero técnico autónomo de Unreal Engine. "
    "Trabajás dentro del editor del usuario a través de herramientas. "
    "Pensá tu plan, usá las herramientas necesarias, verificá los resultados "
    "y corregí si algo falla. Para cualquier operación sin tool dedicada, "
    "escribí código con `run_ue_python` (el módulo `unreal` está disponible; "
    "usá print() para devolver datos). Sé conciso en tu respuesta final."
)


def build_agent_loop(llm_client, *, model: str = DEFAULT_MODEL, confirm=None) -> AgentLoop:
    """Arma un AgentLoop con todas las tools auto-descubiertas de vera/agent/tools/."""
    import vera.agent.tools as tools_pkg

    registry = ToolRegistry()
    registry.discover(tools_pkg)
    return AgentLoop(
        registry,
        llm_client,
        model=model,
        system=SYSTEM_PROMPT,
        confirm=confirm,
    )
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/agent/test_factory.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Conectar el flag en `vera_server.py`**

En `vera/core/vera_server.py`, dentro de `handle_client`, ubicá el bloque que arranca con el comentario `# Fast keyword route: bypass manager_agent caching issue` (cerca de la línea 80). Insertá ANTES de ese bloque la siguiente rama:

```python
                # Cerebro agéntico (Fase 1): activable por env var, Manager como fallback.
                import os
                if os.environ.get("VERA_USE_AGENT_LOOP"):
                    import anthropic
                    from vera.agent.factory import build_agent_loop
                    loop = build_agent_loop(anthropic.Anthropic())
                    result = loop.run(command, emit=emit)
                    # build_agent_loop no pasa `confirm`, así que el gate destructivo
                    # está inactivo en Fase 1 (round-trip de confirmación = Fase 2).
                    success = result.get("status") == "success"
                    return
```

(El `emit` y `command` ya existen en el scope de `handle_client`. El `return` sale del `try` y libera `_busy` en el `finally` existente.)

- [ ] **Step 6: Verificar que no rompiste la suite ni el import del server**

Run: `python -m pytest tests/agent/ -v`
Expected: PASS (20 tests)

Run: `python -c "import vera.core.vera_server"`
Expected: sin error (el módulo importa limpio)

- [ ] **Step 7: Commit**

```bash
git add vera/agent/factory.py tests/agent/test_factory.py vera/core/vera_server.py
git commit -m "feat(agent): build_agent_loop + ruteo opcional en vera_server (flag VERA_USE_AGENT_LOOP)"
```

---

## Verificación end-to-end (manual, con UE abierto)

> No es un step automatizado — es la prueba viva del contrato (alineado con el feedback "verificar antes de declarar éxito").

1. Con UE abierto y el `vera_server` corriendo, recargar el módulo del server vía el bridge 9878 (hot-reload, sin reiniciar UE) **o** levantar un server nuevo con `VERA_USE_AGENT_LOOP=1`.
2. Mandar por socket a 9880: `{"command": "creá un cubo en el origen del nivel"}`.
3. Esperado en el stream: eventos `tool_use` (run_ue_python) → `tool_result` → `final` con status success, y un cubo nuevo en el viewport.

---

## Self-Review (cobertura del spec)

- **Bucle de tool-use (spec §3.1 AgentLoop):** Task 5. ✅
- **ToolRegistry + auto-discovery (spec §3.1, §3.2):** Tasks 2, 4. ✅
- **Contrato Tool (spec §3.2):** Task 1. ✅
- **Capa 0 run_ue_python (spec §3.3):** Task 3. ✅
- **Guarda destructiva (spec §6):** Task 5 (`confirm`), decisión "destructiva por defecto" en `RunUEPythonTool` (Task 3). Round-trip de UI = Fase 2 (documentado en Task 6 Step 5). ✅
- **vera_server adelgazado / fallback (spec §3.1, §7 Fase 1):** Task 6, detrás de flag. El borrado del ruteo duplicado se completa en Fase 2 (cuando el loop sea el default). ✅
- **Eventos → timeline UI (spec §3.1 EventEmitter):** Task 5 (`emit` con tipos progress/tool_use/tool_result/final). ✅
- **Fuera de alcance de Fase 1 (otras fases):** tools dedicadas de los 17 agentes (Fase 2), Watcher proactivo (Fase 3), sub-agentes/memoria-tool/Fab (Fase 4), consolidación de config (Fase 2-3).
