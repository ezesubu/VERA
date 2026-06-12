# VERA — Fase 1 de Animaciones: diseño

**Fecha:** 2026-06-12
**Estado:** aprobado por Ezequiel (diseño validado por secciones)
**Contexto:** VERA hoy spawnea, mueve y diagnostica actores, pero no puede animarlos.
Los enemigos del Gauntlet (CyberHead, Jungle_Stalker) son static meshes movidos por
transform en tick. Esta fase le da al cerebro agéntico la capacidad "animá este actor" /
"pon un personaje animado", con diagnóstico del asset y reporte honesto cuando no se puede.

## Objetivo

Dos tools nuevas del cerebro agéntico (patrón de scripts curados de `inspect_level.py`,
transporte por el bridge 9878, UE 5.7):

1. **`inspect_actor_animability`** — percepción read-only (sin gate destructivo).
2. **`animate_actor`** — acción destructiva (pasa por el gate de aprobación), con
   acciones `animate` y `spawn`.

Decisiones de alcance acordadas:

- Consumidor principal: el cerebro agéntico (chat). Los scripts del Gauntlet la
  adoptan después, fuera de esta fase.
- Incluye spawneo de personajes animados (no solo animar existentes).
- Fuera de alcance: retargeting (IK Retargeter), Sequencer, Control Rig, autoría de
  animación. Si no hay anims compatibles, VERA lo informa y sugiere; no lo intenta.

## Componentes y contratos

### `vera/agent/tools/inspect_actor_animability.py`

- Clase `InspectActorAnimabilityTool(Tool)`, `destructive = False`.
- Input: `{actor_name: str}` — label del actor en el nivel (match exacto, luego parcial
  case-insensitive).
- Script curado que inspecciona los componentes del actor y consulta el AssetRegistry
  por `AnimSequence` cuyo skeleton coincida con el del mesh (sin hardcodear la lista
  de Manny).
- Output (JSON):

```json
{
  "actor": "CyberHead_2",
  "kind": "skeletal | static | none",
  "skeleton": "SK_Mannequin | null",
  "compatible_anims": ["MM_Idle", "MF_Unarmed_Walk_Fwd"],
  "current_anim_mode": "animation_blueprint | single_node | null",
  "notes": "texto libre con observaciones"
}
```

- El registry (`vera/agent/registry.py`) auto-descubre subclases de `Tool` en
  `vera/agent/tools/`; no hay que registrar nada a mano.

### `vera/agent/tools/animate_actor.py`

- Clase `AnimateActorTool(Tool)`, `destructive = True` (cubierta por el gate
  question/approve existente).
- Input:

```json
{
  "action": "animate | spawn",
  "actor_name": "requerido si action=animate",
  "animation": "auto | nombre de AnimSequence (default: auto)",
  "looping": "bool (default: true)",
  "location": "[x, y, z] opcional (spawn; default: frente a la cámara del editor)",
  "allow_procedural": "bool (default: false)"
}
```

- **`animate`**: re-diagnostica el actor dentro del script (safeguard: no confía en
  que el cerebro haya llamado a inspect antes).
  - Skeletal → `set_animation_mode(ANIMATION_SINGLE_NODE)` + `play_animation(anim, looping)`.
    Con `animation="auto"`, heurística por nombre: preferir idle, luego walk.
  - Static + `allow_procedural=true` → movimiento procedural (rotación/bobbing,
    el patrón de `vera_enemy.py`).
  - Static sin permiso → reporte honesto: no animable (sin huesos); opciones:
    procedural o conseguir versión rigged. **No es error del sistema** — es un
    resultado válido informativo.
- **`spawn`**: spawnea `SkeletalMeshActor` con
  `/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple`, aplica la animación pedida
  y taggea el actor con `VERA_SPAWNED` (habilita limpieza e isolate-by-tag estilo
  S.A.M en fases futuras).
- Output siempre JSON con `strategy_used`
  (`played_animation | procedural | not_animable | spawned`) para que el cerebro
  narre lo que hizo.

## Flujo y manejo de errores

Transporte idéntico a `inspect_level`: script curado → `send_json(ctx.bridge_port)` →
ejecución en el main thread del editor. Nunca éxito silencioso:

| Caso | Comportamiento |
|---|---|
| Actor no encontrado | Error con hasta 5 labels parecidos como candidatos |
| Sin anims compatibles | Reporta el skeleton hallado; sugiere pack/retargeting sin intentarlo |
| Bridge caído / timeout | `UEConnectionError`/`UETimeoutError` → `ToolResult(is_error=True)` como las tools existentes |
| `play_animation` falla | Propaga el error real del editor |
| Asset SKM_Manny ausente | Error explícito con la ruta buscada |

## Testing y verificación

- **Unit tests** — `tests/test_animation_tools.py`, bridge mockeado (estilo
  `test_python_agent.py`): contratos de input, parseo de outputs, cada rama de error,
  `animate_actor.destructive is True`, `inspect_actor_animability.destructive is False`.
- **E2E vivo** (obligatorio para declarar éxito; ver feedback 2026-06-11 sobre
  verificar contratos):
  1. Por chat: "pon un Manny corriendo" → spawn + run en loop + screenshot de evidencia.
  2. Por chat: "animá el CyberHead" → reporte honesto static; con permiso, procedural.
  3. `inspect_actor_animability` sobre ambos actores devuelve `kind` correcto y
     anims compatibles para el Manny.

## Fases futuras (no en este spec)

- Fase 2: percepción de animación — `isolate_and_capture` con entorno neutro
  (patrón S.A.M, tutorial Epic 2026-06-10) para que el art_critic juzgue animaciones.
- Fase 3: Sequencer / Control Rig / retargeting — solo si 1 y 2 se validan en vivo.
