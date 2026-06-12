# VERA Fase 1 de Animaciones — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dos tools nuevas del cerebro agéntico — `inspect_actor_animability` (percepción read-only) y `animate_actor` (destructiva: animar existentes / spawnear Manny animado) — según el spec `docs/superpowers/specs/2026-06-12-vera-animation-phase1-design.md`.

**Architecture:** Patrón de scripts curados de `inspect_level.py`: cada tool construye un script Python (lado editor) con parámetros inyectados de forma segura, lo manda por el bridge 9878 con `send_json`, y parsea una línea JSON de respuesta. Los fragmentos de script compartidos (buscar actor, diagnosticar animabilidad, elegir+reproducir anim) viven en un módulo privado `_anim_scripts.py`. El `ToolRegistry` auto-descubre las subclases de `Tool` — no hay que registrar nada.

**Tech Stack:** Python 3 (repo `E:\PCW\VERA`), pytest (+monkeypatch), Unreal Engine 5.7 Python API (`unreal.EditorActorSubsystem`, `AssetRegistryHelpers`, `SkeletalMeshComponent.play_animation`, `register_slate_post_tick_callback`).

**Convenciones del repo que importan:**
- Tests corren desde la raíz del repo: `cd E:\PCW\VERA` y `python -m pytest ...`.
- Las tools importan `send_json` a su namespace (`from vera.tools.ue_conn import send_json, ...`) para que los tests lo mockeen con `monkeypatch.setattr(mod, "send_json", ...)`.
- Los scripts curados imprimen **JSON compacto en una sola línea** (nunca `indent=`) porque el output del editor puede traer ruido de log y se parsea la última línea que empieza con `{`.
- `ToolResult(content, is_error)`: `is_error=True` solo para fallos del sistema o pedidos imposibles. `strategy_used: "not_animable"` es un **resultado válido** (reporte honesto), NO un error.

---

### Task 1: Módulo de builders de scripts `_anim_scripts.py`

**Files:**
- Create: `vera/agent/tools/_anim_scripts.py`
- Test: `tests/agent/test_anim_scripts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent/test_anim_scripts.py
from vera.agent.tools._anim_scripts import (
    build_inspect_script,
    build_animate_script,
    build_spawn_script,
    parse_json_output,
)


def test_inspect_script_inyecta_label_seguro():
    s = build_inspect_script('Cyber "Head" 2')
    assert '"Cyber \\"Head\\" 2"' in s     # json.dumps escapa las comillas
    assert "__LABEL__" not in s
    assert "_find_actor" in s and "_diagnose" in s
    assert "indent" not in s               # JSON compacto, una línea


def test_animate_script_inyecta_parametros():
    s = build_animate_script("Bot", "MM_Idle", False, True)
    assert '"Bot"' in s and '"MM_Idle"' in s
    assert "looping = False" in s
    assert "allow_procedural = True" in s
    for token in ("__LABEL__", "__ANIM__", "__LOOPING__", "__ALLOW_PROC__"):
        assert token not in s


def test_spawn_script_con_location():
    s = build_spawn_script("auto", True, [100.0, 200.0, 90.0])
    assert "location = [100.0, 200.0, 90.0]" in s
    assert "SKM_Manny_Simple" in s
    assert "VERA_SPAWNED" in s
    assert "__LOCATION__" not in s


def test_spawn_script_sin_location():
    s = build_spawn_script("auto", True, None)
    assert "location = None" in s
    assert "get_level_viewport_camera_info" in s


def test_parse_json_output_tolera_ruido_de_log():
    out = 'LogPython: ruido\nLogTemp: mas ruido\n{"a": 1}'
    assert parse_json_output(out) == {"a": 1}


def test_parse_json_output_invalido_devuelve_none():
    assert parse_json_output("sin json") is None
    assert parse_json_output("") is None
    assert parse_json_output(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/agent/test_anim_scripts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.agent.tools._anim_scripts'`

- [ ] **Step 3: Write the implementation**

```python
# vera/agent/tools/_anim_scripts.py
"""Builders de scripts curados (lado editor) para las tools de animación.

No es una Tool: construye los scripts Python que corren en el main thread del
editor vía el bridge. Los parámetros se inyectan con json.dumps/repr sobre
tokens __X__ — nunca interpolación cruda (labels con comillas no rompen nada).
Los scripts imprimen JSON compacto en UNA línea; parse_json_output() lo
recupera tolerando ruido de log.
"""
from __future__ import annotations

import json

# --- Fragmento común: localizar actor + diagnóstico + elegir/reproducir -----
_COMMON = '''
import unreal, json

def _find_actor(label):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = list(eas.get_all_level_actors())
    low = label.lower()
    for a in actors:
        if a.get_actor_label().lower() == low:
            return a, actors
    partial = [a for a in actors if low in a.get_actor_label().lower()]
    return (partial[0] if partial else None), actors

def _candidates(actors, label, n=5):
    low = label.lower()
    labels = [a.get_actor_label() for a in actors]
    labels.sort(key=lambda s: (low[:3] not in s.lower(), s))
    return labels[:n]

def _diagnose(actor):
    info = {"actor": actor.get_actor_label(), "kind": "none", "skeleton": None,
            "compatible_anims": [], "anim_paths": {}, "current_anim_mode": None,
            "notes": ""}
    skel_comps = list(actor.get_components_by_class(unreal.SkeletalMeshComponent))
    static_comps = list(actor.get_components_by_class(unreal.StaticMeshComponent))
    comp = None
    if skel_comps:
        comp = skel_comps[0]
        info["kind"] = "skeletal"
        info["current_anim_mode"] = str(comp.get_editor_property("animation_mode"))
        mesh = comp.get_skeletal_mesh_asset()
        if mesh is None:
            info["notes"] = "SkeletalMeshComponent sin mesh asignado"
        else:
            skel = mesh.get_editor_property("skeleton")
            if skel is not None:
                info["skeleton"] = skel.get_name()
                skel_path = skel.get_path_name()
                ar = unreal.AssetRegistryHelpers.get_asset_registry()
                flt = unreal.ARFilter(
                    class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "AnimSequence")],
                    package_paths=["/Game"], recursive_paths=True)
                for ad in ar.get_assets(flt):
                    tag = ad.get_tag_value("Skeleton")
                    if tag and skel_path in str(tag):
                        name = str(ad.asset_name)
                        info["compatible_anims"].append(name)
                        info["anim_paths"][name] = str(ad.package_name)
                info["compatible_anims"].sort()
    elif static_comps:
        info["kind"] = "static"
        info["notes"] = "static mesh: sin esqueleto, no admite AnimSequence"
    return info, comp

def _pick_and_play(comp, info, anim_req, looping, out):
    name = anim_req
    if anim_req == "auto":
        names = info["compatible_anims"]
        name = next((n for n in names if "idle" in n.lower()),
                    next((n for n in names if "walk" in n.lower()),
                         names[0] if names else None))
    path = info["anim_paths"].get(name) if name else None
    if path is None:
        out["error"] = "anim_not_compatible"
        out["requested"] = anim_req
        out["compatible_anims"] = info["compatible_anims"][:40]
        return False
    anim = unreal.load_asset(path)
    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    comp.play_animation(anim, looping)
    out["animation"] = name
    out["looping"] = looping
    return True
'''

_INSPECT_TEMPLATE = _COMMON + '''
label = __LABEL__
actor, actors = _find_actor(label)
if actor is None:
    print(json.dumps({"error": "not_found", "actor": label,
                      "candidates": _candidates(actors, label)}, sort_keys=True))
else:
    info, _comp = _diagnose(actor)
    info.pop("anim_paths", None)
    total = len(info["compatible_anims"])
    info["compatible_anims"] = info["compatible_anims"][:40]
    info["total_compatible_anims"] = total
    print(json.dumps(info, sort_keys=True))
'''

_ANIMATE_TEMPLATE = _COMMON + '''
import sys, types, math
label = __LABEL__
anim_req = __ANIM__
looping = __LOOPING__
allow_procedural = __ALLOW_PROC__

actor, actors = _find_actor(label)
if actor is None:
    print(json.dumps({"error": "not_found", "actor": label,
                      "candidates": _candidates(actors, label)}, sort_keys=True))
else:
    info, comp = _diagnose(actor)
    out = {"actor": info["actor"], "kind": info["kind"], "strategy_used": None}
    if info["kind"] == "skeletal" and info["compatible_anims"]:
        if _pick_and_play(comp, info, anim_req, looping, out):
            out["strategy_used"] = "played_animation"
    elif info["kind"] == "skeletal":
        out["strategy_used"] = "not_animable"
        out["skeleton"] = info["skeleton"]
        out["reason"] = ("skeletal sin AnimSequences compatibles en /Game para el "
                         "skeleton %s; opciones: importar un pack para ese rig o "
                         "retargeting (fase 3). %s" % (info["skeleton"], info["notes"]))
    elif info["kind"] == "static" and allow_procedural:
        mod = sys.modules.get("vera_proc_anim")
        if mod is None:
            mod = types.ModuleType("vera_proc_anim")
            mod.targets = {}
            def _tick(dt):
                for k, st in list(mod.targets.items()):
                    try:
                        st["t"] += dt
                        base = st["base"]
                        a = st["actor"]
                        z = base.z + 25.0 * math.sin(st["t"] * 2.0)
                        a.set_actor_location(unreal.Vector(base.x, base.y, z), False, False)
                        r = a.get_actor_rotation()
                        a.set_actor_rotation(
                            unreal.Rotator(roll=0.0, pitch=0.0, yaw=r.yaw + 60.0 * dt), False)
                    except Exception:
                        mod.targets.pop(k, None)
            mod.tick = _tick
            mod.handle = unreal.register_slate_post_tick_callback(mod.tick)
            sys.modules["vera_proc_anim"] = mod
        mod.targets[info["actor"]] = {"actor": actor,
                                      "base": actor.get_actor_location(), "t": 0.0}
        out["strategy_used"] = "procedural"
        out["detail"] = "rotacion + bobbing via slate post tick (modulo vera_proc_anim)"
    else:
        out["strategy_used"] = "not_animable"
        out["reason"] = ("'%s' (%s) no tiene esqueleto: no admite animacion esqueletal. "
                         "Opciones: allow_procedural=true (rotacion/bobbing) o un asset "
                         "rigged equivalente." % (info["actor"], info["kind"]))
    print(json.dumps(out, sort_keys=True))
'''

_SPAWN_TEMPLATE = _COMMON + '''
anim_req = __ANIM__
looping = __LOOPING__
location = __LOCATION__
MESH_PATH = "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple"

mesh = unreal.load_asset(MESH_PATH)
if mesh is None:
    print(json.dumps({"error": "asset_missing", "path": MESH_PATH}, sort_keys=True))
else:
    rot = unreal.Rotator()
    if location is None:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        cam_loc, cam_rot = ues.get_level_viewport_camera_info()
        fwd = unreal.MathLibrary.get_forward_vector(cam_rot)
        location = [cam_loc.x + fwd.x * 400.0, cam_loc.y + fwd.y * 400.0, cam_loc.z]
        rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=cam_rot.yaw + 180.0)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = eas.spawn_actor_from_class(
        unreal.SkeletalMeshActor,
        unreal.Vector(location[0], location[1], location[2]), rot)
    comp = actor.get_editor_property("skeletal_mesh_component")
    comp.set_skeletal_mesh_asset(mesh)
    actor.set_actor_label("VERA_Manny")
    tags = list(actor.get_editor_property("tags"))
    tags.append("VERA_SPAWNED")
    actor.set_editor_property("tags", tags)
    out = {"strategy_used": "spawned", "actor": actor.get_actor_label(),
           "kind": "skeletal", "tag": "VERA_SPAWNED",
           "location": [round(location[0], 1), round(location[1], 1),
                        round(location[2], 1)],
           "animation": None}
    info, comp = _diagnose(actor)
    _pick_and_play(comp, info, anim_req, looping, out)
    print(json.dumps(out, sort_keys=True))
'''


def build_inspect_script(actor_name: str) -> str:
    return _INSPECT_TEMPLATE.replace("__LABEL__", json.dumps(actor_name))


def build_animate_script(actor_name: str, animation: str = "auto",
                         looping: bool = True,
                         allow_procedural: bool = False) -> str:
    return (_ANIMATE_TEMPLATE
            .replace("__LABEL__", json.dumps(actor_name))
            .replace("__ANIM__", json.dumps(animation))
            .replace("__LOOPING__", repr(bool(looping)))
            .replace("__ALLOW_PROC__", repr(bool(allow_procedural))))


def build_spawn_script(animation: str = "auto", looping: bool = True,
                       location=None) -> str:
    loc_literal = repr([float(v) for v in location]) if location is not None else "None"
    return (_SPAWN_TEMPLATE
            .replace("__ANIM__", json.dumps(animation))
            .replace("__LOOPING__", repr(bool(looping)))
            .replace("__LOCATION__", loc_literal))


def parse_json_output(output):
    """Última línea JSON del output del editor (tolera ruido de log). None si no hay."""
    if not output:
        return None
    for line in reversed(str(output).strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/agent/test_anim_scripts.py -v`
Expected: 6 passed

- [ ] **Step 5: Verify the registry still discovers tools cleanly**

`_anim_scripts.py` no define subclases de `Tool`, así que `ToolRegistry.discover` lo importa sin registrar nada. Verificar que no rompe nada existente:

Run: `python -m pytest tests/agent/ -v`
Expected: todos los tests existentes + los 6 nuevos en verde

- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/_anim_scripts.py tests/agent/test_anim_scripts.py
git -C E:/PCW/VERA commit -m "feat(agent): builders de scripts curados para animacion (inyeccion segura + parse tolerante a log)"
```

---

### Task 2: Tool read-only `inspect_actor_animability`

**Files:**
- Create: `vera/agent/tools/inspect_actor_animability.py`
- Test: `tests/agent/test_inspect_actor_animability.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent/test_inspect_actor_animability.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.inspect_actor_animability import InspectActorAnimabilityTool
import vera.agent.tools.inspect_actor_animability as mod
from vera.tools.ue_conn import UEConnectionError


def test_es_read_only():
    assert InspectActorAnimabilityTool().destructive is False


def test_skeletal_con_anims(monkeypatch):
    data = {"actor": "VERA_Manny", "kind": "skeletal", "skeleton": "SK_Mannequin",
            "compatible_anims": ["MM_Idle"], "total_compatible_anims": 1,
            "current_anim_mode": "AnimationMode.ANIMATION_BLUEPRINT", "notes": ""}
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["port"] = port
        captured["script"] = payload["script"]
        return {"success": True, "output": json.dumps(data)}

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = InspectActorAnimabilityTool().execute(
        {"actor_name": "VERA_Manny"}, ToolContext(bridge_port=9878))
    assert res.is_error is False
    assert "SK_Mannequin" in res.content
    assert captured["port"] == 9878
    assert '"VERA_Manny"' in captured["script"]


def test_ruido_de_log_antes_del_json(monkeypatch):
    out = "LogTemp: warning x\n" + json.dumps(
        {"actor": "A", "kind": "static", "skeleton": None,
         "compatible_anims": [], "total_compatible_anims": 0,
         "current_anim_mode": None, "notes": "static mesh"})
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": True, "output": out})
    res = InspectActorAnimabilityTool().execute({"actor_name": "A"}, ToolContext())
    assert res.is_error is False
    assert "static" in res.content


def test_not_found_con_candidatos(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: {
        "success": True,
        "output": json.dumps({"error": "not_found", "actor": "Raton",
                              "candidates": ["Altar", "Goal"]})})
    res = InspectActorAnimabilityTool().execute({"actor_name": "Raton"}, ToolContext())
    assert res.is_error is True
    assert "Altar" in res.content and "Goal" in res.content


def test_actor_name_vacio_no_llama_al_bridge(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = InspectActorAnimabilityTool().execute({"actor_name": "   "}, ToolContext())
    assert res.is_error is True


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = InspectActorAnimabilityTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content


def test_output_no_parseable(monkeypatch):
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": True, "output": "ruido sin json"})
    res = InspectActorAnimabilityTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True


def test_error_del_editor(monkeypatch):
    monkeypatch.setattr(mod, "send_json",
                        lambda *a, **k: {"success": False, "error": "boom interno"})
    res = InspectActorAnimabilityTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "boom interno" in res.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/agent/test_inspect_actor_animability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.agent.tools.inspect_actor_animability'`

- [ ] **Step 3: Write the implementation**

```python
# vera/agent/tools/inspect_actor_animability.py
"""Percepción (read-only): ¿este actor es animable?

Devuelve si el actor es skeletal o static, qué skeleton usa y qué AnimSequences
compatibles existen en /Game (vía AssetRegistry — nada hardcodeado). Sin gate
destructivo: mirar no pide permiso.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import build_inspect_script, parse_json_output
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class InspectActorAnimabilityTool(Tool):
    name = "inspect_actor_animability"
    description = (
        "Inspecciona (read-only) si un actor del nivel es animable: devuelve si es "
        "skeletal o static, qué skeleton usa y qué AnimSequences compatibles existen "
        "en el proyecto. Usala antes de animate_actor para saber qué es posible."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {
                "type": "string",
                "description": "label del actor en el nivel (match exacto o parcial)",
            },
        },
        "required": ["actor_name"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor_name = (args.get("actor_name") or "").strip()
        if not actor_name:
            return ToolResult("falta actor_name (label del actor a inspeccionar)",
                              is_error=True)
        ctx.report("InspectAnimability", f"diagnosticando {actor_name!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_inspect_script(actor_name)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"no se pudo inspeccionar el actor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo al inspeccionar el actor",
                              is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable del editor:\n{resp.get('output')}", is_error=True)
        if data.get("error") == "not_found":
            cands = ", ".join(data.get("candidates") or []) or "(sin actores en el nivel)"
            return ToolResult(
                f"actor {actor_name!r} no encontrado; labels parecidos: {cands}",
                is_error=True)
        return ToolResult(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/agent/test_inspect_actor_animability.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/inspect_actor_animability.py tests/agent/test_inspect_actor_animability.py
git -C E:/PCW/VERA commit -m "feat(agent): tool read-only inspect_actor_animability (skeletal/static + anims compatibles)"
```

---

### Task 3: Tool destructiva `animate_actor` (animate + spawn)

**Files:**
- Create: `vera/agent/tools/animate_actor.py`
- Test: `tests/agent/test_animate_actor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent/test_animate_actor.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.animate_actor import AnimateActorTool
import vera.agent.tools.animate_actor as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert AnimateActorTool().destructive is True


def test_animate_reproduce_animacion(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"actor": "VERA_Manny", "kind": "skeletal",
                    "strategy_used": "played_animation",
                    "animation": "MM_Idle", "looping": True})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "VERA_Manny"}, ToolContext())
    assert res.is_error is False
    assert "played_animation" in res.content
    assert '"VERA_Manny"' in captured["script"]
    assert "play_animation" in captured["script"]


def test_animate_static_reporte_honesto_no_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"actor": "CyberHead", "kind": "static", "strategy_used": "not_animable",
         "reason": "sin esqueleto"}))
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "CyberHead"}, ToolContext())
    assert res.is_error is False           # reporte honesto = resultado válido
    assert "not_animable" in res.content


def test_animate_anim_incompatible_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"actor": "VERA_Manny", "kind": "skeletal", "strategy_used": None,
         "error": "anim_not_compatible", "requested": "Samba",
         "compatible_anims": ["MM_Idle"]}))
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "VERA_Manny", "animation": "Samba"},
        ToolContext())
    assert res.is_error is True
    assert "MM_Idle" in res.content


def test_animate_actor_inexistente(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "not_found", "actor": "Nada", "candidates": ["Goal", "Lava"]}))
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "Nada"}, ToolContext())
    assert res.is_error is True
    assert "Goal" in res.content


def test_animate_requiere_actor_name(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute({"action": "animate"}, ToolContext())
    assert res.is_error is True


def test_action_invalida():
    res = AnimateActorTool().execute({"action": "bailar"}, ToolContext())
    assert res.is_error is True


def test_spawn_script_y_resultado(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"strategy_used": "spawned", "actor": "VERA_Manny",
                    "kind": "skeletal", "tag": "VERA_SPAWNED",
                    "location": [100.0, 200.0, 90.0],
                    "animation": "MF_Unarmed_Jog_Fwd", "looping": True})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = AnimateActorTool().execute(
        {"action": "spawn", "animation": "MF_Unarmed_Jog_Fwd",
         "location": [100.0, 200.0, 90.0]}, ToolContext())
    assert res.is_error is False
    assert "spawned" in res.content
    assert "SKM_Manny_Simple" in captured["script"]
    assert "VERA_SPAWNED" in captured["script"]
    assert "location = [100.0, 200.0, 90.0]" in captured["script"]


def test_spawn_anim_incompatible_no_es_error_si_spawneo(monkeypatch):
    # el actor SÍ se creó: error de anim es informativo, no fallo del sistema
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"strategy_used": "spawned", "actor": "VERA_Manny", "kind": "skeletal",
         "tag": "VERA_SPAWNED", "location": [0.0, 0.0, 90.0], "animation": None,
         "error": "anim_not_compatible", "requested": "Samba",
         "compatible_anims": ["MM_Idle"]}))
    res = AnimateActorTool().execute(
        {"action": "spawn", "animation": "Samba"}, ToolContext())
    assert res.is_error is False
    assert "anim_not_compatible" in res.content


def test_spawn_location_invalida(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute(
        {"action": "spawn", "location": [1, 2]}, ToolContext())
    assert res.is_error is True


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = AnimateActorTool().execute(
        {"action": "animate", "actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/agent/test_animate_actor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.agent.tools.animate_actor'`

- [ ] **Step 3: Write the implementation**

```python
# vera/agent/tools/animate_actor.py
"""Acción (destructiva): animar un actor existente o spawnear un Manny animado.

- animate: re-diagnostica el actor dentro del script (safeguard) y elige
  estrategia: play_animation (skeletal con anims compatibles), movimiento
  procedural (static + allow_procedural=true), o reporte honesto not_animable
  (resultado válido, NO error).
- spawn: SkeletalMeshActor con SKM_Manny_Simple, taggeado VERA_SPAWNED,
  default frente a la cámara del editor.

Regla de error: is_error=True solo si el sistema falló o el pedido fue
imposible SIN efectos (data tiene "error" y NO tiene strategy_used). Si el
spawn ocurrió pero la anim pedida no era compatible, el resultado vuelve
completo con el detalle — el cerebro decide cómo seguir.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import (
    build_animate_script, build_spawn_script, parse_json_output)
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class AnimateActorTool(Tool):
    name = "animate_actor"
    description = (
        "Anima un actor del nivel (action=animate) o spawnea un personaje Manny "
        "animado (action=spawn). Skeletal: reproduce una AnimSequence compatible "
        "('auto' elige idle/walk). Static: solo movimiento procedural si "
        "allow_procedural=true; si no, explica por qué no es animable. "
        "Modifica el nivel: requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["animate", "spawn"]},
            "actor_name": {
                "type": "string",
                "description": "label del actor (requerido si action=animate)",
            },
            "animation": {
                "type": "string",
                "description": "'auto' (default) o nombre de una AnimSequence compatible",
            },
            "looping": {
                "type": "boolean",
                "description": "reproducir en loop (default true)",
            },
            "location": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "spawn: [x,y,z]; default frente a la cámara del editor",
            },
            "allow_procedural": {
                "type": "boolean",
                "description": "permitir fallback rotación/bobbing en static meshes",
            },
        },
        "required": ["action"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        action = args.get("action")
        animation = (args.get("animation") or "auto").strip() or "auto"
        looping = bool(args.get("looping", True))

        if action == "animate":
            actor_name = (args.get("actor_name") or "").strip()
            if not actor_name:
                return ToolResult("action=animate requiere actor_name", is_error=True)
            ctx.report("AnimateActor", f"animando {actor_name!r} ({animation})")
            script = build_animate_script(
                actor_name, animation, looping,
                bool(args.get("allow_procedural", False)))
        elif action == "spawn":
            location = args.get("location")
            if location is not None and (
                    not isinstance(location, (list, tuple)) or len(location) != 3):
                return ToolResult("location debe ser [x, y, z]", is_error=True)
            ctx.report("AnimateActor", f"spawneando Manny animado ({animation})")
            script = build_spawn_script(animation, looping, location)
        else:
            return ToolResult(
                f"action inválida: {action!r} (usar 'animate' o 'spawn')", is_error=True)

        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"no se pudo ejecutar en el editor: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo al animar", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable del editor:\n{resp.get('output')}", is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        if data.get("error") and not data.get("strategy_used"):
            return ToolResult(rendered, is_error=True)
        return ToolResult(rendered)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/agent/test_animate_actor.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/animate_actor.py tests/agent/test_animate_actor.py
git -C E:/PCW/VERA commit -m "feat(agent): tool destructiva animate_actor (play_animation, fallback procedural, spawn Manny taggeado)"
```

---

### Task 4: Suite completa + nota en PLAN_VERA.md

**Files:**
- Modify: `E:/PCW/VERA/PLAN_VERA.md` (agregar sección al final)

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: todos en verde (los preexistentes + ~26 nuevos). Si algo preexistente falla, verificar que ya fallaba en `main` antes de tocar nada.

- [ ] **Step 2: Add the animation roadmap note to PLAN_VERA.md**

Agregar al final de `PLAN_VERA.md`:

```markdown
## Animaciones (roadmap)

- **Fase 1 (implementada 2026-06-12):** tools `inspect_actor_animability` (read-only)
  y `animate_actor` (destructiva: animate/spawn). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase1-design.md`.
- **Fase 2 (pendiente):** percepción de animación — `isolate_and_capture` con entorno
  neutro (patrón S.A.M) para que el art_critic juzgue animaciones.
- **Fase 3 (pendiente, condicional):** Sequencer / Control Rig / retargeting, solo si
  las fases 1-2 se validan en vivo.
```

- [ ] **Step 3: Commit**

```bash
git -C E:/PCW/VERA add PLAN_VERA.md
git -C E:/PCW/VERA commit -m "docs: roadmap de animaciones en PLAN_VERA (fase 1 implementada)"
```

---

### Task 5: Demo E2E en vivo (gate de éxito — manual, con el editor abierto)

**Requisito:** UE 5.7 abierto con el bridge 9878 cargado y el nivel del Gauntlet. NO declarar éxito sin completar los 4 checks con evidencia (feedback 2026-06-11: verificar contratos antes de declarar éxito).

- [ ] **Step 1: Smoke test del bridge**

```bash
python -c "from vera.tools.ue_conn import send_json; print(send_json(9878, {'script': 'print(\"bridge-ok\")'}))"
```
Expected: `{'success': True, 'output': 'bridge-ok\n'}` (o equivalente)

- [ ] **Step 2: Check 1 — inspect sobre un static (CyberHead)**

Por el chat de VERA: pedir "¿el CyberHead es animable?". El cerebro debe usar `inspect_actor_animability` y responder `kind: static` sin disparar el gate destructivo.

- [ ] **Step 3: Check 2 — spawn de Manny corriendo**

Por el chat: "pon un Manny corriendo". Debe disparar el **gate destructivo** (aprobar), spawnear `VERA_Manny` con tag `VERA_SPAWNED`, y reproducir una anim de jog/run en loop. Evidencia: screenshot con el Manny visible en pose de carrera (recordar: el editor necesita foco para capturas).

- [ ] **Step 4: Check 3 — animate sobre el Manny spawneado**

Por el chat: "ponelo en idle". `animate_actor` con `action=animate` → `strategy_used: played_animation`, `animation` con "idle" en el nombre. Screenshot de evidencia.

- [ ] **Step 5: Check 4 — reporte honesto + procedural en el CyberHead**

Por el chat: "animá el CyberHead". Respuesta esperada: `not_animable` con las opciones (NO un error del sistema). Después: "dale, con movimiento procedural" → `strategy_used: procedural`, y el CyberHead rota/bobea en el viewport.

- [ ] **Step 6: Registrar el resultado**

Anotar los 4 checks con sus evidencias en `docs/vera_minigame_run_log.md` y commitear:

```bash
git -C E:/PCW/VERA add docs/vera_minigame_run_log.md
git -C E:/PCW/VERA commit -m "docs: evidencia E2E fase 1 de animaciones (4 checks en vivo)"
```

---

## Self-review del plan (hecho al escribirlo)

- **Cobertura del spec:** inspect (Task 2), animate+fallback+honesto (Task 3), spawn+tag (Task 3), errores accionables (tests por rama en Tasks 2-3), unit tests mockeados (Tasks 1-3), E2E vivo (Task 5). Sin huecos.
- **Sin placeholders:** todo el código está completo en cada step.
- **Consistencia de tipos:** `build_*` firmas idénticas entre Task 1 (definición) y Tasks 2-3 (uso); `parse_json_output` devuelve dict o None en ambos consumidores; claves JSON (`strategy_used`, `compatible_anims`, `anim_paths`) consistentes entre templates y tests.
