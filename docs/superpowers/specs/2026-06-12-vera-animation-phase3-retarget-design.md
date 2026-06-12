# VERA — Fase 3 de Animaciones: retargeting ("anima este ratón")

**Fecha:** 2026-06-12
**Estado:** aprobado por Ezequiel (diseño validado por secciones)
**Contexto:** fases 1 (animar: `animate_actor`) y 2 (ver: `capture_actor`) completas
y validadas en vivo. Esta fase cierra el loop para esqueletos extranjeros: cuando
un actor skeletal no tiene AnimSequences compatibles, VERA retargetea las de
Manny (o de cualquier fuente) vía IK Retargeter — incluyendo la **auto-creación**
de IK Rigs y Retargeters cuando no existen.

## Decisiones acordadas

- **Pilar:** retargeting (Sequencer y Control Rig quedan como fases futuras).
- **Alcance:** auto-crear IK Rig + Retargeter cuando no existen (no solo usar
  los existentes). Red de seguridad: cada etapa falla honesto.
- **Arquitectura: tools separadas (enfoque B, elegido por Ezequiel).** Racional
  principal (de Ezequiel): **separación de concerns como producto** — cada tool
  es un bloque consumible por sí solo; quien mañana necesite solo una etapa
  (crear IK rigs en lote, batch-retargetear un pack) ya tiene su agente sin
  cargar el pipeline entero. Además: los productos intermedios son **assets
  durables y reutilizables** (un IK Rig sirve para todos los retargets futuros
  de ese esqueleto) — no hay problema de restore, y gates separados dan
  visibilidad por asset creado. La composición es inteligencia del cerebro:
  `inspect` → `ensure_ik_rig` → `ensure_retargeter` → `retarget_animations` →
  `capture_actor` para juzgar el resultado.

## Recursos del proyecto (verificados vía AssetRegistry en vivo)

- IK Rigs existentes: `IK_Mannequin` (UE5), `IK_UE4_Mannequin` (Tokyo pack).
- IK Retargeters existentes: `RTG_Mannequin`, `RTG_UE4Manny_UE5Manny`,
  `RTG_UE5Manny_UE4Manny`.
- Esqueleto extranjero para el E2E feliz: Mannequin UE4 de
  `/Game/TokyoStylizedEnvironment/DemoContent/Characters/Mannequin_UE4/`
  (skeleton distinto del UE5).
- Casos negativos reales: `SK_SteampunkCar02`, `SK_Gyroscope_Mesh01` (esqueletos
  no humanoides — auto-characterize debe fallar honesto), `SK_ChestAM`.

## Componentes y contratos

Las tres tools viven en `vera/agent/tools/`, comparten builders en
`_retarget_scripts.py` (reusa `_COMMON` de `_anim_scripts.py`; inyección por
tokens; JSON compacto de una línea). Todas `destructive = True` (crean assets).
Todas son **find-first e idempotentes**: si el asset que producirían ya existe,
lo devuelven con `created: false` sin duplicar.

### `ensure_ik_rig`

- Input: `{actor_name: str}` o `{skeleton_path: str}` (uno de los dos requerido;
  con actor, resuelve su esqueleto vía `_diagnose`).
- Busca un `IKRigDefinition` existente cuyo skeleton coincida; si no hay, crea
  uno (AssetTools + factory) y corre auto-characterize para generar las retarget
  chains y el FBIK.
- Output: `{rig_path, skeleton, chains: ["Spine", "LeftArm", ...],
  retarget_root, created: bool}`.
- Errores honestos: actor/skeleton no encontrado; esqueleto no characterizable
  (p.ej. un auto) → error con el conteo de huesos y la sugerencia de rig manual.

### `ensure_retargeter`

- Input: `{source: str, target: str}` — cada uno acepta label de actor, path de
  skeleton o path de IKRigDefinition (resuelve con la misma lógica find-first;
  si falta el IK Rig de alguno de los lados, error honesto que apunta a
  `ensure_ik_rig`, NO lo crea implícitamente — un gate por asset).
- Busca un `IKRetargeter` existente cuyo par source/target coincida; si no hay,
  lo crea y mapea chains con `auto_map_chains` (modo fuzzy).
- Output: `{retargeter_path, chain_mapping: [{"source": ..., "target": ...}],
  unmapped_chains: [...], created: bool}` — el mapping explícito permite al
  cerebro juzgar la calidad del mapeo ANTES de gastar el batch.
- Errores honestos: rigs faltantes; cero chains mapeadas → error (un retargeter
  sin mapping es inútil; se reporta qué chains existen de cada lado).

### `retarget_animations`

- Input: `{retargeter_path: str, animations: [nombres] | "auto",
  target_actor_name?: str, play_first?: bool}`.
  - `"auto"`: el set básico de locomoción del source (idle + walk + jog por la
    heurística de nombre de `_pick_name`, hasta 5 anims).
- Corre `IKRetargetBatchOperation` (duplica + retargetea). Las anims nuevas van
  a una carpeta junto al skeletal mesh target, con sufijo `_VERA_RTG`.
- Si `play_first` y hay `target_actor_name`: reproduce la primera anim creada en
  el actor (reusa el flujo single-node de fase 1, con el fix de
  `update_animation_in_editor`).
- Output: `{created_anims: [paths], skipped: [...], played: nombre|null}`.
- Errores honestos: retargeter no encontrado; lista de anims vacía tras resolver
  `"auto"`; batch que produce cero assets (con el error del editor).

## Flujo, errores y riesgo de API

Orden de composición esperado (lo guían las descriptions de las tools, el
cerebro decide): `inspect_actor_animability` detecta `compatible_anims: []` →
`ensure_ik_rig` (target) → `ensure_retargeter` (Manny → target) →
`retarget_animations` → `animate_actor`/`play_first` → `capture_actor` para
verificación visual.

| Caso | Comportamiento |
|---|---|
| Asset ya existe (rig/rtg) | `created: false`, se reusa — idempotencia |
| Esqueleto no characterizable | Error honesto con diagnóstico (huesos, sugerencia) |
| Chains sin mapear | En output (`unmapped_chains`); cero mapeadas = error |
| Batch produce 0 anims | Error con el detalle del editor |
| Bridge caído / property bloqueada | Mismo manejo que fases 1-2 (`tail_of_output`, errores accionables) |

**Riesgo central — la superficie Python de IKRig en 5.7**: hoy verificamos tres
veces que la doc miente (properties "cannot be edited on templates", métodos
inexistentes, `get_single_node_instance` vs `get_anim_instance`). Por eso el
plan de implementación arranca con una **Task 0 de probing en vivo**: validar
contra el editor cada llamada del pipeline (controllers de IKRig/IKRetargeter,
factories de assets, auto-characterize, `auto_map_chains`,
`IKRetargetBatchOperation`) ANTES de bakear los templates. Los hallazgos del
probing fijan los detalles de implementación y se documentan en el run log.

## Testing y verificación

- **Unit tests mockeados** por tool (patrón FakeBridge/secuencia de fases 1-2,
  ~8-10 por tool): contratos de input, find-first (`created: false`), cada rama
  de error, flags destructivos.
- **E2E vivo** (obligatorio para declarar éxito):
  1. **Feliz**: spawn del Mannequin UE4 → `inspect` confirma 0 anims compatibles
     → `ensure_ik_rig` (created o reusado) → `ensure_retargeter` → 
     `retarget_animations` con jog + `play_first` → el UE4 manny corre →
     **`capture_actor` con frames de evidencia** (el cerebro juzga el resultado).
  2. **Negativo**: `ensure_ik_rig` sobre `SK_SteampunkCar02` → error honesto.
  3. **Idempotencia**: repetir la cadena feliz → todos `created: false`, cero
     assets duplicados.

## Fuera de alcance

- Sequencer (cinemáticas) y Control Rig — pilares de fases futuras.
- Edición/limpieza manual de chains (si el auto-mapeo no alcanza, VERA reporta
  y el humano edita el RTG en el editor).
- Retarget de root motion settings finos, curvas o notifies.
