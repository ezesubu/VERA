# VERA MCP Bridge — Diseño

**Fecha:** 2026-06-10
**Estado:** Aprobado por el usuario (brainstorming 2026-06-10)
**Objetivo de la iteración:** que Claude Code (terminal) controle el editor de Unreal con un "loop completo con ojos": comando → acción en el editor → captura del viewport → iteración autónoma.

## Contexto

VERA ya tiene dos canales TCP locales:

- **Bridge** (`vera/tools/ue_bridge_server.py`, puerto `9878`): corre dentro del editor, recibe `{"script": "..."}` y ejecuta Python en el main thread vía slate tick callback, devolviendo stdout capturado y traceback. Hoy requiere pegar el script a mano en la consola Python del editor.
- **Backend VERA** (`vera/core/vera_server.py`, puerto `9880`): recibe `{"command": "..."}` y lo enruta al `ManagerAgent` (pipeline de agentes/recetas).

Falta el ciclo de vida (auto-arranque del bridge), los "ojos" (screenshot + log) y una integración de primera clase con Claude Code. Se eligió **servidor MCP** sobre un CLI delgado o llamadas ad-hoc, priorizando herramientas nativas con esquemas/permisos en Claude Code y reutilización por cualquier cliente MCP (valor de producto para Fab).

## Definition of Done

Desde la terminal, Claude Code puede: recibir un pedido ("poné un puente de vidrio"), ejecutarlo en el editor con `ue_exec`, verificar el resultado con `ue_screenshot`, diagnosticar con `ue_log` si quedó mal, y corregir sin intervención del usuario.

## Arquitectura

```
Claude Code ⇄ (stdio MCP) ⇄ vera/tools/mcp_server.py ⇄ (TCP 127.0.0.1) ⇄ Unreal Editor
                                   │                        :9878 bridge (exec main-thread)
                                   │                        :9880 backend VERA (agentes)
                                   └── lee UE57/Saved/Logs/UE57.log directo (sin bridge)
```

### Componente 1: `vera/tools/mcp_server.py` (nuevo)

Servidor MCP en Python usando FastMCP (SDK oficial `mcp`), proceso stdio lanzado por Claude Code y registrado en `.mcp.json` del proyecto. No toca la API de Unreal: traduce herramientas MCP a llamadas TCP, con timeouts y errores accionables.

### Componente 2: Bridge endurecido (existente → `UE57/Content/Python/vera_bridge.py`)

- **Auto-start:** `UE57/Content/Python/init_unreal.py` importa y arranca el bridge al abrir el proyecto. Se elimina el paso manual.
- **Framing:** respuestas JSON delimitadas por newline en ambas direcciones (hoy el request usa `\n` pero la respuesta se lee "hasta cerrar conexión").
- **Helper de screenshot:** función del lado UE que captura el viewport activo a PNG en una ruta conocida (`UE57/Saved/VERA/screenshots/`).

### Componente 3: Backend VERA (sin cambios estructurales)

El MCP server reenvía `vera_command` al puerto 9880 igual que lo hace hoy la UI PySide6.

## Herramientas MCP

| Herramienta | Parámetros | Canal | Devuelve |
|---|---|---|---|
| `ue_exec` | `script: str`, `timeout: float = 60` | TCP 9878 | stdout capturado + traceback si falló |
| `ue_screenshot` | — | TCP 9878 + archivo | imagen PNG como contenido MCP (Claude la ve) |
| `ue_log` | `lines: int = 100` | archivo directo | últimas N líneas de `UE57/Saved/Logs/UE57.log` |
| `ue_status` | — | TCP 9878 y 9880 | estado de bridge y backend + versión del editor |
| `vera_command` | `text: str` | TCP 9880 | respuesta del pipeline de agentes |

`ue_log` lee el archivo directamente a propósito: funciona aunque el editor esté colgado o crasheado, que es cuando más se necesita.

## Manejo de errores

- **Editor cerrado / bridge no cargado:** `ConnectionRefusedError` → mensaje accionable ("Unreal no está corriendo o el bridge no cargó; abrí UE57 o ejecutá `import vera_bridge` en la consola Python"). Nunca traceback crudo del MCP server.
- **Error de Python dentro de UE:** el traceback del editor se devuelve como resultado normal de `ue_exec` (no como fallo de herramienta), para que el agente lo lea y corrija.
- **Timeouts:** `ue_exec` con timeout configurable (default 60 s); al expirar responde "sigue ejecutando" — el main thread de UE no se aborta.
- **Screenshot fallido:** si el PNG no aparece en el tiempo esperado, se devuelve el error del bridge + sugerencia de usar `ue_log`.

## Testing

- **Unit tests** (`tests/test_mcp_server.py`): fake bridge TCP en puerto efímero; cubre framing, timeouts, traducción de errores y parsing de log con archivo de muestra. No requiere Unreal.
- **Smoke test de integración** (manual, documentado en el spec de implementación): editor abierto → `ue_status` → `ue_exec("print(unreal.SystemLibrary.get_engine_version())")` → `ue_screenshot` → verificar PNG.
- **Test de aceptación:** la demo del loop con ojos (construir algo visible, verlo, corregirlo solo).

## Fuera de alcance (esta iteración)

- UI PySide6 (progreso de agentes, markdown, historial) — próximo spec.
- Cambiar el LLM default del backend de Gemini a Claude (`llm_factory`) — iteración aparte.
- Acceso remoto/autenticación: todo en `127.0.0.1`.
- Streaming de output parcial de scripts largos.
