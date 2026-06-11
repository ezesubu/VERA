# VERA — Cerebro Agéntico (Diseño de Arquitectura)

> Estado: **propuesta para revisión** · Fecha: 2026-06-11 · Rama: `feature/ui-redesign`
> Reemplaza la orquestación actual (Manager `if/elif` + GOAP) por un agente nativo de tool-use.

---

## 1. Objetivo y visión

VERA debe ser un **ingeniero técnico autónomo de Unreal Engine** — el "desarrollador junior" que escribe código, lo prueba, lee los errores, los corrige y versiona, sin intervención manual. La arquitectura actual creció orgánicamente y hoy pelea consigo misma: dos "cerebros" desconectados, ruteo duplicado, y agregar una capacidad obliga a editar archivos centrales.

Este diseño unifica todo en **un único bucle agéntico** sobre un modelo moderno de Anthropic, con una superficie de herramientas extensible pensada para un proyecto que será **público y colaborativo**.

### Principios

1. **El modelo decide, no el `if/elif`.** El cerebro es un bucle de tool-use; el LLM elige y encadena herramientas, planifica con thinking adaptativo, y delega.
2. **Un cerebro, dos fuentes de turnos.** Reactivo (chat) y proactivo (watchers) inyectan turnos al *mismo* bucle.
3. **Extensible por contrato.** Agregar una capacidad = dropear un archivo que cumple el contrato `Tool`. Cero ediciones en el core. Sin merge-hell para contribuidores.
4. **Híbrido por capas.** Una tool universal (`run_ue_python`) para amplitud; tools dedicadas solo donde se gana gate/render/paralelización/seguridad.
5. **Reusar lo que funciona.** Los 17 agentes existentes se vuelven la *lógica interna* de las tools; no se reescriben.

---

## 2. Decisiones tomadas (resumen)

| Decisión | Elección | Por qué |
|---|---|---|
| Forma del cerebro | Bucle de tool-use (agéntico) | Reemplaza router + GOAP; planning nativo |
| Reactivo vs proactivo | Ambos, unificados en un loop | Misma máquina; solo cambia quién inyecta el turno |
| Superficie de tools | Híbrido por capas | Potencia (bash-core) + seguridad (tools dedicadas) |
| Extensibilidad | Contrato `Tool` + auto-discovery | Proyecto público: drop-in, sin tocar el core |
| Modelo | Anthropic moderno (Opus 4.8 / Fable 5) | Thinking adaptativo, tool-use robusto, sub-agentes |
| Multi-provider (`llm/`) | Subordinado | Gemini-Vision, etc., pasan a ser *tools*, no el cerebro |
| Memoria | Como tool | El modelo lee/escribe en el loop (no pipeline aparte) |

---

## 3. Arquitectura

```
        ┌──────────── CHAT (reactivo) ─────────┐
        │  usuario → user.message               │
        │                                       ▼
   ┌────────────┐   inyecta turno      ┌──────────────────┐
   │  WATCHER   │ ───────────────────► │   AGENT LOOP     │  ← el cerebro
   │ (proactivo)│   "error de          │ (Anthropic       │
   │ log / FPS  │    compilación:      │  tool-use,       │
   │ / estado   │    arreglalo"        │  thinking on)    │
   └────────────┘                      └────────┬─────────┘
                                                │ tool_use
                          ┌──────────────┬──────┼───────────┬─────────────┐
                          ▼              ▼      ▼            ▼             ▼
                    run_ue_python   analyze   ui_control  git_commit  spawn_subagent …
                     (bridge 9878)  _project  (teclado/   (versionar) (fan-out)
                          │         (filesys)  mouse/OCR)
                          ▼
                    UnrealEditor (PID del editor)
```

### 3.1 Componentes y fronteras

| Pieza | Rol | Origen |
|---|---|---|
| **`vera_server`** (TCP 9880) | Transporte fino: recibe comando, emite eventos a la UI. **Pierde su ruteo por keyword.** | Existe → se adelgaza |
| **`AgentLoop`** | El cerebro. Corre el bucle tool-use de Anthropic. Absorbe el `if/elif` del Manager **y** el GOAP. | **Nuevo** |
| **`ToolRegistry`** | Auto-descubre tools de `vera/tools/`, construye el `tools[]` del modelo. | **Nuevo** |
| **`Tool` (contrato)** | Interfaz común de toda herramienta. | **Nuevo** |
| **`UEBridgeClient`** | Cliente del bridge 9878 (ejecuta Python en el editor, main-thread safe). | Existe (`tools/ue_conn.py`) |
| **`EventEmitter`** | Mapea eventos del loop (thinking/tool_use/tool_result) → timeline de la UI. | Existe (`blackboard.report_progress` + socket) |
| **`Watcher`(s)** | Proactivo: leen log/estado de UE, inyectan *goals* al loop. | **Nuevo** (reemplaza `goap_engine`) |
| **`Config`** | Settings + toggles de autopilot (`enable_autofixer`, `enable_qa_bot`…). Consolida `config.py` + `_load_env`. | Consolidar |
| **`llm/`** | Subordinado. El cerebro usa el cliente Anthropic directo; otros providers quedan como tools. | Existe → se subordina |

### 3.2 El contrato `Tool`

```python
# vera/tools/base.py
class Tool(Protocol):
    name: str                      # "analyze_project"
    description: str               # qué hace + CUÁNDO usarla (el modelo lo lee)
    input_schema: dict             # JSON Schema de los args
    destructive: bool = False      # ¿requiere confirmación? (irreversible)

    def execute(self, args: dict, ctx: "ToolContext") -> "ToolResult": ...
```

`ToolContext` expone a la tool: el `UEBridgeClient` (ejecutar en UE), el `EventEmitter` (reportar progreso), y el cliente LLM (para sub-llamadas / sub-agentes).

**Auto-discovery:** el `ToolRegistry` escanea `vera/tools/`, instancia todo lo que cumple `Tool`, y arma el array de herramientas para Anthropic. Un contribuidor dropea `mi_tool.py` y aparece — cero edición del core.

### 3.3 Capas de tools

- **Capa 0 — `run_ue_python`** (bash-core): ejecuta código `unreal` arbitrario vía bridge. Lo abierto, lo que aún no tiene tool dedicada. El modelo escribe el código.
- **Capa 1 — tools dedicadas** (un archivo c/u, auto-descubiertas): `analyze_project`, `analyze_performance` (ex `analyzer_agent`), `ui_control` (teclado/mouse/OCR — ex `hotkey_agent`+`perception`), `pie_qa`, `create_blueprint`, `git_commit`, `art_critic`, `log_qa`, `screenshot`, `cloud_recipes` (descarga de comunidad), `fab_install` (futuro).
- **Capa 2 — `spawn_subagent`**: fan-out para auditar N subsistemas en paralelo (sub-agentes asíncronos).
- **Memoria** como tool: `remember` / `recall` sobre `SemanticMemory` (VectorDB + embeddings).

---

## 4. Flujo de una orden (punta a punta)

Comando: *"optimizá la iluminación del nivel"*

```
chat → vera_server(9880) → AgentLoop.run("optimizá la iluminación")
  ├─ [thinking]   modelo planifica            → UI: 💭
  ├─ tool_use     analyze_performance()        → UI: 🔍 (12 luces dinámicas costosas)
  ├─ [thinking]   decide pasar 8 a estáticas
  ├─ tool_use     run_ue_python(<código>)      → bridge 9878 → editor (8 convertidas)
  ├─ tool_use     screenshot()                 → UI: imagen del viewport
  └─ final        "Listo: 8 luces a estáticas, ~18ms GPU menos"
```

Cada `thinking`/`tool_use`/`tool_result` mapea 1:1 al **timeline de la UI** ya existente. El requisito de "ver progreso en vivo" queda nativo.

---

## 5. Reactivo + proactivo unificados

El `Watcher` reemplaza el utility-scoring artesanal del GOAP. En vez de puntuar goals con multiplicadores hardcodeados, **detecta un hecho e inyecta un turno**; el modelo decide:

```python
# LogWatcher detecta texto rojo en el Output Log de UE
loop.inject(role="user", content=
    "Apareció un error de compilación:\n<stack trace>\n"
    "Diagnosticalo y arreglalo si es seguro.")
```

El mismo `AgentLoop` que atiende el chat atiende esto. Watchers del MVP: `LogWatcher` (errores → auto-fix, el GER loop), `FPSWatcher` (caída de frames → optimización). Los toggles de `Config` (`enable_autofixer`, etc.) prenden/apagan cada watcher.

---

## 6. Seguridad: la guarda de tools destructivas

La guarda vive en **un solo lugar**: antes de ejecutar cualquier tool con `destructive=True`, el `AgentLoop` pide confirmación, surfaceada a la UI como pregunta (se reusa el flujo del `DecisionAgent`). Aplica a *toda* tool marcada así, incluidas las de terceros.

**Decisión (resuelta):** `run_ue_python` arranca marcada **destructiva por defecto** (pide OK siempre); el clasificador liviano que detecta patrones peligrosos (`destroy_actor`, `delete_asset`) entra en Fase 4.

---

## 7. Plan de migración (cada fase entrega software que anda)

| Fase | Qué | Resultado |
|---|---|---|
| **0 — Limpieza** | Borrar duplicados muertos (✅ hecho: 2). Re-homear capacidades dormidas como tools. Matar ruteo duplicado de `vera_server`. | Base limpia |
| **1 — Núcleo** | `AgentLoop` + `ToolRegistry` + contrato `Tool` + `run_ue_python`. `vera_server` apunta al loop (Manager viejo de fallback). | Cerebro agéntico mínimo vivo |
| **2 — Paridad** | Envolver agentes existentes como tools, **uno por uno**; borrar su rama del `if/elif`. Retirar `manager_agent`/`goap_engine`. | Paridad con hoy, sin router |
| **3 — Proactivo** | `LogWatcher` + `FPSWatcher` inyectan goals. Toggles en `Config`. | Autonomía real (junior-dev) |
| **4 — AAA** | Sub-agentes (fan-out), memoria-como-tool, clasificador de seguridad, Fab install. | El "del mañana" |

---

## 8. Estado de la limpieza (Fase 0)

- 🔴 **Borrados (duplicados muertos confirmados):** `tools/gemini_vision_art_critic.py` (stub, lo reemplaza `art_critic_agent`), `cache/action_cache.py` (lo reemplaza `SemanticMemory`).
- 🔴 **Pendiente de borrar:** `recipes/cloud_sync.py` (mock del real `tools/cloud_sync`) — bloqueado por guard de seguridad; se elimina en la consolidación.
- 🟡 **Capacidades dormidas (KEEP, re-homear como tools):** `analyzer_agent` (perf global), `actions/{keyboard,mouse}` + `perception/*` + `hotkey_agent` (→ `ui_control`), `recipes/{auto_linter,lighting_wizard,level_blockout,chaos_crew}`, `config.py` (toggles).
- ⚫ **Se retira en migración (no borrado-ahora):** `manager_agent` `if/elif`, `goap_engine`, ruteo keyword duplicado en `vera_server`.

**Hallazgo clave:** el desorden de VERA **no es código muerto** (solo 2-3 archivos lo eran) — es **ruteo duplicado y cableado ad-hoc**. La "limpieza de verdad" es la refactorización estructural, no borrar archivos.

---

## 9. Testing

- **Por tool, aislada:** el contrato (`execute(args, ctx)`) hace trivial testear cada herramienta con un `ctx` mockeado.
- **El loop:** con un cliente LLM mockeado que emite `tool_use` predeterminados → verifica dispatch, encadenado, y guarda destructiva.
- **End-to-end:** `test_vera_direct.py` contra el `vera_server` vivo dentro de UE (ya funciona).
- **Hot-reload:** el módulo se recarga vía bridge 9878 sin reiniciar UE (validado en esta sesión).

---

## 10. Decisiones resueltas (aprobadas 2026-06-11)

1. **`run_ue_python` destructiva por defecto** (pide OK siempre); clasificador liviano en Fase 4.
2. **Una tool por capacidad** (`run_ue_python`, `ui_control`) al inicio; sub-dividir solo si el modelo se confunde.
3. **Config consolidada:** `config.py` (JSON + toggles) absorbe a `_load_env` (.env + API keys) en un único sistema.
4. **`Watcher` (proactivo) → Fase 3**, sobre un reactivo ya sólido.
