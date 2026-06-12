# VERA — Fase 2 de Animaciones: percepción visual (`capture_actor`)

**Fecha:** 2026-06-12
**Estado:** aprobado por Ezequiel (diseño validado por secciones)
**Contexto:** la fase 1 (spec `2026-06-12-vera-animation-phase1-design.md`, commits
`2f6bddb..962fa6d`) le dio al cerebro la capacidad de animar; esta fase le da los
**ojos**: capturar un actor aislado en frames determinísticos para juzgarlo
visualmente. Hoy el cerebro no tiene ninguna tool de percepción visual (el
`art_critic_agent` viejo usa pyautogui de pantalla completa y depende de keys
externas muertas). La infraestructura `image_block` del tool framework ya existe
y está testeada (`vera/agent/tool.py:19`, `tests/agent/test_loop.py:133`).

## Decisiones de diseño acordadas

- **Retorno:** imágenes directas al cerebro — `ToolResult` con content mixto
  (texto JSON + N `image_block` base64). Los PNG quedan además en disco como
  evidencia.
- **Modos:** `anim` (scrubbing temporal de una animación con
  `AnimSingleNodeInstance.set_position()` — determinístico, sin depender de
  Realtime ni foco del editor) y `orbit` (N ángulos alrededor del actor; sirve
  para statics y para revisar meshes).
- **Aislamiento:** ocultar el resto de los actores
  (`set_is_temporarily_hidden_in_editor`, reversible) + `viewmode unlit`.
  Sin spawns temporales (el entorno S.A.M completo queda descartado por YAGNI).
- **Arquitectura:** "A por fuera, C por dentro" — una sola llamada del cerebro
  con restore garantizado; internamente scripts separados setup/frame/restore.
  Razón: la inteligencia del cerebro se gasta componiendo capacidades, no
  housekeeping; un restore olvidado deja el nivel oculto/unlit (lección S.A.M:
  Restore atado al cierre, nunca a la memoria del operador).

## Componentes y contratos

### `vera/agent/tools/capture_actor.py`

- Clase `CaptureActorTool(Tool)`, `destructive = False` — todo lo que toca se
  revierte; percepción no pide permiso.
- Input:

```json
{
  "actor_name": "requerido — label del actor (match exacto o parcial)",
  "mode": "anim | orbit (default: anim si hay animation, sino orbit)",
  "animation": "auto | nombre de AnimSequence (solo mode=anim)",
  "frames": "int 1..6 (default 4)"
}
```

- Resolución fija 640×360 (~307 tokens de visión por imagen). Sin parámetro
  de resolución (YAGNI).
- Output (content mixto): un bloque de texto con JSON —

```json
{
  "actor": "VERA_Manny",
  "mode": "anim",
  "animation": "MM_Idle",
  "anim_length": 1.66,
  "times": [0.21, 0.62, 1.04, 1.45],
  "files": ["<screen_shot_dir>/vera_cap_<nonce>_0.png", "..."],
  "hidden_actors": 214,
  "restored": true
}
```

  seguido de N `image_block` (PNG base64). En `mode=orbit` la clave `times` se
  reemplaza por `angles` (grados de yaw alrededor del actor).

### `vera/agent/tools/_capture_scripts.py`

Módulo privado de builders (espejo de `_anim_scripts.py`; reusa `_COMMON` —
`_find_actor`, `_candidates`, `_diagnose` — importándolo de `_anim_scripts`).
Inyección de parámetros por tokens `__X__` con `json.dumps`/`repr`. Scripts
imprimen JSON compacto de una línea (parseado con `parse_json_output`).

- **`build_setup_script(actor_name, animation_or_none)`** — en el editor:
  1. Encuentra el actor (no encontrado → `{"error": "not_found", "candidates": [...]}`).
  2. Si se pidió anim y el actor no es skeletal → `{"error": "not_skeletal",
     "kind": "static", "hint": "usar mode=orbit"}` (sin tocar nada del nivel).
  3. Guarda el estado previo en `sys.modules["vera_capture_state"]`:
     lista de actores que ESTA sesión oculta (solo los que estaban visibles),
     cámara original del viewport (`get_level_viewport_camera_info`),
     `animation_mode` previo del componente (si aplica).
  4. Oculta todos los demás actores; `viewmode unlit` vía
     `execute_console_command`; setea la anim single-node si `mode=anim`
     (con la heurística/resolución de `_pick_and_play`, incluido
     `set_update_animation_in_editor(True)`).
  5. Encuadra la cámara por bounds: `origin, extent = actor.get_actor_bounds(False)`,
     distancia `max(2.5 * max(extent), 200)`, cámara elevada `origin.z + 0.4*max(extent)`,
     mirando al origin (`find_look_at_rotation`).
  6. Devuelve JSON: bounds, `anim_length` (de `sequence_length` del asset),
     nombre de anim elegida, conteo de ocultados y **`screenshot_dir`**
     (`unreal.Paths.screen_shot_dir()` — nada hardcodeado en el cliente).
- **`build_frame_script(mode, t_or_angle, filename)`** — UNA pose + UN screenshot:
  - `anim`: `inst.set_position(t, False)` sobre el target.
  - `orbit`: recoloca la cámara al ángulo (misma distancia/elevación del setup).
  - `take_high_res_screenshot(640, 360, filename)`. El filename lleva un nonce
    generado por el lado Python (evita leer PNG viejos de sesiones anteriores).
- **`build_restore_script()`** — **idempotente**, sin parámetros: lee
  `vera_capture_state`, des-oculta exactamente lo que esta sesión ocultó,
  restaura cámara y `viewmode lit`, restaura el `animation_mode` previo del
  actor, limpia el módulo de estado. Si no hay estado guardado responde
  `{"restored": false, "reason": "no_state"}` sin fallar.

### Por qué un screenshot por round-trip

`take_high_res_screenshot` es asíncrona (se encola al próximo frame). N capturas
encoladas en un solo script con N poses = ordering azaroso. Un frame por bridge
call (patrón verificado en vivo en el E2E de fase 1) lo hace determinístico.

## Flujo y manejo de errores

Orquestación en `CaptureActorTool.execute` (lado Python):

```
setup → try: por cada frame i: (frame_script → poll del PNG) → finally: restore
```

- El **restore viaja siempre** (finally), incluso si un frame lanzó excepción.
- Poll del PNG: espera a que el archivo exista y su tamaño quede estable
  (dos lecturas iguales), timeout 15s por frame.
- Tiempos de scrub: `t_i = (i + 0.5) / frames * anim_length` (uniformes,
  evitando los extremos exactos). Ángulos de órbita: `360 * i / frames`.

| Caso | Comportamiento |
|---|---|
| Actor no encontrado | Error con candidatos (sin tocar el nivel) |
| `mode=anim` sobre static | Error claro: "no es skeletal; usá mode=orbit" (sin tocar el nivel) |
| Skeletal sin anims compatibles (anim=auto) | Error con el skeleton reportado (sin tocar el nivel) |
| Timeout de un PNG | Corta los frames restantes y restaura; con ≥1 frame OK devuelve parciales + warning; con 0, error |
| Excepción en cualquier frame | finally → restore; el error del frame se reporta |
| Restore falla o responde mal | El JSON de salida lleva `restored: false` + detalle — nunca éxito silencioso con el nivel sucio |
| Bridge caído | `UEConnectionError`/`UETimeoutError` → error (si cayó a mitad, el restore también se intenta) |

Validación de input antes de tocar el bridge: `actor_name` no vacío,
`frames` entre 1 y 6, `mode` válido, `animation` solo con `mode=anim`.

## Testing y verificación

- **Unit tests** (`tests/agent/test_capture_scripts.py` y
  `tests/agent/test_capture_actor.py`, bridge mockeado por secuencia):
  - Builders: inyección segura, presencia de los marcadores clave
    (`set_is_temporarily_hidden_in_editor`, `viewmode unlit`,
    `take_high_res_screenshot`, `set_position`, idempotencia del restore),
    JSON de una línea.
  - Tool: orden setup→frames→restore verificado por la secuencia de scripts
    capturados; **el restore se manda aunque un frame falle**; espera de
    archivo simulada con `tmp_path`; content mixto con N image_blocks y el
    JSON de metadata; `destructive is False`; cada rama de error de la tabla.
- **E2E vivo** (obligatorio para declarar éxito):
  1. `mode=anim` sobre `VERA_Manny` con `MM_Idle`, 4 frames — el cerebro
     (Claude vía bridge) describe qué ve en los frames.
  2. `mode=orbit` sobre `Enemy_CyberHead`, 4 ángulos.
  3. Verificación de restore: mismo conteo de actores visibles que antes,
     viewmode lit, cámara restaurada, `animation_mode` del Manny restaurado.

## Fuera de alcance (fases futuras)

- Entorno S.A.M completo (luz alineada a cámara, skysphere, silueta).
- Juicio automatizado del art_critic con LLM propio (depende del server/chat
  UI diferido y de keys vivas) — en esta fase el juez es el cerebro que corre
  el loop.
- Comparación frame-a-frame automática ("¿patina?") — primero validar que el
  juicio visual simple funciona.
