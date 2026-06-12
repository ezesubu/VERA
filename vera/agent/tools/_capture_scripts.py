# vera/agent/tools/_capture_scripts.py
"""Builders de scripts curados para capture_actor (percepción visual).

Internals "estilo C": setup / frame / restore separados, orquestados por la
tool con restore garantizado. El estado de la sesión vive en
sys.modules["vera_capture_state"] DEL EDITOR, así el restore es idempotente
(pop) y no depende del proceso cliente. Mismas reglas que _anim_scripts:
inyección por tokens __X__ con json.dumps/repr y JSON compacto de una línea.
"""
from __future__ import annotations

import json

from vera.agent.tools._anim_scripts import _COMMON

_SETUP_TEMPLATE = _COMMON + '''
import sys, types, math
label = __LABEL__
anim_req = __ANIM__

actor, actors = _find_actor(label)
if actor is None:
    print(json.dumps({"error": "not_found", "actor": label,
                      "candidates": _candidates(actors, label)}, sort_keys=True))
else:
    info, comp = _diagnose(actor)
    anim_name = _pick_name(info, anim_req) if anim_req is not None else None
    if anim_req is not None and info["kind"] != "skeletal":
        print(json.dumps({"error": "not_skeletal", "kind": info["kind"],
                          "hint": "usar mode=orbit"}, sort_keys=True))
    elif anim_req is not None and anim_name is None:
        print(json.dumps({"error": "no_anims", "requested": anim_req,
                          "skeleton": info["skeleton"],
                          "compatible_anims": info["compatible_anims"][:40]},
                         sort_keys=True))
    else:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        cam_loc, cam_rot = ues.get_level_viewport_camera_info()
        st = types.ModuleType("vera_capture_state")
        st.hidden = []
        # copias eagerly: si UE devolviera referencias vivas, mover la camara
        # durante la captura corromperia el restore
        st.cam = (unreal.Vector(cam_loc.x, cam_loc.y, cam_loc.z),
                  unreal.Rotator(roll=cam_rot.roll, pitch=cam_rot.pitch,
                                 yaw=cam_rot.yaw))
        st.comp = comp
        st.prev_anim_mode = None
        # ocultar SOLO lo visible: lo que el usuario ya tenia oculto no es nuestro
        for a in actors:
            if a is actor:
                continue
            try:
                if not a.is_temporarily_hidden_in_editor():
                    a.set_is_temporarily_hidden_in_editor(True)
                    st.hidden.append(a)
            except Exception:
                pass
        world = ues.get_editor_world()
        unreal.SystemLibrary.execute_console_command(world, "viewmode unlit")

        out = {"actor": info["actor"], "hidden_actors": len(st.hidden),
               "screenshot_dir": unreal.Paths.screen_shot_dir(),
               "animation": None, "anim_length": None}

        if anim_name is not None:
            st.prev_anim_mode = comp.get_editor_property("animation_mode")
            picked = {}
            _pick_and_play(comp, info, anim_name, True, picked)
            out["animation"] = picked.get("animation")
            anim = unreal.load_asset(info["anim_paths"][anim_name])
            out["anim_length"] = float(anim.get_play_length())

        origin, extent = actor.get_actor_bounds(False)
        radius = max(extent.x, extent.y, extent.z, 50.0)
        st.origin = (origin.x, origin.y, origin.z)
        st.dist = max(2.5 * radius, 200.0)
        st.cam_z = origin.z + 0.4 * radius
        rad = math.radians(45.0)
        cam = unreal.Vector(origin.x + math.cos(rad) * st.dist,
                            origin.y + math.sin(rad) * st.dist, st.cam_z)
        look = unreal.MathLibrary.find_look_at_rotation(cam, origin)
        ues.set_level_viewport_camera_info(cam, look)
        sys.modules["vera_capture_state"] = st
        print(json.dumps(out, sort_keys=True))
'''

_FRAME_TEMPLATE = '''
import unreal, json, sys, math
mode = __MODE__
value = __VALUE__
filename = __FILENAME__

st = sys.modules.get("vera_capture_state")
if st is None:
    print(json.dumps({"error": "no_state"}, sort_keys=True))
else:
    if mode == "orbit":
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        rad = math.radians(value)
        cam = unreal.Vector(st.origin[0] + math.cos(rad) * st.dist,
                            st.origin[1] + math.sin(rad) * st.dist, st.cam_z)
        target = unreal.Vector(st.origin[0], st.origin[1], st.origin[2])
        look = unreal.MathLibrary.find_look_at_rotation(cam, target)
        ues.set_level_viewport_camera_info(cam, look)
    else:
        inst = st.comp.get_anim_instance()
        if inst is not None:
            inst.set_position(value, False)
    unreal.AutomationLibrary.take_high_res_screenshot(640, 360, filename)
    print(json.dumps({"ok": True, "mode": mode, "value": value}, sort_keys=True))
'''

_RESTORE_TEMPLATE = '''
import unreal, json, sys
st = sys.modules.pop("vera_capture_state", None)
if st is None:
    print(json.dumps({"restored": False, "reason": "no_state"}, sort_keys=True))
else:
    errors = []
    for a in getattr(st, "hidden", []):
        try:
            a.set_is_temporarily_hidden_in_editor(False)
        except Exception as e:
            errors.append(str(e))
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        unreal.SystemLibrary.execute_console_command(
            ues.get_editor_world(), "viewmode lit")
        cam_loc, cam_rot = st.cam
        ues.set_level_viewport_camera_info(cam_loc, cam_rot)
    except Exception as e:
        errors.append(str(e))
    try:
        if st.prev_anim_mode is not None and st.comp is not None:
            st.comp.stop()
            st.comp.set_animation_mode(st.prev_anim_mode)
    except Exception as e:
        errors.append(str(e))
    print(json.dumps({"restored": not errors,
                      "unhidden": len(getattr(st, "hidden", [])),
                      "errors": errors[:5]}, sort_keys=True))
'''


def build_setup_script(actor_name: str, animation) -> str:
    """`animation=None` => mode orbit (no toca la animación del actor)."""
    anim_literal = json.dumps(animation) if animation is not None else "None"
    return (_SETUP_TEMPLATE
            .replace("__LABEL__", json.dumps(actor_name))
            .replace("__ANIM__", anim_literal))


def build_frame_script(mode: str, value: float, filename: str) -> str:
    return (_FRAME_TEMPLATE
            .replace("__MODE__", json.dumps(mode))
            .replace("__VALUE__", repr(float(value)))
            .replace("__FILENAME__", json.dumps(filename)))


def build_restore_script() -> str:
    return _RESTORE_TEMPLATE
