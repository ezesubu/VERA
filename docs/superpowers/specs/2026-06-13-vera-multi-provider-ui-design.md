# VERA multi-proveedor + UI tipo Claude Code — Diseño

**Fecha:** 2026-06-13
**Branch:** feature/ui-redesign
**Estado:** aprobado (brainstorming) → pendiente plan de implementación

## Problema

VERA hoy solo puede pensar con Anthropic (`anthropic.Anthropic()` hardcodeado en
`vera_server.py:176`, modelo `claude-opus-4-8` fijo en `vera/agent/loop.py`). Con las
API keys de Anthropic/Gemini muertas, el cerebro agéntico quedó bloqueado. El usuario
corre **LM Studio** local (endpoint OpenAI-compatible en `http://172.21.80.1:1233`) y
necesita poder usarlo como cerebro. Además no hay UI para elegir proveedor/modelo ni
para configurar las credenciales: la experiencia deseada es "como Claude Code" —
agente autónomo que pide permiso solo en lo destructivo— **no** el Plan/Act rígido de
Cline/Antigravity.

## Arquitectura existente (no se rompe)

- **UI:** `vera_ui.py` levanta un `QWebEngineView` (PySide6) parentado a la ventana de
  Unreal (`parent_external_window_to_slate`), bombeado por el tick del editor. El chat
  (`vera_chat/index.html` + `chat.js` + `chat.css`) es web puro. Puente JS↔Python por
  **QWebChannel** (`pybridge`): `send_command`, `answer_question`, `js_ready`,
  `open_image`. Hay un modo dev standalone (`dev.html` + `dev.js`) que corre en un
  navegador sin Qt.
- **Backend:** `VeraServer` (socket 127.0.0.1:9880) stremea eventos JSON por línea
  (`user/progress/thinking/tool_use/image/question/final/...`). Con
  `VERA_USE_AGENT_LOOP`, una `AgentSession` persistente corre `AgentLoop`, que consume
  la superficie de Anthropic: `llm.messages.stream(model, max_tokens, thinking, system,
  tools, messages)` → `stop_reason` + `content` (bloques `text/thinking/tool_use`).
- **Tools:** auto-descubiertas en `vera/agent/tools/`, con flag `tool.destructive` y un
  gate `confirm(tool, args)` con round-trip a la UI.

## Decisión de arquitectura

Las dos restricciones del usuario —"corre dentro de Unreal" y "mi expertise es web"—
**ya las cumple el stack actual** (web embebido en Qt dentro del editor). No se migra a
UMG ni a app aparte. Se **extiende** lo existente.

### Pieza clave: adaptador que imita a Anthropic

No se reescribe `AgentLoop`. Se construye un cliente que **duck-types la superficie de
`anthropic.Anthropic`** que el loop ya usa. El loop nunca sabe qué proveedor hay detrás.
Como OpenAI, LM Studio y Gemini hablan **formato OpenAI** (Gemini vía su endpoint
OpenAI-compatible `…/v1beta/openai/`), los tres colapsan en **una sola clase**. Anthropic
queda nativo. Un adaptador nuevo cubre tres proveedores y los 130 tests del loop no se
tocan.

## Componentes

### 1. `vera/llm/openai_compat_client.py` (nuevo)
Adaptador OpenAI→Anthropic. Expone `.messages.stream(...)` como context manager que
devuelve un objeto con `.stop_reason` y `.content` (bloques). Traducciones:

- **Tools (salida):** `{name, description, input_schema}` →
  `{type:"function", function:{name, description, parameters: input_schema}}`.
- **Mensajes (salida):** el historial canónico se mantiene en forma Anthropic; se
  traduce al vuelo a formato OpenAI en cada llamada:
  - `{"role":"user","content":"str"}` → igual.
  - `{"role":"assistant","content":[blocks]}` → mensaje assistant con `content` = texto
    concatenado y `tool_calls` = `[{id, type:"function", function:{name,
    arguments: json.dumps(input)}}]` por cada bloque `tool_use`.
  - `{"role":"user","content":[tool_result...]}` → un `{"role":"tool", tool_call_id,
    content}` por cada `tool_result`.
- **Respuesta (entrada):** `choices[0].message`; si hay `tool_calls` → bloques
  `[text?, tool_use(id, name, input=json.loads(arguments))]` con `stop_reason="tool_use"`;
  si no → `[text]` con `stop_reason="end_turn"`.
- Usa el SDK `openai` (ya dependencia). Config: `base_url`, `api_key`, `model`.
- **Streaming/thinking:** v1 no emite `thinking` en vivo para estos proveedores (el loop
  igual pinta el texto final). Si el modelo expone `reasoning_content`, se puede mapear
  a eventos `thinking` en una iteración futura.

**Propiedad lateral valiosa:** como el historial canónico queda en forma Anthropic
independientemente del proveedor, **se puede cambiar de proveedor a mitad de sesión sin
perder el historial** (decisión tomada: conservar historial al cambiar de modelo).

### 2. Registro de modelos — `vera/agent/models.py` (nuevo)
Lista los combos provider+modelo del selector y qué credencial/env necesita cada uno:

```
PROVIDERS = {
  "ANTHROPIC": {label, models:[...], env:"ANTHROPIC_API_KEY", native:True},
  "OPENAI":    {label, models:[...], env:"OPENAI_API_KEY",   base_url:default},
  "GEMINI":    {label, models:[...], env:"GEMINI_API_KEY",   base_url:".../v1beta/openai/"},
  "LOCAL":     {label:"LM Studio", base_url:"http://172.21.80.1:1233/v1", env:None,
                discover:True},
}
```

- **Autodescubrimiento (decisión tomada):** para `LOCAL`, `list_models()` consulta
  `GET {base_url}/models` en vivo y devuelve los modelos cargados en LM Studio. Si el
  server local no responde, cae a una lista vacía con estado "offline".
- Modelos local recomendados (tool-calling sólido): Qwen2.5-Coder-32B-Instruct,
  Llama-3.3-70B-Instruct. Se documenta en la UI de setup.

### 3. `vera/agent/factory.py` — `make_llm_client(provider, model)`
Devuelve `anthropic.Anthropic()` (ANTHROPIC) o `OpenAICompatClient(base_url, key, model)`
(LOCAL/OPENAI/GEMINI). `build_agent_loop` acepta `provider`/`model`.

### 4. `vera_server.py` — selección y modos por comando
El payload del socket pasa de `{"command"}` a
`{"command", "provider", "model", "mode"}`. Antes de correr, el server reconfigura
`loop.llm` (vía `make_llm_client`) y `loop.model`. Sin estado pegajoso por turno.

- Nuevo endpoint de control (comando especial JSON, p.ej. `{"op":"list_models",
  "provider":"LOCAL"}`) para que la UI liste modelos y verifique credenciales/estado sin
  correr el agente.

### 5. Permisos híbridos (sobre primitivas existentes)
`mode ∈ {ask, auto, readonly}`:

- **ask** (default): `confirm` gate actual dispara en tools `destructive`.
- **auto**: `confirm` devuelve `True` (equivale a `VERA_AUTO_APPROVE`).
- **readonly / "planear esta vez"**: al armar `registry.to_anthropic()` se filtran las
  tools `destructive` → el modelo ni las ve. Reusa `tool.destructive`. El botón "planear
  esta vez" es un `readonly` de un solo turno sin cambiar el modo persistente.

### 6. UI web (`vera_chat/`)
- **Selector de modelo** en el header: provider + modelo (modelos local autodescubiertos).
- **Selector de modo:** Ask / Auto / Solo-lectura, + botón "Planear esta vez".
- **Panel de setup** (engranaje): tarjetas por proveedor con input de API key (enmascarada,
  "probar conexión"), y para LM Studio: campo de base URL (default
  `http://172.21.80.1:1233`), botón "Detectar modelos" (`/v1/models`), estado en vivo.
  Onboarding de primer uso si no hay proveedor configurado.
- Nuevos slots en `PyBridge`: `set_model(provider, model)`, `set_mode(mode)`,
  `list_models(provider)`, `save_credentials(provider, key)`, `test_connection(provider)`.
- El `send_command` enriquece el payload con `provider/model/mode`.
- **Persistencia de credenciales:** se escriben al `.env` del repo (mismo que ya lee
  `VeraServer._load_env`); las keys nunca viajan al frontend una vez guardadas (solo
  estado "configurado/no configurado").

## Fases (cada una testeable sola)

1. **Backend core:** `OpenAICompatClient` + traducción + tests con fake OpenAI client.
   `make_llm_client`. Esto solo ya corre el cerebro en LM Studio/OpenAI/Gemini.
2. **Plumbing + permisos:** payload extendido, reconfig por turno, modos de permiso,
   `models.py` + autodescubrimiento, endpoint `list_models`/`test_connection`.
3. **UI:** dropdown de modelo + modos + "planear esta vez" + panel de setup + slots del
   bridge + persistencia de credenciales.

## Error handling

- Proveedor sin credencial → la UI lo marca "no configurado"; correr con él devuelve un
  `final` de error claro, no un stacktrace.
- LM Studio sin modelo cargado / inalcanzable → estado "offline" en el selector; correr
  devuelve error guía ("cargá un modelo en LM Studio").
- Modelo local sin tool-calling → el loop puede no avanzar; se mitiga recomendando
  modelos capaces en el setup. Riesgo aceptado y documentado, no bloqueante del diseño.
- Cambio de proveedor a mitad de sesión: soportado (historial canónico Anthropic).

## Testing

- Unit: traducción tools/mensajes/respuesta del adaptador (fake OpenAI client), ambos
  sentidos, incluyendo multi tool_call en un turno.
- Unit: `make_llm_client` por proveedor; `models.py` autodescubrimiento con server fake.
- Unit: modos de permiso (ask/auto/readonly) sobre el filtro de tools y el confirm.
- Integración: `vera_server` con payload `{command, provider, model, mode}` reconfigura
  el loop (con loop fake).
- UI: el modo dev standalone (`dev.js`) demuestra setup + selector + modos con datos mock.

## Fuera de alcance (YAGNI)

- Streaming de `thinking` en vivo para proveedores no-Anthropic.
- Multi-usuario / varias sesiones concurrentes.
- Cifrado de credenciales más allá del `.env` (el repo ya asume `.env` local).
- Plan/Act rígido tipo Cline (rechazado por el usuario).
