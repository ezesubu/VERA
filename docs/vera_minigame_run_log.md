# VERA Gauntlet — log de iteraciones (Claude como agente)

Minigame para testear el cerebro agéntico: el agente juega en PIE (física real)
vía el bridge 9878 + `vera_autopilot.py`, debe llegar al Finish gate (0, 3600),
y en cada iteración arregla **todos** los defectos del mapa que detecte.

**Meta**: Finish gate (0, 3600), radio 300. **Política**: arreglar todo lo detectado.

## Infraestructura creada

- `UE57/Content/Python/vera_autopilot.py` — runtime tick-driven en el editor:
  cola de comandos (`walk_to`/`jump`/`wait`), `add_movement_input` con física real,
  telemetría (posición/velocidad), eventos (`fell`/`stuck`/`auto_jump`/`goal_reached`).
- `scratch/ue.py` — cliente CLI del bridge (script por stdin → JSON).

## Iteraciones

### Run 1 (sin llegar a jugar) — spawn imposible
- **Síntoma**: PIE arranca sin pawn. Log: `FindPlayerStart: NO PLAYERSTART with positive rating`.
- **D1**: PlayerStart en (0,0,302), encajonado entre el Sweeper_Arm, láseres y VERA_Cube de la arena.
- **Fix**: PlayerStart → (0, -2200, 130), sobre la plataforma de START.

### Run 1b — el pawn muere al spawnear
- **Síntoma**: pawn spawnea y desaparece en <1s, sin caminar.
- **D2**: `KillZ = 4000` — el plano de muerte estaba ARRIBA de todo el circuito (Z 0–1150).
  Todo pawn era destruido por "caerse del mundo" estando parado en el piso.
- **Fix**: KillZ → -2000 (debajo de la lava en Z≈-750).

### Run 1c — lanzado a Y=23.000 en 0,6s
- **Síntoma**: telemetría muestra al pawn a 25.000 uu del spawn en medio segundo, cayendo.
- **D3**: `Minigame_Black_Hole_Trap` (RadialForceActor) con `radius=4000`,
  `force_strength=-8.000.000`, auto-activado: succionaba desde TODO el mapa y
  revoleaba al personaje como honda. También era el verdadero culpable de que el
  auto-spawn "no funcionara" (mataba al pawn antes de poder observarlo).
- **Fix**: radius → 700, force → -150.000, impulse → 0. Queda como trampa local esquivable.
- **Verificado**: tras el fix, el auto-spawn funciona sin `restart_player`.

### Run 2 — trabado a 165 uu del spawn
- **Síntoma**: `stuck` en (0,-2035) con auto-jump fallido.
- **D4**: el minigame está construido ENCIMA del playground original del template
  ThirdPerson. Dos muros del template (`SM_Cube4` 3600×200×200 + `SM_Cube18` encima,
  Z 0–400) sellan el gate de START — los pilares del gate coinciden con el muro.
- **D6** (detectado midiendo): plataformas al Mega Coin suben +200 uu/salto;
  el personaje salta ~143+45. Escalera imposible.
- **D7**: abismo de 1750 uu entre Platform_4 (2200,0,1010) y GlassBridge_Start (y=1750).
- **D8**: el Finish gate (0,3600) no conecta con el puente de cristal (x=2200, Z=1150);
  los pilares del gate flotan sobre la lava.
- **Fixes** (los muros del template no estaban cargados en editor — World Partition:
  `get_intersecting_actor_descs` + `load_actors`):
  - Muro sur reconstruido en 4 segmentos (`Minigame_StartWall_*`, mismo material
    `MI_PrototypeGrid_Gray`) con puerta de 400 uu en x ±200.
  - 5 escalones intermedios (`Minigame_Step_S00/M01..M04`) → +100 z por salto.
  - 4 plataformas (`Minigame_Step_B1..B4`) P4 → puente de cristal (gaps 350, +40 z).
  - 5 plataformas de descenso (`Minigame_Step_F1..F5`) puente → techo del Finish gate.
  - Paneles de cristal verificados: todos `BlockAll` (no hay trampa Squid Game).

### Run 3 — trabado saliendo de la puerta
- **D9**: dos columnas del template (`SM_Cylinder2/3` en x±125, y=-1775, Z 0–400)
  tapaban exactamente el corredor de salida de la puerta nueva.
- **Fix**: movidas a x±600 (decoran sin bloquear).

### Run 4 — trabado en el anillo este
- **Síntoma**: `stuck` en (1350,-1201) contra `SM_QuarterCylinder2` (pieza que el
  inventario por bounds no había listado — lección de percepción).
- **Fix de ruta** (no de mapa): escaneo de lanes por raycast → lane x=1150 limpia
  de y -1440 a +1440.

### Run 5 — en curso
Ruta: puerta START → franja sur (x 650) → lane x=1150 → escalera al Mega Coin →
pasarela B → puente de cristal → paneles → pasarela F → techo del Finish gate.

## Expansiones post-Gauntlet (misma sesión)

- **Pasada visual** (pedido: "mucha luz, no tiene sentido"): de 58 luces locales
  (8,7M cd) a ~16 con intensidad cap 3000 y radios cap 1200; lava con material
  emisivo propio (`M_VERA_Lava`); monedas en oro emisivo (`M_VERA_Gold`);
  geometría del circuito unificada en `MI_PrototypeGrid_Gray`; el lavado verde
  era una luz VERDE PURA en el Start (ahora blanco cálido).
- **Movimiento**: 23 actores animados con RotatingMovementComponent (vía
  `SubobjectDataSubsystem`, `add_component_by_class` no está expuesto). 7 rotadores
  preexistentes estaban rotos por mobility Static. Martillos re-rigged: pivots
  giraban en yaw (invisible con brazo vertical); ahora swing en pitch con
  mango+cabeza attacheados.
- **VFX**: 9 sistemas Niagara de los packs del usuario (meteoros sobre la arena,
  blackhole real en la trampa, tormentas de fuego en la lava, portal en el Finish).
- **Enemigo `vera_enemy.py`**: CyberHead flotante con aura de fuego; persigue a
  420 uu/s, explota magma + launch_character a <240 uu. Test: 11 ataques en 20s.
- **Selva + `vera_horror.py`**: 186 plantas, altar, niebla/almas/tormenta, luces
  parpadeantes y stalker Weeping Angel (solo avanza fuera del cono de visión;
  test: congelado mirándolo, 1.800 uu en 6s sin mirar, 2 sustos).
- **Integración selva↔laberinto**: puerta oeste (muro template SM_Cube3/20
  reconstruido con gap en y -800..-400), puente de 4 tablones con antorchas sobre
  la lava (gaps 200/250/250), 6 monedas-migas y tesoro dorado sobre el altar.

## Integración selva↔laberinto — VERIFICADA JUGANDO (2026-06-12)

Ruta nueva: Start → puerta oeste → 4 tablones sobre lava (saltos) → sendero de
monedas → **tesoro en el altar** (goal, radio 350). 6 runs hasta el GOAL:

1. `fell` — el CyberHead cazaba por TODO el mapa (107 ataques); knockback a la
   lava. Fix: **leash territorial** (solo caza si el jugador está en |x|,|y|≤950;
   si no, vuelve a su puesto; ataque gateado al modo cacería).
2. `timeout` — el hold_jump lo subió ENCIMA del muro bajo (cornisa z=200, muro
   alto adelante). Fix de ruta: cruzar puertas caminando, saltar solo en tablones.
3. `stuck` — mis segmentos del muro oeste tenían las escalas AL DOBLE (dividí
   por 50 en vez de 100) y tapaban mi propia puerta. Fix: escalas 12/24.
4. `fell` — gap de 100 uu entre el borde del piso y el tablón 1: la cápsula
   (Ø70) cae en cualquier hueco mayor. Fix: tablón pegado al borde.
5. `stuck` — árbol del scatter aleatorio sobre el sendero. Fix: corrimiento de
   vegetación a >380 uu de la polilínea del camino (8 plantas movidas).
6. `queue_done` a 660 del altar (faltaba el último waypoint) → 7º run: **GOAL
   en 14,7s, 0 muertes**.

**Lava real (`vera_lava.py`)**: el plano de lava ya no es piso — sin colisión
(se fuerza por sesión PIE, el save no alcanzó), hundirse < Z=-760 = explosión de
magma + respawn en Start + contador de muertes. Verificado: 2 muertes de prueba.

## Lecciones para el cerebro de VERA (backlog)

1. **Síntomas idénticos, causas distintas**: "no hay pawn" fue 3 bugs encadenados
   (PlayerStart bloqueado → KillZ → black hole). El loop perceive→diagnose debe
   re-diagnosticar tras cada fix, no asumir que el fix anterior falló.
2. **La telemetría gana a la inspección estática**: el black hole solo se vio
   con posición muestreada en el tiempo (teleport de 25.000 uu en 0,5s).
3. **El inventario por bounds no alcanza**: QuarterCylinder2 no apareció en el
   barrido de AABB pero bloqueaba la lane. Raycasts a altura de personaje son
   la verificación de "transitabilidad" real.
4. **World Partition**: actores no cargados en el editor existen igual en PIE.
   Percepción y edición operan sobre mundos distintos — el cerebro debe saber
   en cuál está mirando (`get_intersecting_actor_descs`/`load_actors`).
5. **Leer los TextRender del nivel** ("CLIMB TO THE MEGA COIN") = intención de
   diseño gratis para el planner.
6. **Física del personaje como restricción de diseño**: salto máx ≈188 uu
   (JumpZ 700 / gravedad template). Todo gap/escalón generado debe validarse
   contra el modelo de movimiento antes de construir.

## E2E Fase 1 de Animaciones (2026-06-12)

Validación en vivo de las tools `inspect_actor_animability` y `animate_actor`
(spec `docs/superpowers/specs/2026-06-12-vera-animation-phase1-design.md`),
ejecutadas reales contra el editor vía bridge 9878 (driver `scratch/e2e_anim_phase1.py`).

| Check | Resultado | Evidencia |
|---|---|---|
| 1. inspect "CyberHead" | ✅ match parcial → `Enemy_CyberHead`, `kind: static`, 0 anims, nota honesta | output JSON |
| 2. spawn Manny corriendo | ✅ `VERA_Manny` + tag `VERA_SPAWNED` + `MF_Unarmed_Jog_Fwd` loop | `Saved/Screenshots/WindowsEditor/vera_e2e_scrub_t01.png` y `_t045.png` (dos fases de zancada distintas) |
| 3. animate "auto" | ✅ heurística eligió `MF_Pistol_Idle_ADS`; pose idle visible | `vera_e2e_check3_idle.png` |
| 4. reporte honesto + procedural | ✅ `not_animable` con opciones (no error); con `allow_procedural`: bobbing z 337.6→359.9 + yaw -44.7→46.2 en 1.5s | telemetría de location/rotation |

### Hallazgo que produjo fix de código
Los SkeletalMeshComponent **no tickean animación en el mundo del editor** sin
`set_update_animation_in_editor(True)` — descubierto en vivo, fix commiteado
(`31cd9e9`) dentro de `_pick_and_play` en `_anim_scripts.py`. La reproducción
visible en viewport además requiere Realtime activo; el scrubbing con
`AnimSingleNodeInstance.set_position()` evalúa poses correctamente sin realtime
(así se capturó la evidencia del check 2).

### Gotchas de API (UE 5.7 Python)
- `comp.get_single_node_instance()` no existe → `comp.get_anim_instance()` devuelve el `AnimSingleNodeInstance`.
- `AnimSingleNodeInstance.get_current_time()` no existe; `set_position(t, fire_notifies)` sí.
- `comp.set_editor_property("update_animation_in_editor", True)` falla ("cannot be edited on templates"); el setter `comp.set_update_animation_in_editor(True)` funciona.
- `get_socket_location()` devuelve cache viejo sin tick — verificar poses por render (screenshot), no por sockets.

### Follow-ups anotados
1. El tick procedural (`vera_proc_anim`) no tiene stop/unregister formal (en esta demo se limpió a mano restaurando la base del CyberHead; no guarda rotación base).
2. Heurística "auto" elige el primer idle alfabético (`MF_Pistol_Idle_ADS`); preferible priorizar el idle base (`MM_Idle`).
3. El spawn sin location usa la Z de la cámara → Manny flotando; convendría trace al piso.

## E2E Fase 2 — capture_actor (2026-06-12)

Validación en vivo de la tool de percepción visual (spec
`docs/superpowers/specs/2026-06-12-vera-animation-phase2-capture-design.md`).
El diseño original (viewport + HighResShot) murió en el primer check en vivo
y fue reemplazado por **SceneCapture2D + RenderTarget + show-only list** —
los unit tests (105) jamás lo hubieran detectado.

| Check | Resultado | Evidencia |
|---|---|---|
| 1. anim: Manny + MF_Unarmed_Jog_Fwd, 4 frames | ✅ 4 fases de zancada DISTINTAS, aislado contra cielo | `vera_cap_5c607b7e_*.png` |
| 2. orbit: Enemy_CyberHead, 4 ángulos | ✅ perfil/trasera/perfil opuesto, materiales visibles | `vera_cap_9f69c7b7_*.png` |
| 3. restore | ✅ 556/556 visibles (baseline exacto), 0 rigs huérfanos, anim mode restaurado | conteo por bridge |

### Hallazgos en vivo que produjeron fixes de código

1. **`take_high_res_screenshot` nunca aterriza con el editor minimizado** (ni
   con `Slate.bAllowThrottling 0`); `EditorPerformanceSettings` no está expuesta
   en Python 5.7 → captura reescrita a SceneCapture2D (render a demanda,
   funciona minimizado, export síncrono) — commit `6ca609c`.
2. **`show_only_actors` property falla** ("cannot be edited on templates");
   el setter `show_only_actor_components(actor, True)` + `PRM_USE_SHOW_ONLY_LIST`
   funciona → aislamiento sin tocar NINGÚN actor del nivel (ni viewport, ni
   viewmode, ni cámara — el restore se reduce a destruir el rig).
3. **`SCS_BASE_COLOR` rinde blanco inútil** en este nivel → `SCS_FINAL_COLOR_LDR`.
4. **`capture_scene()` en el mismo call stack ve la pose ANTERIOR** al scrub:
   la evaluación ocurre entre ticks → pose y captura en round-trips separados
   (`a2fed70`) + espera de settle 0.25s (`ed26fd8`).
5. **Restricción documentada**: `mode=anim` requiere la ventana del editor
   visible (no minimizada; foco NO hace falta — tickea a 60fps restaurada);
   `mode=orbit` funciona incluso minimizado (transforms son inmediatos).
   Scrub 100% headless (AnimPose CPU-side) queda como follow-up.
6. Mi propio probe manual crasheado dejó un SceneCapture2D huérfano en el
   nivel — exactamente la clase de fuga que el restore-en-finally de la tool
   previene (la tool nunca dejó huérfanos en ninguna corrida).
