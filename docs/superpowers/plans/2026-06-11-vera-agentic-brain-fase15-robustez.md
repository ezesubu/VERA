# VERA Fase 1.5 — Robustez del Núcleo Agéntico (Plan de Implementación)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Endurecer el `AgentLoop` de Fase 1 antes de la paridad de tools: fix del bug de `stop_reason`, resultados de tool con imágenes y truncado, streaming con thinking visible en el timeline, sesión con historial persistente, y gate de confirmación real con round-trip a la UI.

**Architecture:** El loop pasa de `messages.create` (no-streaming, un comando aislado) a `messages.stream` con `thinking adaptive + display summarized` (los deltas de thinking se emiten al timeline). Una nueva clase `AgentSession` es dueña del historial (`messages`), que sobrevive entre comandos y expone `inject()` para los watchers de Fase 3. El gate destructivo se activa en producción: `vera_server` emite un evento `question` por el socket ya abierto y espera una línea JSON `{"approve": bool}` del cliente; la UI muestra botones Aprobar/Rechazar. Default: **denegar** (timeout o desconexión). Escape hatch: env var `VERA_AUTO_APPROVE=1` para autopilot/testing.

**Tech Stack:** Python 3.11+, SDK `anthropic` (Messages API streaming, modelo `claude-opus-4-8`, thinking adaptativo), pytest, PySide6/QWebEngine (UI), sockets TCP línea-JSON (protocolo existente 9880).

**Convenciones del repo:** código y docstrings en español rioplatense; tests en `tests/agent/`; correr tests con `python -m pytest tests/agent/ -q` desde `E:\PCW\VERA`. Los commits NO llevan emoji.

**Datos de la API que este plan asume (verificados contra la referencia claude-api 2026-06):**
- `thinking={"type": "adaptive"}` es el único modo válido en `claude-opus-4-8`; `display` por defecto es `"omitted"` (los bloques thinking llegan con texto vacío). Para mostrar el razonamiento hay que pedir `{"type": "adaptive", "display": "summarized"}`.
- `client.messages.stream(...)` es un context manager; los deltas llegan como eventos `content_block_delta` con `delta.type == "thinking_delta"` (atributo `.thinking`) o `"text_delta"` (atributo `.text`); `stream.get_final_message()` devuelve el `Message` completo.
- `tool_result.content` acepta un string **o** una lista de content blocks, incluidas imágenes: `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ...}}`.
- `stop_reason` puede ser `end_turn`, `tool_use`, `pause_turn`, `max_tokens`, `stop_sequence`, `refusal`. Un mensaje user con `content: []` es un 400.

---

## Task 1: Fix del bug de `stop_reason` no contemplado

El loop actual asume que todo lo que no es `end_turn`/`pause_turn` es `tool_use`. Si el modelo corta por `max_tokens` o `refusal`, no hay bloques `tool_use` → se appendea `{"role": "user", "content": []}` → error 400 de la API y el comando muere.

**Files:**
- Modify: `vera/agent/loop.py:69-90` (método `run`)
- Test: `tests/agent/test_loop.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/agent/test_loop.py`:

```python
def test_stop_reason_max_tokens_corta_limpio():
    """max_tokens sin tool_use no debe appendear un user vacío (400 de la API)."""
    client = FakeClient([_Resp("max_tokens", [_Text("respuesta trunca")])])
    out = AgentLoop(_reg(), client).run("hola")
    assert out["status"] == "error"
    assert "max_tokens" in out["msg"]
    # una sola llamada: el loop NO debe reintentar con un mensaje malformado
    assert len(client.messages.calls) == 1


def test_stop_reason_refusal_corta_limpio():
    client = FakeClient([_Resp("refusal", [])])
    events = []
    out = AgentLoop(_reg(), client).run("hola", emit=events.append)
    assert out["status"] == "error"
    assert "refusal" in out["msg"]
    assert events[-1]["type"] == "final"
    assert events[-1]["status"] == "error"
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/agent/test_loop.py -q` (desde `E:\PCW\VERA`)
Expected: los 2 tests nuevos FAIL (los viejos pasan). El fallo típico: `IndexError: pop from empty list` o un assert sobre `status`.

- [ ] **Step 3: Implementación mínima**

En `vera/agent/loop.py`, dentro de `run()`, reemplazar el bloque que arranca con el comentario `# stop_reason == "tool_use"`:

```python
            # stop_reason == "tool_use"
            messages.append({"role": "assistant", "content": resp.content})
            results = [
                self._run_tool(block, ctx, emit)
                for block in resp.content
                if getattr(block, "type", None) == "tool_use"
            ]
            messages.append({"role": "user", "content": results})
```

por:

```python
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = [
                    self._run_tool(block, ctx, emit)
                    for block in resp.content
                    if getattr(block, "type", None) == "tool_use"
                ]
                messages.append({"role": "user", "content": results})
                continue

            # max_tokens, refusal, stop_sequence o valores futuros: cortar limpio.
            # Nunca appendear un mensaje user vacío — la API lo rechaza con 400.
            msg = f"el modelo se detuvo de forma inesperada ({resp.stop_reason})"
            if emit:
                emit({"type": "final", "status": "error", "msg": msg})
            return {"status": "error", "msg": msg}
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/agent/ -q`
Expected: todos PASS (20 viejos + 2 nuevos).

- [ ] **Step 5: Commit**

```bash
git add vera/agent/loop.py tests/agent/test_loop.py
git commit -m "fix(agent): stop_reason inesperado (max_tokens/refusal) corta limpio en vez de romper la API"
```

---

## Task 2: `ToolResult` con content blocks (imágenes) + truncado de resultados grandes

Los "Ojos" de VERA (screenshot, art_critic) necesitan devolver imágenes al modelo. La API lo soporta (`tool_result.content` como lista de blocks); nuestro contrato solo soporta `str`. Además, un resultado gigante (log de UE de 50k líneas) infla el contexto sin control: se trunca con marcador.

**Files:**
- Modify: `vera/agent/tool.py` (dataclass `ToolResult`, helper `image_block`)
- Modify: `vera/agent/loop.py` (truncado en `_run_tool`)
- Test: `tests/agent/test_tool.py`, `tests/agent/test_loop.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/agent/test_tool.py`:

```python
from vera.agent.tool import image_block


def test_image_block_forma_de_la_api():
    b = image_block("QUJD", media_type="image/jpeg")
    assert b == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }


def test_tool_result_acepta_lista_de_blocks():
    blocks = [image_block("QUJD"), {"type": "text", "text": "screenshot del viewport"}]
    r = ToolResult(blocks)
    assert r.content is blocks
    assert r.is_error is False
```

(Nota: `test_tool.py` ya importa `ToolResult`; si no, agregar el import.)

Agregar al final de `tests/agent/test_loop.py`:

```python
def test_tool_result_con_blocks_pasa_intacto():
    from vera.agent.tool import image_block

    class CameraTool(Tool):
        name = "camera"
        description = "c"
        input_schema = {"type": "object", "properties": {}}
        destructive = False

        def execute(self, args, ctx):
            return ToolResult([image_block("QUJD")])

    reg = ToolRegistry()
    reg.register(CameraTool())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "camera", {})]),
        _Resp("end_turn", [_Text("vi la imagen")]),
    ])
    AgentLoop(reg, client).run("sacá una foto")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert isinstance(tr["content"], list)
    assert tr["content"][0]["type"] == "image"


def test_tool_result_largo_se_trunca():
    class VerboseTool(Tool):
        name = "verbose"
        description = "v"
        input_schema = {"type": "object", "properties": {}}
        destructive = False

        def execute(self, args, ctx):
            return ToolResult("x" * 50_000)

    reg = ToolRegistry()
    reg.register(VerboseTool())
    client = FakeClient([
        _Resp("tool_use", [_ToolUse("t1", "verbose", {})]),
        _Resp("end_turn", [_Text("ok")]),
    ])
    AgentLoop(reg, client).run("dale")
    tr = client.messages.calls[1]["messages"][-1]["content"][0]
    assert len(tr["content"]) < 50_000
    assert "truncado" in tr["content"]
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/agent/ -q`
Expected: FAIL — `ImportError: cannot import name 'image_block'` y los asserts de truncado.

- [ ] **Step 3: Implementación**

En `vera/agent/tool.py`, reemplazar la dataclass `ToolResult` por:

```python
@dataclass
class ToolResult:
    """Resultado de ejecutar una tool. `content` vuelve al modelo.

    `content` puede ser un string (texto plano) o una lista de content blocks
    de la API — p.ej. texto + imagen para tools de percepción (ver `image_block`).
    """
    content: Any
    is_error: bool = False


def image_block(data_b64: str, media_type: str = "image/png") -> dict:
    """Content block de imagen (base64) para devolver en un ToolResult."""
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data_b64},
    }
```

En `vera/agent/loop.py`:

1. Agregar la constante debajo de `MAX_ITERATIONS = 20`:

```python
MAX_TOOL_RESULT_CHARS = 20_000  # un log gigante no debe inflar el contexto sin control
```

2. En `_run_tool`, después del bloque `try/except` que ejecuta la tool y antes del `if emit:` final, insertar:

```python
        if isinstance(result.content, str) and len(result.content) > MAX_TOOL_RESULT_CHARS:
            result = ToolResult(
                result.content[:MAX_TOOL_RESULT_CHARS]
                + f"\n[...resultado truncado: {len(result.content)} caracteres en total]",
                is_error=result.is_error,
            )
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/agent/ -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add vera/agent/tool.py vera/agent/loop.py tests/agent/test_tool.py tests/agent/test_loop.py
git commit -m "feat(agent): ToolResult con content blocks (imagenes) y truncado de resultados grandes"
```

---

## Task 3: Streaming + thinking al timeline de la UI

El loop usa `messages.create` no-streaming: con thinking adaptativo los turnos largos son silencio total en la UI y riesgo de timeout HTTP. Se migra a `messages.stream` y se emiten los deltas de thinking como eventos `{"type": "thinking", "msg": ...}`. Los deltas de **texto** NO se emiten (el evento `final` ya pinta la respuesta completa; emitir ambos duplicaría la burbuja).

**Files:**
- Create: `tests/agent/fakes.py` (fakes compartidos, ahora con forma streaming)
- Modify: `vera/agent/loop.py` (de `create` a `stream`, método `_call_llm`)
- Modify: `tests/agent/test_loop.py` (usar los fakes compartidos)

- [ ] **Step 1: Crear los fakes compartidos**

Crear `tests/agent/fakes.py`:

```python
"""Fakes que imitan la forma streaming del SDK de Anthropic, compartidos por los tests."""


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


class _ThinkingDelta:
    type = "thinking_delta"

    def __init__(self, thinking):
        self.thinking = thinking


class _StreamEvent:
    type = "content_block_delta"

    def __init__(self, delta):
        self.delta = delta


def thinking_event(text):
    return _StreamEvent(_ThinkingDelta(text))


class _FakeStream:
    """Context manager que itera eventos y devuelve el mensaje final."""

    def __init__(self, resp, events=()):
        self._resp = resp
        self._events = list(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._resp


class _FakeMessages:
    """Cada entrada de `scripted` es un _Resp o una tupla (_Resp, [eventos])."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        item = self._scripted.pop(0)
        resp, events = item if isinstance(item, tuple) else (item, ())
        return _FakeStream(resp, events)


class FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)
```

- [ ] **Step 2: Migrar `test_loop.py` a los fakes compartidos y agregar el test de thinking**

En `tests/agent/test_loop.py`, borrar las clases inline `_Text`, `_ToolUse`, `_Resp`, `_FakeMessages`, `FakeClient` (líneas 6-41 del archivo actual) y reemplazar por:

```python
from tests.agent.fakes import FakeClient, _Resp, _Text, _ToolUse, thinking_event
```

(El resto de los tests no cambia: la interfaz de `FakeClient` es la misma.)

Agregar al final del archivo:

```python
def test_streaming_emite_thinking_al_timeline():
    client = FakeClient([
        (_Resp("end_turn", [_Text("listo")]), [thinking_event("primero miro el nivel...")]),
    ])
    events = []
    AgentLoop(_reg(), client).run("x", emit=events.append)
    assert {"type": "thinking", "msg": "primero miro el nivel..."} in events


def test_request_pide_thinking_summarized():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    AgentLoop(_reg(), client).run("x")
    kwargs = client.messages.calls[0]
    assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
```

- [ ] **Step 3: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/agent/test_loop.py -q`
Expected: FAIL masivo con `AttributeError: '_FakeMessages' object has no attribute 'create'` (el loop todavía llama `create`). Eso confirma que los fakes nuevos están enchufados.

- [ ] **Step 4: Migrar el loop a streaming**

En `vera/agent/loop.py`, dentro de `run()`, reemplazar la llamada:

```python
            resp = self.llm.messages.create(
                model=self.model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=self.system,
                tools=tools,
                messages=messages,
            )
```

por:

```python
            resp = self._call_llm(messages, tools, emit)
```

y agregar el método al final de la clase:

```python
    def _call_llm(self, messages, tools, emit):
        """Una llamada streaming al modelo. Emite los deltas de thinking al
        timeline (en claude-opus-4-8 el thinking viene omitido salvo que se
        pida display=summarized). El texto NO se emite por delta: el evento
        `final` ya pinta la respuesta completa."""
        with self.llm.messages.stream(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive", "display": "summarized"},
            system=self.system,
            tools=tools,
            messages=messages,
        ) as stream:
            for event in stream:
                if (
                    emit
                    and getattr(event, "type", None) == "content_block_delta"
                    and getattr(getattr(event, "delta", None), "type", None) == "thinking_delta"
                    and event.delta.thinking
                ):
                    emit({"type": "thinking", "msg": event.delta.thinking})
            return stream.get_final_message()
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/agent/ -q`
Expected: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add vera/agent/loop.py tests/agent/fakes.py tests/agent/test_loop.py
git commit -m "feat(agent): loop streaming con thinking summarized emitido al timeline"
```

---

## Task 4: `AgentSession` — historial persistente entre comandos + `inject()`

Hoy `run()` arranca `messages` desde cero por comando: "creá un cubo" → "ahora hacelo rojo" falla porque VERA no recuerda el cubo. `AgentSession` es dueña del historial; `vera_server` mantiene UNA sesión viva (en vez de reconstruir loop+registry por comando). `inject()` es el punto de entrada de los watchers de Fase 3.

**Files:**
- Create: `vera/agent/session.py`
- Modify: `vera/agent/loop.py` (parámetros `messages` y `confirm` en `run()`)
- Modify: `vera/core/vera_server.py:80-89` (sesión cacheada)
- Test: `tests/agent/test_session.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/agent/test_session.py`:

```python
from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.session import MAX_HISTORY_MESSAGES, AgentSession
from tests.agent.fakes import FakeClient, _Resp, _Text


def test_el_historial_sobrevive_entre_comandos():
    loop_client = FakeClient([
        _Resp("end_turn", [_Text("cubo creado")]),
        _Resp("end_turn", [_Text("ahora es rojo")]),
    ])
    s = AgentSession(AgentLoop(ToolRegistry(), loop_client))
    s.run("creá un cubo")
    s.run("hacelo rojo")
    # la segunda request debe llevar el turno anterior completo
    msgs = loop_client.messages.calls[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "creá un cubo"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[2] == {"role": "user", "content": "hacelo rojo"}


def test_inject_agrega_un_turno_proactivo():
    client = FakeClient([_Resp("end_turn", [_Text("arreglado")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    out = s.inject("Error de compilación en el log: arreglalo si es seguro.")
    assert out["status"] == "success"
    assert s.messages[0]["role"] == "user"


def test_trim_corta_en_turno_user_de_texto_plano():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    # historial sintético más largo que el máximo, con pares tool_use/tool_result
    for i in range(MAX_HISTORY_MESSAGES):
        s.messages.append({"role": "user", "content": f"comando {i}"})
        s.messages.append({"role": "assistant", "content": [{"type": "tool_use"}]})
        s.messages.append({"role": "user", "content": [{"type": "tool_result"}]})
        s.messages.append({"role": "assistant", "content": [{"type": "text"}]})
    s.run("último comando")
    assert len(s.messages) <= MAX_HISTORY_MESSAGES + 2  # +turno nuevo y respuesta
    # nunca arrancar el historial en medio de un par tool_use/tool_result
    assert s.messages[0]["role"] == "user"
    assert isinstance(s.messages[0]["content"], str)
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/agent/test_session.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'vera.agent.session'`.

- [ ] **Step 3: Adaptar `AgentLoop.run` para historial externo y confirm por-run**

En `vera/agent/loop.py`, reemplazar la firma y el arranque de `run()`:

```python
    def run(self, command: str, emit: Optional[Callable[[dict], None]] = None) -> dict:
        ctx = ToolContext(bridge_port=self.bridge_port, emit=emit, llm=self.llm)
        messages = [{"role": "user", "content": command}]
        tools = self.registry.to_anthropic()
```

por:

```python
    def run(
        self,
        command: str,
        emit: Optional[Callable[[dict], None]] = None,
        *,
        messages: Optional[list] = None,
        confirm: Optional[Callable] = None,
    ) -> dict:
        """`messages`: historial externo (lo muta in place — lo posee la Session).
        `confirm`: override por-comando del gate destructivo (p.ej. el round-trip
        a la UI de la conexión en curso)."""
        ctx = ToolContext(bridge_port=self.bridge_port, emit=emit, llm=self.llm)
        confirm = confirm if confirm is not None else self.confirm
        if messages is None:
            messages = []
        messages.append({"role": "user", "content": command})
        tools = self.registry.to_anthropic()
```

En la rama `end_turn`, agregar el append del turno final ANTES del return (para que el historial quede completo):

```python
            if resp.stop_reason == "end_turn":
                messages.append({"role": "assistant", "content": resp.content})
                text = _final_text(resp.content)
                if emit:
                    emit({"type": "final", "status": "success", "msg": text})
                return {"status": "success", "msg": text}
```

En `_run_tool`, cambiar la firma a `def _run_tool(self, block, ctx, emit, confirm):` y el gate de `self.confirm` a la variable local:

```python
        if tool.destructive and confirm and not confirm(tool, block.input):
            return _tool_result(block.id, "El usuario rechazó la acción.", True)
```

y en `run()` pasar `confirm` en la list comprehension:

```python
                results = [
                    self._run_tool(block, ctx, emit, confirm)
                    for block in resp.content
                    if getattr(block, "type", None) == "tool_use"
                ]
```

(El test existente `test_destructive_confirm_reject` pasa `confirm=` al constructor — sigue funcionando porque `confirm` local hereda de `self.confirm` cuando no hay override.)

- [ ] **Step 4: Crear la Session**

Crear `vera/agent/session.py`:

```python
"""AgentSession: conversación persistente del cerebro de VERA.

El historial sobrevive entre comandos ("creá un cubo" → "hacelo rojo" funciona).
Reactivo (chat) y proactivo (watchers, Fase 3) inyectan turnos al MISMO historial
vía run() / inject().
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

MAX_HISTORY_MESSAGES = 40  # el truncado de contexto fino llega con compaction (Fase 4)


class AgentSession:
    def __init__(self, loop) -> None:
        self.loop = loop
        self.messages: list = []
        self._lock = threading.Lock()

    def run(
        self,
        command: str,
        emit: Optional[Callable[[dict], None]] = None,
        confirm: Optional[Callable] = None,
    ) -> dict:
        with self._lock:
            self._trim()
            return self.loop.run(command, emit=emit, messages=self.messages, confirm=confirm)

    def inject(
        self,
        content: str,
        emit: Optional[Callable[[dict], None]] = None,
        confirm: Optional[Callable] = None,
    ) -> dict:
        """Turno proactivo (LogWatcher/FPSWatcher en Fase 3): mismo loop, otra fuente."""
        return self.run(content, emit=emit, confirm=confirm)

    def _trim(self) -> None:
        """Mantiene el historial acotado. Después de podar, el historial debe
        arrancar SIEMPRE en un turno user de texto plano: cortar en medio de un
        par tool_use/tool_result es un 400 de la API."""
        if len(self.messages) <= MAX_HISTORY_MESSAGES:
            return
        del self.messages[: len(self.messages) - MAX_HISTORY_MESSAGES]
        while self.messages and not (
            self.messages[0].get("role") == "user"
            and isinstance(self.messages[0].get("content"), str)
        ):
            self.messages.pop(0)
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/agent/ -q`
Expected: todos PASS.

- [ ] **Step 6: Sesión cacheada en `vera_server`**

En `vera/core/vera_server.py`:

1. En `__init__`, después de `self._busy = threading.Lock()`, agregar:

```python
        self._session = None  # AgentSession persistente (solo con VERA_USE_AGENT_LOOP)
```

2. Agregar el método (debajo de `handle_client`):

```python
    def _agent_session(self):
        """Sesión agéntica persistente: el historial sobrevive entre comandos.
        Lazy: solo se construye si el flag está activo."""
        if self._session is None:
            import anthropic
            from vera.agent.factory import build_agent_loop
            from vera.agent.session import AgentSession
            self._session = AgentSession(build_agent_loop(anthropic.Anthropic()))
        return self._session
```

3. Reemplazar la rama del flag en `handle_client` (líneas 80-89):

```python
                # Cerebro agéntico (Fase 1): activable por env var, Manager como fallback.
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

por:

```python
                # Cerebro agéntico: sesión persistente (historial entre comandos),
                # Manager viejo como fallback si el flag está apagado.
                if os.environ.get("VERA_USE_AGENT_LOOP"):
                    result = self._agent_session().run(command, emit=emit)
                    success = result.get("status") == "success"
                    return
```

4. Verificar que importa limpio: `python -c "import vera.core.vera_server"`

- [ ] **Step 7: Commit**

```bash
git add vera/agent/session.py vera/agent/loop.py vera/core/vera_server.py tests/agent/test_session.py
git commit -m "feat(agent): AgentSession con historial persistente e inject(); vera_server reusa una sesion viva"
```

---

## Task 5: Gate de confirmación real — round-trip server↔cliente

El gate destructivo está apagado en producción: `run_ue_python` (destructiva, la única tool real) ejecuta código arbitrario sin pedir OK jamás. Se activa: el server emite `{"type": "question", ...}` por el socket de la conexión en curso y espera UNA línea JSON `{"approve": bool}` del cliente. **Ante la duda, denegar** (timeout de 120s, desconexión, JSON inválido — decisión del spec §6: destructiva pide OK siempre). `VERA_AUTO_APPROVE=1` saltea el gate (autopilot/testing).

**Files:**
- Modify: `vera/core/vera_server.py`
- Test: `tests/agent/test_confirm_gate.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/agent/test_confirm_gate.py`:

```python
import json
import socket
from types import SimpleNamespace

import vera.core.vera_server as vs


def _confirm_pair():
    """Un VeraServer sin bind ni manager + un par de sockets conectados."""
    srv = vs.VeraServer.__new__(vs.VeraServer)  # sin __init__: solo usamos _make_confirm
    a, b = socket.socketpair()
    events = []
    return srv._make_confirm(a, events.append), a, b, events


_TOOL = SimpleNamespace(name="run_ue_python")


def test_aprueba_cuando_el_cliente_responde_approve_true():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"approve": true}\n')
    assert confirm(_TOOL, {"code": "unreal.log('x')"}) is True
    assert events[0]["type"] == "question"
    assert events[0]["tool"] == "run_ue_python"
    a.close(); b.close()


def test_deniega_cuando_el_cliente_responde_false():
    confirm, a, b, events = _confirm_pair()
    b.sendall(b'{"approve": false}\n')
    assert confirm(_TOOL, {}) is False
    a.close(); b.close()


def test_deniega_si_el_cliente_se_desconecta():
    confirm, a, b, events = _confirm_pair()
    b.close()  # desconexión antes de responder
    assert confirm(_TOOL, {}) is False
    a.close()


def test_auto_approve_saltea_el_gate(monkeypatch):
    monkeypatch.setenv("VERA_AUTO_APPROVE", "1")
    confirm, a, b, events = _confirm_pair()
    # no se envía respuesta: si el gate leyera del socket, colgaría
    assert confirm(_TOOL, {}) is True
    assert events == []  # ni siquiera pregunta
    a.close(); b.close()
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/agent/test_confirm_gate.py -q`
Expected: FAIL con `AttributeError: 'VeraServer' object has no attribute '_make_confirm'`.

- [ ] **Step 3: Implementar `_make_confirm`**

En `vera/core/vera_server.py`:

1. Constante debajo de `logger = ...`:

```python
CONFIRM_TIMEOUT = 120.0  # segundos para que el usuario apruebe una accion destructiva
```

2. Método nuevo (debajo de `_make_emitter`):

```python
    def _make_confirm(self, conn, emit):
        """Gate destructivo con round-trip al cliente: emite un evento `question`
        y espera UNA línea JSON {"approve": bool} por el mismo socket.
        Ante la duda (timeout, desconexión, JSON inválido) DENIEGA.
        VERA_AUTO_APPROVE=1 saltea el gate (autopilot/testing)."""
        def confirm(tool, args):
            if os.environ.get("VERA_AUTO_APPROVE"):
                return True
            emit({
                "type": "question",
                "tool": tool.name,
                "msg": f"VERA quiere ejecutar la acción destructiva '{tool.name}'. ¿Aprobar?",
                "args_preview": str(args)[:500],
            })
            try:
                conn.settimeout(CONFIRM_TIMEOUT)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(4096)
                    if not chunk:
                        return False  # cliente desconectado → denegar
                    data += chunk
                return bool(json.loads(data.decode("utf-8").strip()).get("approve"))
            except (OSError, ValueError):
                return False  # timeout o respuesta inválida → denegar
            finally:
                try:
                    conn.settimeout(None)
                except OSError:
                    pass
        return confirm
```

3. En `handle_client`, conectar el gate a la sesión (la rama del flag de Task 4):

```python
                if os.environ.get("VERA_USE_AGENT_LOOP"):
                    result = self._agent_session().run(
                        command, emit=emit, confirm=self._make_confirm(conn, emit))
                    success = result.get("status") == "success"
                    return
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/agent/ -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add vera/core/vera_server.py tests/agent/test_confirm_gate.py
git commit -m "feat(server): gate destructivo real con round-trip question/approve (deny por defecto, VERA_AUTO_APPROVE para autopilot)"
```

---

## Task 6: UI — botones Aprobar/Rechazar y thinking en vivo

La UI mantiene el socket abierto durante todo el comando (`vera_ui.py:_stream_command`), así que la respuesta viaja por la misma conexión. El hilo lector se bloquea en una `queue.Queue` hasta que el usuario toca un botón (el slot `answer_question` la llena desde JS). Timeout de UI: 110s (menor que los 120s del server, para que la UI siempre conteste antes de que el server deniegue por su cuenta).

**Files:**
- Modify: `UE57/Content/Python/vera_ui.py` (cola de respuestas, slot del bridge, manejo del evento `question` en `_stream_command`)
- Modify: `UE57/Content/Python/vera_chat/chat.js` (casos `question` y `thinking` en el dispatch)
- Modify: `UE57/Content/Python/vera_chat/chat.css` (estilos de la pregunta y el thinking)

**Regla de seguridad de la UI (no negociable):** todo dato dinámico entra al DOM con `textContent` / `createTextNode`, NUNCA `innerHTML` (la sesión anterior encontró y arregló un XSS — no reintroducirlo).

- [ ] **Step 1: Cola de respuestas + slot en `vera_ui.py`**

1. En los imports del módulo (junto a `threading`), agregar:

```python
import queue
```

2. Junto a la declaración global `_pending_events = []` (línea ~41), agregar:

```python
_answer_queue = queue.Queue()  # respuestas aprobar/denegar (JS → hilo lector del stream)
CONFIRM_UI_TIMEOUT = 110.0     # menor que el timeout del server (120s)
```

3. En la clase `Bridge` (la que tiene `@Slot(str) def send_command`, línea ~73), agregar el slot:

```python
    @Slot(bool)
    def answer_question(self, approve):
        """El usuario tocó Aprobar/Rechazar en el chat (round-trip del gate)."""
        _answer_queue.put(bool(approve))
```

- [ ] **Step 2: Manejar el evento `question` en `_stream_command`**

En `vera_ui.py`, dentro del loop de eventos de `_stream_command` (línea ~214), reemplazar:

```python
                        _pending_events.append(event)
                        if event.get("type") == "final":
                            return
```

por:

```python
                        if event.get("type") == "question":
                            # Round-trip del gate destructivo: mostrar la pregunta
                            # y esperar la decisión del usuario (botones en el chat).
                            while not _answer_queue.empty():
                                _answer_queue.get_nowait()  # descartar respuestas viejas
                            _pending_events.append(event)
                            try:
                                approve = _answer_queue.get(timeout=CONFIRM_UI_TIMEOUT)
                            except queue.Empty:
                                approve = False
                                _pending_events.append({
                                    "type": "progress", "agent": "Gate",
                                    "msg": "sin respuesta del usuario — acción denegada"})
                            s.sendall((json.dumps({"approve": approve}) + "\n").encode("utf-8"))
                            continue
                        _pending_events.append(event)
                        if event.get("type") == "final":
                            return
```

Nota: mientras el hilo espera en `_answer_queue.get` NO está en `recv`, así que el `settimeout` del socket no corta la espera.

- [ ] **Step 3: Casos `question` y `thinking` en `chat.js`**

En `UE57/Content/Python/vera_chat/chat.js`, dentro del `switch (e.type)` del dispatch, agregar dos casos (después del caso `"progress"`):

```javascript
      case "thinking": {
        const tl = ensureTimeline();
        let th = tl.querySelector(".tl-think.live");
        if (!th) {
          th = document.createElement("div");
          th.className = "tl-item tl-think live";
          const b = document.createElement("b");
          b.textContent = "razonando";
          th.appendChild(b);
          th.appendChild(document.createTextNode(" — "));
          tl.appendChild(th);
        }
        th.lastChild.textContent += e.msg || "";
        break;
      }
      case "question": {
        const tl = ensureTimeline();
        const q = document.createElement("div");
        q.className = "tl-item question";
        const txt = document.createElement("div");
        txt.textContent = e.msg || "VERA pide confirmación.";
        q.appendChild(txt);
        if (e.args_preview) {
          const pre = document.createElement("pre");
          pre.className = "q-args";
          pre.textContent = e.args_preview;
          q.appendChild(pre);
        }
        const yes = document.createElement("button");
        yes.className = "q-btn approve";
        yes.textContent = "Aprobar";
        const no = document.createElement("button");
        no.className = "q-btn deny";
        no.textContent = "Rechazar";
        const answer = (v) => {
          yes.disabled = true;
          no.disabled = true;
          q.classList.add(v ? "approved" : "denied");
          if (pybridge) pybridge.answer_question(v);
        };
        yes.onclick = () => answer(true);
        no.onclick = () => answer(false);
        q.appendChild(yes);
        q.appendChild(no);
        tl.appendChild(q);
        break;
      }
```

Además, para que cada segmento de thinking se cierre cuando arranca otra cosa, agregar **al inicio** de los casos `"progress"` y `"final"` (antes de su código actual):

```javascript
        ensureTimeline().querySelectorAll(".tl-think.live")
          .forEach((el) => el.classList.remove("live"));
```

- [ ] **Step 4: Estilos en `chat.css`**

Agregar al final de `UE57/Content/Python/vera_chat/chat.css`:

```css
/* --- thinking en vivo (Fase 1.5) --- */
.tl-think { opacity: 0.65; font-style: italic; white-space: pre-wrap; }
.tl-think.live::after { content: "▋"; animation: blink 1s step-start infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* --- pregunta del gate destructivo (Fase 1.5) --- */
.tl-item.question { border-left: 3px solid #e0a030; padding-left: 8px; }
.tl-item.question .q-args {
  max-height: 120px; overflow: auto; font-size: 11px;
  background: rgba(0, 0, 0, 0.25); padding: 6px; border-radius: 4px;
}
.q-btn { margin: 4px 6px 0 0; padding: 4px 14px; border-radius: 6px;
         border: 1px solid transparent; cursor: pointer; }
.q-btn.approve { background: #2e7d4f; color: #fff; }
.q-btn.deny { background: #7d2e2e; color: #fff; }
.q-btn:disabled { opacity: 0.45; cursor: default; }
.tl-item.question.approved { border-left-color: #2e7d4f; }
.tl-item.question.denied { border-left-color: #7d2e2e; }
```

- [ ] **Step 5: Verificación visual en dev.html (sin UE)**

`dev.html` carga el mismo `chat.js` sin QWebChannel (`pybridge = null`). Abrirlo en un browser y en la consola:

```javascript
window.veraChat.dispatch({type: "user", msg: "probá el gate"});
window.veraChat.dispatch({type: "thinking", msg: "evaluando si la acción es segura..."});
window.veraChat.dispatch({type: "question", tool: "run_ue_python",
  msg: "VERA quiere ejecutar la acción destructiva 'run_ue_python'. ¿Aprobar?",
  args_preview: "{'code': \"unreal.log('hola')\"}"});
```

Expected: burbuja con el thinking en itálica + cursor parpadeante, y la pregunta con botones Aprobar (verde) / Rechazar (rojo). Click en un botón deshabilita ambos (con `pybridge = null` no manda nada — correcto).

- [ ] **Step 6: Verificación de sintaxis Python**

Run: `python -c "import ast; ast.parse(open('E:/PCW/VERA/UE57/Content/Python/vera_ui.py', encoding='utf-8').read())"`
Expected: sin error.

- [ ] **Step 7: Commit**

```bash
git add UE57/Content/Python/vera_ui.py UE57/Content/Python/vera_chat/chat.js UE57/Content/Python/vera_chat/chat.css
git commit -m "feat(ui): botones aprobar/rechazar del gate destructivo y thinking en vivo en el timeline"
```

---

## Verificación end-to-end (manual, con UE abierto)

> La prueba viva del contrato — alineada con el feedback "verificar antes de declarar éxito". No es un step automatizado.

1. Con UE abierto, recargar el módulo del server vía bridge 9878 (hot-reload, sin reiniciar UE) o levantar `vera_server` nuevo con `VERA_USE_AGENT_LOOP=1` (SIN `VERA_AUTO_APPROVE`).
2. En la UI de VERA: **"creá un cubo en el origen del nivel"**.
   - Esperado: thinking en vivo en el timeline → pregunta con botones → al Aprobar, `tool_use`/`tool_result` → `final` success y el cubo en el viewport.
3. Segundo comando: **"ahora movelo 500 unidades arriba"**.
   - Esperado: VERA recuerda el cubo del turno anterior (historial persistente) y lo mueve sin preguntar "¿qué cubo?".
4. Tercer comando con **Rechazar** en la pregunta.
   - Esperado: el `tool_result` informa el rechazo y VERA cierra el turno sin ejecutar nada en el editor.
5. Dejar pasar un timeout (no contestar la pregunta ~2 min).
   - Esperado: denegación automática, evento "sin respuesta del usuario — acción denegada", el server no queda colgado y acepta el siguiente comando.

---

## Self-Review (cobertura de los hallazgos de la revisión 2026-06-11)

- **Bug stop_reason (hallazgo 1):** Task 1. ✅
- **Gate destructivo apagado (hallazgo 2):** Tasks 5 + 6 (server round-trip + UI). ✅
- **Thinking invisible / sin streaming (hallazgo 3):** Task 3 (stream + display summarized + evento `thinking`), Task 6 (render). ✅
- **Amnesia conversacional + inject para Fase 3 (hallazgo 4):** Task 4 (`AgentSession`). ✅
- **ToolResult solo texto + resultados sin límite (hallazgo 5):** Task 2. ✅
- **Loop reconstruido por comando (menor):** Task 4 Step 6 (sesión cacheada en `vera_server`). ✅
- **Menores diferidos a Fase 2:** helper `ctx.run_in_editor()` (se hace al escribir la 2ª tool dedicada, donde la duplicación se materializa), `discover` instancia dos veces / duplicados con log+skip (decisión de contrato público, no urgente). Anotados en el plan de Fase 2.
