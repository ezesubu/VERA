# VERA Fase 2 — `capture_actor` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tool de percepción visual `capture_actor` — aísla un actor (oculta el resto + unlit), captura N frames determinísticos (scrub de animación u órbita) y devuelve las imágenes directo al cerebro, con restore garantizado. Spec: `docs/superpowers/specs/2026-06-12-vera-animation-phase2-capture-design.md`.

**Architecture:** "A por fuera, C por dentro": una sola tool con orquestación Python (setup → N×frame → restore en `finally`), internals como scripts curados separados en `_capture_scripts.py` que reusan `_COMMON` de `_anim_scripts.py`. Un screenshot por round-trip (la API es asíncrona). Estado de sesión en `sys.modules["vera_capture_state"]` del editor para restore idempotente.

**Tech Stack:** Python 3 (repo `E:\PCW\VERA`), pytest + monkeypatch, UE 5.7 Python API. Gotchas YA VERIFICADOS EN VIVO que este plan respeta: `HitResult` sin `.location`, `set_update_animation_in_editor` setter obligatorio, `get_anim_instance()` (no `get_single_node_instance`), screenshots async que aparecen en `unreal.Paths.screen_shot_dir()`.

**Convenciones del repo:**
- Tests desde la raíz: `cd E:\PCW\VERA` y `python -m pytest ...`.
- Tools importan `send_json` a su namespace para que los tests mockeen `mod.send_json`.
- Scripts curados imprimen JSON compacto en UNA línea; `parse_json_output` parsea la última línea `{`.
- NUNCA `git add -A` (working tree con cambios ajenos): siempre paths explícitos.
- `ToolResult.content` puede ser lista de content blocks (texto + `image_block`) — el loop ya lo soporta (`tests/agent/test_loop.py:133`); el truncado `MAX_TOOL_RESULT_CHARS` solo aplica a content str, las imágenes pasan enteras.

---

### Task 1: Refactor `_pick_name` en `_anim_scripts._COMMON`

El setup de captura necesita resolver el nombre de la anim ANTES de mutar el nivel (para fallar limpio sin restore). Hoy `_pick_and_play` elige y reproduce en un solo paso. Extraer la elección a `_pick_name` (mismo comportamiento, cero cambios funcionales).

**Files:**
- Modify: `vera/agent/tools/_anim_scripts.py` (dentro del string `_COMMON`)
- Test: `tests/agent/test_anim_scripts.py`

- [ ] **Step 1: Write the failing test** — agregar al final de `tests/agent/test_anim_scripts.py`:

```python
def test_common_expone_pick_name_separado_del_play():
    # capture_actor necesita resolver la anim ANTES de mutar el nivel
    s = build_animate_script("X")
    assert "def _pick_name" in s
    assert "_pick_name(info, anim_req)" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/agent/test_anim_scripts.py -v`
Expected: FAIL — `test_common_expone_pick_name_separado_del_play` (assert "def _pick_name")

- [ ] **Step 3: Refactor** — en `vera/agent/tools/_anim_scripts.py`, dentro del string `_COMMON`, reemplazar la función `_pick_and_play` completa por:

```python
def _pick_name(info, anim_req):
    if anim_req != "auto":
        return anim_req if anim_req in info["anim_paths"] else None
    names = info["compatible_anims"]
    # nombre mas corto primero: MM_Idle le gana a MF_Pistol_Idle_ADS
    idles = sorted((n for n in names if "idle" in n.lower()), key=len)
    walks = sorted((n for n in names if "walk" in n.lower()), key=len)
    return (idles + walks + list(names))[0] if names else None

def _pick_and_play(comp, info, anim_req, looping, out):
    name = _pick_name(info, anim_req)
    path = info["anim_paths"].get(name) if name else None
    if path is None:
        out["error"] = "anim_not_compatible"
        out["requested"] = anim_req
        out["compatible_anims"] = info["compatible_anims"][:40]
        return False
    anim = unreal.load_asset(path)
    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    try:
        # en el mundo del editor los skeletal meshes no tickean animacion
        # sin este flag (verificado en vivo, UE 5.7); requiere ademas
        # viewport en Realtime y editor con foco
        comp.set_update_animation_in_editor(True)
    except Exception:
        pass
    comp.play_animation(anim, looping)
    out["animation"] = name
    out["looping"] = looping
    return True
```

NOTA: el bloque `try/except` del flag ya existe en el archivo — conservarlo tal cual. El único cambio real es extraer la elección del nombre a `_pick_name` (que ahora también valida nombres explícitos contra `anim_paths`).

- [ ] **Step 4: Run the full agent suite**

Run: `python -m pytest tests/agent/ -v`
Expected: 82 passed (81 previos + 1 nuevo). El test `test_auto_prefiere_el_idle_mas_corto` ("key=len") debe seguir verde.

- [ ] **Step 5: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/_anim_scripts.py tests/agent/test_anim_scripts.py
git -C E:/PCW/VERA commit -m "refactor(agent): extrae _pick_name de _pick_and_play (capture necesita resolver sin mutar)"
```

---

### Task 2: Builders `_capture_scripts.py`

**Files:**
- Create: `vera/agent/tools/_capture_scripts.py`
- Test: `tests/agent/test_capture_scripts.py`

- [ ] **Step 1: Write the failing tests** — crear `tests/agent/test_capture_scripts.py` con EXACTAMENTE:

```python
# tests/agent/test_capture_scripts.py
from vera.agent.tools._capture_scripts import (
    build_setup_script,
    build_frame_script,
    build_restore_script,
)


def test_setup_inyecta_label_y_anim():
    s = build_setup_script('El "Raton"', "MM_Idle")
    assert '"El \\"Raton\\""' in s
    assert '"MM_Idle"' in s
    assert "__LABEL__" not in s and "__ANIM__" not in s


def test_setup_sin_anim_para_orbit():
    s = build_setup_script("Cubo", None)
    assert "anim_req = None" in s


def test_setup_aisla_y_guarda_estado():
    s = build_setup_script("X", None)
    assert "set_is_temporarily_hidden_in_editor" in s
    assert "viewmode unlit" in s
    assert "vera_capture_state" in s
    assert "screen_shot_dir" in s
    assert "get_actor_bounds" in s
    assert "indent" not in s            # JSON compacto, una línea


def test_frame_anim_scrubea():
    s = build_frame_script("anim", 0.75, "vera_cap_ab_0.png")
    assert "set_position" in s
    assert "0.75" in s
    assert '"vera_cap_ab_0.png"' in s
    assert "take_high_res_screenshot(640, 360" in s


def test_frame_orbit_mueve_la_camara():
    s = build_frame_script("orbit", 180.0, "f.png")
    assert "find_look_at_rotation" in s
    assert "180.0" in s
    assert "set_position" in s          # mismo template, rama por modo


def test_restore_idempotente_y_sin_tokens():
    s = build_restore_script()
    assert "sys.modules.pop" in s        # consumir el estado = idempotente
    assert "viewmode lit" in s
    assert "set_is_temporarily_hidden_in_editor" in s
    assert "__" not in s                 # sin tokens pendientes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/agent/test_capture_scripts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.agent.tools._capture_scripts'`

- [ ] **Step 3: Write the implementation** — crear `vera/agent/tools/_capture_scripts.py` con EXACTAMENTE:

```python
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
        st.cam = (cam_loc, cam_rot)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/agent/test_capture_scripts.py -v`
Expected: 6 passed

- [ ] **Step 5: Run the whole agent suite** (el registry importa el módulo nuevo; sin Tool subclass no registra nada)

Run: `python -m pytest tests/agent/ -v`
Expected: 88 passed

- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/_capture_scripts.py tests/agent/test_capture_scripts.py
git -C E:/PCW/VERA commit -m "feat(agent): builders setup/frame/restore para captura aislada (estado en el editor, restore idempotente)"
```

---

### Task 3: Tool `capture_actor`

**Files:**
- Create: `vera/agent/tools/capture_actor.py`
- Test: `tests/agent/test_capture_actor.py`

- [ ] **Step 1: Write the failing tests** — crear `tests/agent/test_capture_actor.py` con EXACTAMENTE:

```python
# tests/agent/test_capture_actor.py
import json
import re

from vera.agent.tool import ToolContext
from vera.agent.tools.capture_actor import CaptureActorTool
import vera.agent.tools.capture_actor as mod
from vera.tools.ue_conn import UEConnectionError


def _setup_payload(tmp_path, **over):
    d = {"actor": "VERA_Manny", "hidden_actors": 3,
         "screenshot_dir": str(tmp_path), "animation": "MM_Idle",
         "anim_length": 2.0}
    d.update(over)
    return d


class FakeBridge:
    """Simula el editor: discrimina setup/frame/restore por marcadores del
    script, escribe el PNG cuando ve un frame y registra el orden."""

    def __init__(self, tmp_path, setup=None, frame_fail_at=None,
                 write_files=True, restore=None):
        self.tmp = tmp_path
        self.setup = setup if setup is not None else _setup_payload(tmp_path)
        self.frame_fail_at = frame_fail_at
        self.write_files = write_files
        self.restore = restore or {"restored": True, "unhidden": 3, "errors": []}
        self.scripts = []
        self.frame_count = 0

    def __call__(self, port, payload, *a, **k):
        s = payload["script"]
        self.scripts.append(s)
        if "sys.modules.pop" in s:                      # restore
            return {"success": True, "output": json.dumps(self.restore)}
        if "take_high_res_screenshot" in s:             # frame
            self.frame_count += 1
            if self.frame_fail_at == self.frame_count:
                return {"success": False, "error": "boom en el frame"}
            m = re.search(r"vera_cap_[0-9a-f]+_\d+\.png", s)
            if self.write_files and m:
                (self.tmp / m.group(0)).write_bytes(b"PNGDATA")
            return {"success": True, "output": json.dumps({"ok": True})}
        return {"success": True, "output": json.dumps(self.setup)}   # setup

    @property
    def kinds(self):
        out = []
        for s in self.scripts:
            if "sys.modules.pop" in s:
                out.append("restore")
            elif "take_high_res_screenshot" in s:
                out.append("frame")
            else:
                out.append("setup")
        return out


def _fast(monkeypatch):
    monkeypatch.setattr(mod, "POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(mod, "FILE_TIMEOUT_S", 0.2)


def test_es_read_only():
    assert CaptureActorTool().destructive is False


def test_orbit_feliz(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "VERA_Manny", "frames": 2}, ToolContext())
    assert res.is_error is False
    assert bridge.kinds == ["setup", "frame", "frame", "restore"]
    assert isinstance(res.content, list)
    meta = json.loads(res.content[0]["text"])
    assert meta["mode"] == "orbit"
    assert meta["angles"] == [0.0, 180.0]
    assert meta["restored"] is True
    images = [b for b in res.content if b.get("type") == "image"]
    assert len(images) == 2


def test_anim_feliz_calcula_tiempos(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "VERA_Manny", "animation": "auto", "frames": 4},
        ToolContext())
    assert res.is_error is False
    meta = json.loads(res.content[0]["text"])
    assert meta["mode"] == "anim"                 # inferido por animation
    assert meta["times"] == [0.25, 0.75, 1.25, 1.75]
    assert meta["animation"] == "MM_Idle"


def test_orbit_rechaza_animation(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "mode": "orbit", "animation": "MM_Idle"},
        ToolContext())
    assert res.is_error is True


def test_validaciones_sin_bridge(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = CaptureActorTool()
    assert t.execute({"actor_name": "  "}, ToolContext()).is_error
    assert t.execute({"actor_name": "X", "frames": 0}, ToolContext()).is_error
    assert t.execute({"actor_name": "X", "frames": 7}, ToolContext()).is_error
    assert t.execute({"actor_name": "X", "mode": "vuelta"}, ToolContext()).is_error


def test_not_found_no_muta_ni_restaura(monkeypatch, tmp_path):
    bridge = FakeBridge(tmp_path, setup={"error": "not_found", "actor": "Nada",
                                         "candidates": ["Goal"]})
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute({"actor_name": "Nada"}, ToolContext())
    assert res.is_error is True
    assert bridge.kinds == ["setup"]              # sin frames y SIN restore


def test_not_skeletal_es_error_claro(monkeypatch, tmp_path):
    bridge = FakeBridge(tmp_path, setup={"error": "not_skeletal",
                                         "kind": "static", "hint": "usar mode=orbit"})
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "CyberHead", "animation": "auto"}, ToolContext())
    assert res.is_error is True
    assert "orbit" in res.content


def test_frame_falla_pero_restore_viaja(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, frame_fail_at=1)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 3}, ToolContext())
    assert res.is_error is True                   # 0 imágenes
    assert bridge.kinds[-1] == "restore"          # el finally lo mandó igual


def test_parcial_devuelve_lo_capturado_con_warning(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, frame_fail_at=2)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 2}, ToolContext())
    assert res.is_error is False                  # hay 1 frame útil
    meta = json.loads(res.content[0]["text"])
    assert meta["frames_capturados"] == 1
    assert meta["warnings"]
    assert meta["restored"] is True


def test_timeout_de_png_restaura_y_falla(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, write_files=False)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 1}, ToolContext())
    assert res.is_error is True
    assert bridge.kinds[-1] == "restore"


def test_restore_fallido_se_reporta(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, restore={"restored": False,
                                           "unhidden": 1, "errors": ["x"]})
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 1}, ToolContext())
    assert res.is_error is False                  # las capturas sirven igual
    meta = json.loads(res.content[0]["text"])
    assert meta["restored"] is False
    assert "restore_detail" in meta


def test_bridge_caido_en_setup(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = CaptureActorTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/agent/test_capture_actor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vera.agent.tools.capture_actor'`

- [ ] **Step 3: Write the implementation** — crear `vera/agent/tools/capture_actor.py` con EXACTAMENTE:

```python
# vera/agent/tools/capture_actor.py
"""Percepción visual (read-only): el cerebro VE un actor aislado.

"A por fuera, C por dentro": una sola llamada con restore garantizado; adentro
scripts separados setup/frame/restore orquestados acá. El restore viaja en un
finally del lado cliente: aunque un frame falle, el nivel vuelve a su estado.
Un screenshot por round-trip: take_high_res_screenshot es asíncrona y encolar
N capturas con N poses en un script tiene ordering azaroso.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

from vera.agent.tool import Tool, ToolContext, ToolResult, image_block
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._capture_scripts import (
    build_setup_script, build_frame_script, build_restore_script)
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

MAX_FRAMES = 6
FILE_TIMEOUT_S = 15.0
POLL_INTERVAL_S = 0.3


class CaptureActorTool(Tool):
    name = "capture_actor"
    description = (
        "Percepción visual (read-only): aísla un actor del nivel (oculta el "
        "resto, fondo neutro) y captura N frames a 640x360 que te llegan como "
        "imágenes — usala para VER un actor o juzgar una animación. "
        "mode=anim recorre una animación en N tiempos (requiere skeletal); "
        "mode=orbit lo rodea en N ángulos (cualquier actor). Restaura el nivel "
        "automáticamente al terminar."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {
                "type": "string",
                "description": "label del actor (match exacto o parcial)",
            },
            "mode": {
                "type": "string", "enum": ["anim", "orbit"],
                "description": "default: anim si hay animation, sino orbit",
            },
            "animation": {
                "type": "string",
                "description": "solo mode=anim: 'auto' o nombre de AnimSequence",
            },
            "frames": {
                "type": "integer", "minimum": 1, "maximum": 6,
                "description": "cantidad de capturas (default 4)",
            },
        },
        "required": ["actor_name"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor_name = (args.get("actor_name") or "").strip()
        if not actor_name:
            return ToolResult("falta actor_name (label del actor)", is_error=True)
        try:
            frames = int(args.get("frames", 4))
        except (TypeError, ValueError):
            return ToolResult("frames debe ser un entero entre 1 y 6", is_error=True)
        if not 1 <= frames <= MAX_FRAMES:
            return ToolResult("frames debe estar entre 1 y 6", is_error=True)
        animation = args.get("animation")
        mode = args.get("mode") or ("anim" if animation else "orbit")
        if mode not in ("anim", "orbit"):
            return ToolResult(f"mode inválido: {mode!r} (anim|orbit)", is_error=True)
        if mode == "orbit" and animation:
            return ToolResult("animation solo aplica a mode=anim", is_error=True)
        if mode == "anim" and not animation:
            animation = "auto"

        ctx.report("CaptureActor", f"aislando {actor_name!r} ({mode}, {frames} frames)")
        setup = self._send(ctx, build_setup_script(
            actor_name, animation if mode == "anim" else None))
        if isinstance(setup, ToolResult):
            return setup
        if setup.get("error"):
            # los errores del setup ocurren ANTES de mutar el nivel: sin restore
            return ToolResult(
                json.dumps(setup, ensure_ascii=False, sort_keys=True), is_error=True)

        if mode == "anim":
            length = float(setup.get("anim_length") or 0.0)
            values = [round((i + 0.5) / frames * length, 3) for i in range(frames)]
        else:
            values = [round(360.0 * i / frames, 1) for i in range(frames)]

        nonce = uuid.uuid4().hex[:8]
        shot_dir = setup.get("screenshot_dir") or ""
        files, images, warnings = [], [], []
        try:
            for i, value in enumerate(values):
                fname = f"vera_cap_{nonce}_{i}.png"
                ctx.report("CaptureActor", f"frame {i + 1}/{frames}")
                frame = self._send(ctx, build_frame_script(mode, value, fname))
                if isinstance(frame, ToolResult):
                    warnings.append(f"frame {i}: {frame.content}")
                    break
                if frame.get("error"):
                    warnings.append(f"frame {i}: {frame['error']}")
                    break
                path = os.path.join(shot_dir, fname)
                data = self._wait_for_file(path)
                if data is None:
                    warnings.append(f"frame {i}: timeout esperando {fname}")
                    break
                files.append(path)
                images.append(image_block(base64.b64encode(data).decode("ascii")))
        finally:
            restore_info = self._restore(ctx)

        meta = {
            "actor": setup.get("actor"), "mode": mode,
            "frames_capturados": len(images), "files": files,
            "hidden_actors": setup.get("hidden_actors"),
            "restored": bool(restore_info.get("restored")),
        }
        if mode == "anim":
            meta["animation"] = setup.get("animation")
            meta["anim_length"] = setup.get("anim_length")
            meta["times"] = values[: len(images)]
        else:
            meta["angles"] = values[: len(images)]
        if warnings:
            meta["warnings"] = warnings
        if not restore_info.get("restored"):
            meta["restore_detail"] = restore_info

        text = json.dumps(meta, ensure_ascii=False, sort_keys=True)
        if not images:
            return ToolResult(text, is_error=True)
        return ToolResult([{"type": "text", "text": text}] + images)

    # ---- helpers ----

    def _send(self, ctx: ToolContext, script: str):
        """Un round-trip por el bridge: dict parseado o ToolResult de error."""
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge caído: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo en el editor", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        return data

    def _restore(self, ctx: ToolContext) -> dict:
        """Best-effort y nunca lanza: el finally no debe enmascarar el error real."""
        try:
            data = self._send(ctx, build_restore_script())
        except Exception as e:  # noqa: BLE001
            return {"restored": False, "reason": str(e)}
        if isinstance(data, ToolResult):
            return {"restored": False, "reason": str(data.content)}
        if data.get("reason") == "no_state":
            # setup nunca llegó a mutar: no había nada que restaurar
            return {"restored": True, "reason": "no_state"}
        return data

    def _wait_for_file(self, path: str, timeout=None, interval=None):
        """Espera a que el PNG exista con tamaño estable. bytes o None.
        Lee los límites del módulo en runtime para que los tests los achiquen."""
        timeout = FILE_TIMEOUT_S if timeout is None else timeout
        interval = POLL_INTERVAL_S if interval is None else interval
        deadline = time.monotonic() + timeout
        last = -1
        while time.monotonic() < deadline:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            if size > 0 and size == last:
                with open(path, "rb") as f:
                    return f.read()
            last = size
            time.sleep(interval)
        return None
```

OJO: `_wait_for_file` lee `FILE_TIMEOUT_S`/`POLL_INTERVAL_S` como globals del módulo en tiempo de llamada (no como defaults de parámetro) a propósito — los tests los monkeypatchean.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/agent/test_capture_actor.py -v`
Expected: 12 passed. Si falla alguno, arreglar la implementación — NO debilitar tests.

- [ ] **Step 5: Run the whole agent suite**

Run: `python -m pytest tests/agent/ -v`
Expected: 100 passed (88 + 12; el registry descubre `capture_actor` sin colisiones)

- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/capture_actor.py tests/agent/test_capture_actor.py
git -C E:/PCW/VERA commit -m "feat(agent): tool capture_actor — el cerebro ve actores aislados (anim scrub u orbita, restore en finally)"
```

---

### Task 4: Suite completa + roadmap

**Files:**
- Modify: `E:/PCW/VERA/PLAN_VERA.md` (línea de Fase 2 en la sección "Animaciones (roadmap)")

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: los 100 de `tests/agent/` verdes. Los fallos preexistentes conocidos (`test_perception.py`, `test_manager.py`, `test_python_agent.py` — dependen de keys/mocks viejos, documentado en el plan de fase 1) NO bloquean si no tocan archivos de animación/captura.

- [ ] **Step 2: Update PLAN_VERA.md** — en la sección `## Animaciones (roadmap)`, reemplazar la línea de Fase 2 por:

```markdown
- **Fase 2 (implementada 2026-06-12):** percepción visual — tool `capture_actor`
  (aislamiento + unlit + scrub/órbita determinísticos, restore garantizado). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase2-capture-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git -C E:/PCW/VERA add PLAN_VERA.md
git -C E:/PCW/VERA commit -m "docs: fase 2 de animaciones implementada en el roadmap"
```

---

### Task 5: Demo E2E en vivo (gate de éxito — editor abierto + bridge 9878)

NO declarar éxito sin los 3 checks con evidencia. El cerebro (Claude vía bridge) ejecuta la tool real y DESCRIBE lo que ve en las imágenes.

- [ ] **Step 1: Estado base** — registrar conteo de actores visibles y modo de vista:

```bash
python -c "from vera.tools.ue_conn import send_json; print(send_json(9878, {'script': 'import unreal\neas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)\nvis = [a for a in eas.get_all_level_actors() if not a.is_temporarily_hidden_in_editor()]\nprint(len(vis))'}))"
```

- [ ] **Step 2: Check 1 — anim.** Ejecutar `CaptureActorTool` con `{"actor_name": "VERA_Manny", "animation": "MM_Idle", "frames": 4}`. Esperado: 4 imágenes del Manny solo sobre fondo plano, en 4 puntos de la animación; `restored: true`. El cerebro describe las poses.

- [ ] **Step 3: Check 2 — orbit.** `{"actor_name": "Enemy_CyberHead", "mode": "orbit", "frames": 4}`. Esperado: el CyberHead desde 4 ángulos (0/90/180/270), aislado.

- [ ] **Step 4: Check 3 — restore.** Repetir el conteo del Step 1: mismo número de actores visibles; verificar viewmode lit y cámara razonable. El `animation_mode` del Manny volvió al previo.

- [ ] **Step 5: Registrar evidencia** — apéndice en `docs/vera_minigame_run_log.md` (sección "E2E Fase 2") con los 3 checks y paths de los PNG, y commit:

```bash
git -C E:/PCW/VERA add docs/vera_minigame_run_log.md
git -C E:/PCW/VERA commit -m "docs: evidencia E2E fase 2 (capture_actor en vivo)"
```

---

## Self-review del plan

- **Cobertura del spec:** contratos de tool e internals (Tasks 2-3), tabla de errores completa testeada (Task 3: not_found sin restore, not_skeletal, frame-fail→restore, parcial+warning, timeout, restore fallido reportado, bridge caído), un-screenshot-por-round-trip (frame script), `_pick_name` pre-mutación (Task 1), E2E con los 3 checks del spec (Task 5). Sin huecos.
- **Sin placeholders:** todo el código está completo.
- **Consistencia:** firmas de `build_*` idénticas entre Task 2 (definición) y Task 3 (uso); claves JSON (`restored`, `screenshot_dir`, `anim_length`, `hidden_actors`, `times`/`angles`) consistentes entre templates, tool y tests; el FakeBridge discrimina por los mismos marcadores que existen en los templates (`sys.modules.pop`, `take_high_res_screenshot`).
