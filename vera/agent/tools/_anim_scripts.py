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
