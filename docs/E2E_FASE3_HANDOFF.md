# E2E Fase 3 — Retargeting de VERA (handoff para agente externo)

Sos un agente de testing. Tu trabajo: ejecutar el E2E del pipeline de
retargeting de VERA contra el Unreal Editor 5.7 abierto, registrar evidencia,
y NO declarar éxito sin verificarla. Este documento es autocontenido.

## Entorno

- Repo: `E:\PCW\VERA` (ejecutar Python desde acá). Branch: `feature/ui-redesign` — **no cambiar de branch, no commitear código, no `git add -A`**. Solo podés commitear tu evidencia (paso final).
- El editor UE 5.7 debe estar abierto con el bridge en el puerto 9878. Smoke test:

```bash
python -c "from vera.tools.ue_conn import send_json; print(send_json(9878, {'script': 'print(1)'}))"
```

- Las tools se ejecutan directo (sin gate — el gate vive en el AgentLoop, no en la tool):

```python
import sys; sys.path.insert(0, r"E:\PCW\VERA")
from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_ik_rig import EnsureIKRigTool
from vera.agent.tools.ensure_retargeter import EnsureRetargeterTool
from vera.agent.tools.retarget_animations import RetargetAnimationsTool
from vera.agent.tools.capture_actor import CaptureActorTool
from vera.agent.tools.inspect_actor_animability import InspectActorAnimabilityTool

ctx = ToolContext(bridge_port=9878)
res = EnsureIKRigTool().execute({"actor_name": "VERA_UE4Guy"}, ctx)
print(res.is_error, res.content)
```

- `capture_actor` devuelve content como LISTA (texto JSON + image blocks base64);
  los PNG también quedan en disco (paths en el JSON) — mirá los archivos.
- REGLA DURA: las llamadas a la API de UE dentro de las tools fueron verificadas
  en vivo. Si algo falla, NO "corrijas" el código de las tools: registrá el
  fallo con el output completo y seguí con el siguiente check.

## Preparación: spawnear el actor de prueba

Spawneá un SkeletalMeshActor con el mesh del Mannequin UE4 (esqueleto
extranjero, sin anims UE5 compatibles), label `VERA_UE4Guy`, sobre el piso:

```python
from vera.tools.ue_conn import send_json
script = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
mesh = unreal.load_asset(\"/Game/TokyoStylizedEnvironment/DemoContent/Characters/Mannequin_UE4/Meshes/SK_Mannequin\")
existing = [a for a in eas.get_all_level_actors() if a.get_actor_label() == \"VERA_UE4Guy\"]
if existing:
    print(\"ya existe\")
else:
    actor = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(200.0, -2200.0, 27.0), unreal.Rotator())
    actor.get_editor_property(\"skeletal_mesh_component\").set_skeletal_mesh_asset(mesh)
    actor.set_actor_label(\"VERA_UE4Guy\")
    tags = list(actor.get_editor_property(\"tags\")); tags.append(\"VERA_SPAWNED\")
    actor.set_editor_property(\"tags\", tags)
    print(\"spawneado\")
"""
print(send_json(9878, {"script": script}))
```

Después: `InspectActorAnimabilityTool().execute({"actor_name": "VERA_UE4Guy"}, ctx)`
y anotá cuántas `compatible_anims` tiene (las del pack UE4 pueden existir — el
punto es que las de Manny UE5 NO le sirven).

## Check 1 — Pipeline feliz (en orden, anotando cada output)

1. `ensure_ik_rig {"actor_name": "VERA_UE4Guy"}`
   → esperado: `is_error=False`; probablemente encuentra `IK_UE4_Mannequin`
   existente (`"created": false`). Anotá `rig_path` y el conteo de `chains`.
2. `ensure_retargeter {"source": "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple", "target": "VERA_UE4Guy"}`
   → esperado: `is_error=False`; `chain_mapping` NO vacío. Anotá
   `retargeter_path` y si `created` fue true/false.
3. `retarget_animations {"retargeter_path": <paso 2>, "animations": ["MF_Unarmed_Jog_Fwd"], "target_actor_name": "VERA_UE4Guy", "play_first": true}`
   → esperado: `created_anims` con un path bajo `.../VERA_Retargeted/` y
   `played` no nulo.
4. `capture_actor {"actor_name": "VERA_UE4Guy", "animation": "MF_Unarmed_Jog_Fwd_VERA_RTG", "frames": 3}`
   → **la ventana del editor debe estar VISIBLE (no minimizada)** o las poses
   no varían. Esperado: 3 PNG con FASES DISTINTAS de trote y `restored: true`.
   ABRÍ los PNG y describí qué ves — si los 3 frames son idénticos, reportalo
   como fallo del check (no lo maquilles).

## Check 2 — Negativo honesto

`ensure_ik_rig {"skeleton_path": "/Game/SteamPunkEnvironment01/Meshes/SK_SteampunkCar02"}`
→ esperado: `is_error=True` con `"not_characterizable"`. Verificá que NO quedó
ningún asset `IK_VERA_*` en `/Game/SteamPunkEnvironment01/Meshes/` (el rig a
medio crear se borra). Para listar:

```python
script = "import unreal\nprint([a for a in unreal.EditorAssetLibrary.list_assets(\"/Game/SteamPunkEnvironment01/Meshes\") if \"VERA\" in a])"
```

## Check 3 — Idempotencia

Repetí los pasos 1-3 del Check 1 tal cual. Esperado: `"created": false` en rig
y retargeter, y el batch con `skipped: ["MF_Unarmed_Jog_Fwd (ya retargeteada)"]`
y `created_anims: []`. Cero assets duplicados.

## Evidencia (paso final)

Apéndice `## E2E Fase 3 — retargeting (fecha)` en
`docs/vera_minigame_run_log.md` con: tabla de los 3 checks (esperado vs
observado), los outputs JSON clave, paths de los PNG, y cualquier desvío SIN
suavizarlo. Commit SOLO de ese archivo:

```bash
git -C E:/PCW/VERA add docs/vera_minigame_run_log.md
git -C E:/PCW/VERA commit -m "docs: evidencia E2E fase 3 (retargeting, agente externo)"
```

Criterio de éxito global: los 3 checks con lo esperado Y evidencia visual real.
Si algo no dio, el reporte honesto VALE MÁS que un éxito inventado — esa es la
filosofía de todo este proyecto.
