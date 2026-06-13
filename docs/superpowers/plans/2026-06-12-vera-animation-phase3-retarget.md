# VERA Fase 3 — Retargeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tres tools find-first del cerebro — `ensure_ik_rig`, `ensure_retargeter`, `retarget_animations` — que permiten retargetear animaciones a cualquier esqueleto humanoide (auto-creando IK Rigs y Retargeters cuando no existen). Spec: `docs/superpowers/specs/2026-06-12-vera-animation-phase3-retarget-design.md`.

**Architecture:** Tools separadas (decisión de Ezequiel: cada concern consumible por sí solo). Cada tool sigue el patrón de fases 1-2: wrapper Python fino → script curado vía bridge 9878 → JSON de una línea. Builders compartidos en `_retarget_scripts.py` sobre `_COMMON` de `_anim_scripts.py`.

**Tech Stack:** Python 3 (repo `E:\PCW\VERA`), pytest+monkeypatch, UE 5.7 Python API (IKRig).

## Task 0 — COMPLETADO durante el planning: probing en vivo de la API

Todas las llamadas del pipeline fueron verificadas contra el editor real (UE4
Mannequin retargeteado de punta a punta y assets de prueba borrados). Los
implementadores NO deben "corregir" estas llamadas — son las que funcionan:

| Llamada verificada | Nota |
|---|---|
| `at.create_asset(name, path, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())` | crea el rig |
| `unreal.IKRigController.get_controller(rig)` / `.set_skeletal_mesh(mesh)` → bool | False = mesh incompatible |
| `.apply_auto_generated_retarget_definition()` → bool | auto-characterize; False = esqueleto sin template conocido (¡error honesto gratis!) |
| `.get_retarget_chains()` → Array; `chain.chain_name`; `.get_retarget_root()` | UE4 manny: 20 chains, root "pelvis" |
| `at.create_asset(..., unreal.IKRetargeter, unreal.IKRetargetFactory())` | crea retargeter con 6 ops default |
| `rc.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE/TARGET, rig)` | NO alcanza solo |
| **`rc.assign_ik_rig_to_all_ops(SOURCE/TARGET, rig)`** | **LA PIEZA NO DOCUMENTADA de 5.7**: sin esto los ops no conocen los rigs y el mapping queda vacío en silencio |
| `rc.auto_map_chains(unreal.AutoMapChainType.FUZZY, True)` | después del assign |
| `rc.get_source_chain(target_chain_name)` → Name ("None" si no mapeada) | default lee el primer op con chain mapping |
| `rc.get_ik_rig(SOURCE/TARGET)` → IKRigDefinition | para el find-first de retargeters |
| `unreal.AssetRegistryHelpers.create_asset_data(anim)` | input del batch |
| `unreal.IKRetargetBatchOperation.duplicate_and_retarget([ad], src_mesh, tgt_mesh, rtg, suffix="_VERA_RTG")` → Array[AssetData] | **deja los duplicados en `/Game/` raíz** — moverlos con `EditorAssetLibrary.rename_asset` |
| `unreal.EditorAssetLibrary.delete_asset(path)` / `does_asset_exist(path)` / `rename_asset(old, new)` | cleanup/find-first/mover |

Gotchas heredados vigentes: properties pueden estar bloqueadas ("cannot be
edited on templates") — preferir setters; `op_stack` está deprecado (no tocar);
JSON compacto de una línea en todos los scripts.

**Convenciones del repo** (idénticas a fases 1-2): tests desde `E:\PCW\VERA`;
tools importan `send_json` a su namespace; NUNCA `git add -A`; `is_error=True`
solo para fallos del sistema o pedidos imposibles.

---

### Task 1: Builders `_retarget_scripts.py`

**Files:**
- Create: `vera/agent/tools/_retarget_scripts.py`
- Test: `tests/agent/test_retarget_scripts.py`

- [ ] **Step 1: failing tests** — crear `tests/agent/test_retarget_scripts.py`:

```python
# tests/agent/test_retarget_scripts.py
from vera.agent.tools._retarget_scripts import (
    build_ensure_rig_script,
    build_ensure_retargeter_script,
    build_retarget_batch_script,
)


def test_ensure_rig_inyecta_ref_y_caracteriza():
    s = build_ensure_rig_script('El "Raton"')
    assert '"El \\"Raton\\""' in s
    assert "apply_auto_generated_retarget_definition" in s
    assert "IKRigDefinitionFactory" in s
    assert "_find_rig_for" in s              # find-first antes de crear
    assert "__REF__" not in s
    assert "indent" not in s                 # JSON una línea


def test_ensure_rig_borra_el_asset_si_no_caracteriza():
    # un rig sin chains es basura: si el auto-characterize falla, no debe quedar
    s = build_ensure_rig_script("X")
    assert "delete_asset" in s


def test_ensure_retargeter_tiene_la_pieza_de_57():
    s = build_ensure_retargeter_script("A", "B")
    assert '"A"' in s and '"B"' in s
    assert "assign_ik_rig_to_all_ops" in s   # sin esto el mapping queda vacío (probado en vivo)
    assert "auto_map_chains" in s
    assert "get_source_chain" in s
    assert "IKRetargetFactory" in s
    assert "__SRC__" not in s and "__TGT__" not in s


def test_retarget_batch_mueve_y_es_idempotente():
    s = build_retarget_batch_script("/Game/R/RTG", ["MM_Idle"], "Bot", True)
    assert '"/Game/R/RTG"' in s
    assert '["MM_Idle"]' in s
    assert "duplicate_and_retarget" in s
    assert "rename_asset" in s               # el batch deja todo en /Game raíz
    assert "does_asset_exist" in s           # skip de ya-retargeteadas
    assert "_VERA_RTG" in s
    assert "play_first = True" in s
    assert "__RTG__" not in s and "__ANIMS__" not in s


def test_retarget_batch_auto_y_sin_actor():
    s = build_retarget_batch_script("/Game/R/RTG", "auto", None, False)
    assert '"auto"' in s
    assert "target_actor = None" in s
    assert "play_first = False" in s


def test_helpers_compartidos_presentes():
    s = build_ensure_rig_script("X")
    assert "_skeleton_from_ref" in s and "_find_actor" in s
    s2 = build_retarget_batch_script("/Game/R", "auto", None, False)
    assert "_anims_for_skeleton" in s2
```

- [ ] **Step 2:** `python -m pytest tests/agent/test_retarget_scripts.py -v` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: implementación** — crear `vera/agent/tools/_retarget_scripts.py`:

```python
# vera/agent/tools/_retarget_scripts.py
"""Builders de scripts curados para las tools de retargeting (fase 3).

Pipeline verificado EN VIVO contra UE 5.7 (ver Task 0 del plan): la pieza
crítica no documentada es assign_ik_rig_to_all_ops — sin ella los ops del
retargeter no conocen los rigs y el chain mapping queda vacío en silencio.
Mismas reglas que _anim_scripts: tokens __X__ con json.dumps/repr, JSON
compacto de una línea.
"""
from __future__ import annotations

import json

from vera.agent.tools._anim_scripts import _COMMON

_RTG_COMMON = _COMMON + '''
def _skeleton_from_ref(ref):
    """ref: label de actor o path (/Game/...) de Skeleton/SkeletalMesh/IKRig.
    -> (skeleton, mesh|None, error|None)"""
    if ref.startswith("/"):
        a = unreal.load_asset(ref)
        if a is None:
            return None, None, "asset no encontrado: %s" % ref
        if isinstance(a, unreal.SkeletalMesh):
            return a.get_editor_property("skeleton"), a, None
        if isinstance(a, unreal.IKRigDefinition):
            m = unreal.IKRigController.get_controller(a).get_skeletal_mesh()
            if m is None:
                return None, None, "el IK Rig %s no tiene mesh asignado" % ref
            return m.get_editor_property("skeleton"), m, None
        if isinstance(a, unreal.Skeleton):
            return a, None, None
        return None, None, "tipo no soportado: %s" % type(a).__name__
    actor, actors = _find_actor(ref)
    if actor is None:
        return None, None, ("actor no encontrado: %s (parecidos: %s)"
                            % (ref, ", ".join(_candidates(actors, ref))))
    info, comp = _diagnose(actor)
    if info["kind"] != "skeletal":
        return None, None, "'%s' no es skeletal (%s)" % (info["actor"], info["kind"])
    mesh = comp.get_skeletal_mesh_asset()
    return mesh.get_editor_property("skeleton"), mesh, None

def _find_rig_for(skel):
    """IKRigDefinition existente cuyo mesh use este skeleton, o None (find-first)."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    flt = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/IKRig", "IKRigDefinition")],
        package_paths=["/Game"], recursive_paths=True)
    sp = skel.get_path_name()
    for ad in ar.get_assets(flt):
        rig = unreal.load_asset(str(ad.package_name))
        if rig is None:
            continue
        m = unreal.IKRigController.get_controller(rig).get_skeletal_mesh()
        if m is not None:
            s = m.get_editor_property("skeleton")
            if s is not None and s.get_path_name() == sp:
                return rig
    return None

def _anims_for_skeleton(skel):
    """{nombre: package_path} de las AnimSequences de /Game para este skeleton."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    flt = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "AnimSequence")],
        package_paths=["/Game"], recursive_paths=True)
    sp = skel.get_path_name()
    res = {}
    for ad in ar.get_assets(flt):
        tag = ad.get_tag_value("Skeleton")
        if tag and sp in str(tag):
            res[str(ad.asset_name)] = str(ad.package_name)
    return res

def _pkg_dir(asset):
    return asset.get_path_name().rsplit(".", 1)[0].rsplit("/", 1)[0]
'''

_ENSURE_RIG_TEMPLATE = _RTG_COMMON + '''
ref = __REF__

skel, mesh, err = _skeleton_from_ref(ref)
if err is not None:
    print(json.dumps({"error": "bad_ref", "detail": err}, sort_keys=True))
elif mesh is None:
    print(json.dumps({"error": "need_mesh",
                      "detail": "pasa un actor o un SkeletalMesh; un Skeleton solo no alcanza para crear el rig"},
                     sort_keys=True))
else:
    rig = _find_rig_for(skel)
    created = False
    error = None
    if rig is None:
        at = unreal.AssetToolsHelpers.get_asset_tools()
        name = "IK_VERA_" + skel.get_name()
        rig = at.create_asset(name, _pkg_dir(mesh), unreal.IKRigDefinition,
                              unreal.IKRigDefinitionFactory())
        if rig is None:
            error = {"error": "create_failed", "name": name, "path": _pkg_dir(mesh)}
        else:
            ctrl = unreal.IKRigController.get_controller(rig)
            if not ctrl.set_skeletal_mesh(mesh):
                unreal.EditorAssetLibrary.delete_asset(rig.get_path_name())
                error = {"error": "mesh_incompatible", "mesh": mesh.get_name()}
            elif not ctrl.apply_auto_generated_retarget_definition():
                # un rig sin chains es basura: borrarlo y reportar honesto
                unreal.EditorAssetLibrary.delete_asset(rig.get_path_name())
                error = {"error": "not_characterizable",
                         "skeleton": skel.get_name(),
                         "detail": ("el esqueleto no coincide con ningun template "
                                    "conocido (no parece humanoide); el rig requiere "
                                    "chains manuales en el editor")}
            else:
                created = True
    if error is not None:
        print(json.dumps(error, sort_keys=True))
    else:
        ctrl = unreal.IKRigController.get_controller(rig)
        chains = [str(c.chain_name) for c in ctrl.get_retarget_chains()]
        out = {"rig_path": rig.get_path_name().rsplit(".", 1)[0],
               "skeleton": skel.get_name(), "chains": chains,
               "retarget_root": str(ctrl.get_retarget_root()), "created": created}
        if not chains:
            out["warning"] = "rig existente sin retarget chains: inutil para retargetear"
        print(json.dumps(out, sort_keys=True))
'''

_ENSURE_RTG_TEMPLATE = _RTG_COMMON + '''
src_ref = __SRC__
tgt_ref = __TGT__

src_skel, _sm, e1 = _skeleton_from_ref(src_ref)
tgt_skel, _tm, e2 = _skeleton_from_ref(tgt_ref)
if e1 is not None or e2 is not None:
    print(json.dumps({"error": "bad_ref", "detail": e1 or e2}, sort_keys=True))
else:
    src_rig = _find_rig_for(src_skel)
    tgt_rig = _find_rig_for(tgt_skel)
    if src_rig is None or tgt_rig is None:
        faltan = [n for n, r in (("source", src_rig), ("target", tgt_rig)) if r is None]
        print(json.dumps({"error": "missing_ik_rig", "missing": faltan,
                          "detail": "usa ensure_ik_rig primero (un gate por asset)"},
                         sort_keys=True))
    else:
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        flt = unreal.ARFilter(
            class_paths=[unreal.TopLevelAssetPath("/Script/IKRig", "IKRetargeter")],
            package_paths=["/Game"], recursive_paths=True)
        rtg, created = None, False
        sp, tp = src_rig.get_path_name(), tgt_rig.get_path_name()
        for ad in ar.get_assets(flt):
            cand = unreal.load_asset(str(ad.package_name))
            if cand is None:
                continue
            c = unreal.IKRetargeterController.get_controller(cand)
            s, t = c.get_ik_rig(unreal.RetargetSourceOrTarget.SOURCE), c.get_ik_rig(
                unreal.RetargetSourceOrTarget.TARGET)
            if s is not None and t is not None and s.get_path_name() == sp and t.get_path_name() == tp:
                rtg = cand
                break
        if rtg is None:
            at = unreal.AssetToolsHelpers.get_asset_tools()
            name = "RTG_VERA_%s_to_%s" % (src_skel.get_name(), tgt_skel.get_name())
            rtg = at.create_asset(name, _pkg_dir(tgt_rig), unreal.IKRetargeter,
                                  unreal.IKRetargetFactory())
            rc = unreal.IKRetargeterController.get_controller(rtg)
            rc.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, src_rig)
            rc.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, tgt_rig)
            # PIEZA CRITICA 5.7 (verificada en vivo): sin esto los ops no
            # conocen los rigs y el mapping queda vacio EN SILENCIO
            rc.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.SOURCE, src_rig)
            rc.assign_ik_rig_to_all_ops(unreal.RetargetSourceOrTarget.TARGET, tgt_rig)
            rc.auto_map_chains(unreal.AutoMapChainType.FUZZY, True)
            created = True
        rc = unreal.IKRetargeterController.get_controller(rtg)
        tctrl = unreal.IKRigController.get_controller(tgt_rig)
        mapping, unmapped = [], []
        for ch in tctrl.get_retarget_chains():
            tname = str(ch.chain_name)
            sname = str(rc.get_source_chain(tname))
            if sname == "None":
                unmapped.append(tname)
            else:
                mapping.append([sname, tname])
        if not mapping:
            if created:
                unreal.EditorAssetLibrary.delete_asset(rtg.get_path_name())
            print(json.dumps({"error": "no_chains_mapped", "created_then_deleted": created,
                              "target_chains": unmapped,
                              "detail": "auto_map_chains no encontro pares; revisar nombres de chains"},
                             sort_keys=True))
        else:
            print(json.dumps({"retargeter_path": rtg.get_path_name().rsplit(".", 1)[0],
                              "chain_mapping": mapping, "unmapped_chains": unmapped,
                              "created": created}, sort_keys=True))
'''

_RETARGET_BATCH_TEMPLATE = _RTG_COMMON + '''
rtg_path = __RTG__
anims_req = __ANIMS__
target_actor = __ACTOR__
play_first = __PLAY__

rtg = unreal.load_asset(rtg_path)
if rtg is None:
    print(json.dumps({"error": "retargeter_not_found", "path": rtg_path}, sort_keys=True))
else:
    rc = unreal.IKRetargeterController.get_controller(rtg)
    src_rig = rc.get_ik_rig(unreal.RetargetSourceOrTarget.SOURCE)
    tgt_rig = rc.get_ik_rig(unreal.RetargetSourceOrTarget.TARGET)
    src_mesh = unreal.IKRigController.get_controller(src_rig).get_skeletal_mesh() if src_rig else None
    tgt_mesh = unreal.IKRigController.get_controller(tgt_rig).get_skeletal_mesh() if tgt_rig else None
    if src_mesh is None or tgt_mesh is None:
        print(json.dumps({"error": "retargeter_incomplete",
                          "detail": "el retargeter no tiene rigs/meshes completos"}, sort_keys=True))
    else:
        anim_map = _anims_for_skeleton(src_mesh.get_editor_property("skeleton"))
        skipped = []
        if anims_req == "auto":
            names = sorted(anim_map.keys(), key=len)
            chosen, seen = [], set()
            for kw in ("idle", "walk", "jog"):
                for n in names:
                    if kw in n.lower() and n not in seen:
                        chosen.append(n); seen.add(n)
                        break
            for n in names:
                if len(chosen) >= 5:
                    break
                if n not in seen:
                    chosen.append(n); seen.add(n)
        else:
            chosen = []
            for n in anims_req:
                if n in anim_map:
                    chosen.append(n)
                else:
                    skipped.append(n + " (no existe para el skeleton source)")
        dest_dir = _pkg_dir(tgt_mesh) + "/VERA_Retargeted"
        to_do = []
        for n in chosen:
            if unreal.EditorAssetLibrary.does_asset_exist(dest_dir + "/" + n + "_VERA_RTG"):
                skipped.append(n + " (ya retargeteada)")
            else:
                to_do.append(n)
        created = []
        if to_do:
            ads = [unreal.AssetRegistryHelpers.create_asset_data(unreal.load_asset(anim_map[n]))
                   for n in to_do]
            res = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
                ads, src_mesh, tgt_mesh, rtg, suffix="_VERA_RTG")
            for ad in res:
                # el batch deja los duplicados en /Game raiz (verificado en vivo): moverlos
                old = str(ad.package_name)
                new = dest_dir + "/" + str(ad.asset_name)
                unreal.EditorAssetLibrary.rename_asset(old, new)
                created.append(new)
        available = created + [dest_dir + "/" + n + "_VERA_RTG" for n in chosen if n not in to_do]
        played = None
        if play_first and target_actor is not None and available:
            actor, actors = _find_actor(target_actor)
            if actor is not None:
                comps = list(actor.get_components_by_class(unreal.SkeletalMeshComponent))
                anim = unreal.load_asset(available[0])
                if comps and anim is not None:
                    comp = comps[0]
                    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                    try:
                        comp.set_update_animation_in_editor(True)
                    except Exception:
                        pass
                    comp.play_animation(anim, True)
                    played = available[0].rsplit("/", 1)[-1]
        if not created and not skipped:
            print(json.dumps({"error": "no_anims",
                              "detail": "ninguna animacion para retargetear (revisa la lista o el skeleton source)"},
                             sort_keys=True))
        else:
            print(json.dumps({"created_anims": created, "skipped": skipped,
                              "played": played}, sort_keys=True))
'''


def build_ensure_rig_script(ref: str) -> str:
    return _ENSURE_RIG_TEMPLATE.replace("__REF__", json.dumps(ref))


def build_ensure_retargeter_script(source: str, target: str) -> str:
    return (_ENSURE_RTG_TEMPLATE
            .replace("__SRC__", json.dumps(source))
            .replace("__TGT__", json.dumps(target)))


def build_retarget_batch_script(retargeter_path: str, animations,
                                target_actor, play_first: bool) -> str:
    anims_literal = (json.dumps(animations) if isinstance(animations, str)
                     else json.dumps(list(animations)))
    actor_literal = json.dumps(target_actor) if target_actor is not None else "None"
    return (_RETARGET_BATCH_TEMPLATE
            .replace("__RTG__", json.dumps(retargeter_path))
            .replace("__ANIMS__", anims_literal)
            .replace("__ACTOR__", actor_literal)
            .replace("__PLAY__", repr(bool(play_first))))
```

- [ ] **Step 4:** `python -m pytest tests/agent/test_retarget_scripts.py -v` → 6 passed.
- [ ] **Step 5:** `python -m pytest tests/agent/ -v` → 111 passed (105 + 6).
- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/_retarget_scripts.py tests/agent/test_retarget_scripts.py
git -C E:/PCW/VERA commit -m "feat(agent): builders de retargeting (pipeline IKRig 5.7 verificado en vivo, assign_ik_rig_to_all_ops)"
```

---

### Task 2: Tool `ensure_ik_rig`

**Files:**
- Create: `vera/agent/tools/ensure_ik_rig.py`
- Test: `tests/agent/test_ensure_ik_rig.py`

- [ ] **Step 1: failing tests** — crear `tests/agent/test_ensure_ik_rig.py`:

```python
# tests/agent/test_ensure_ik_rig.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_ik_rig import EnsureIKRigTool
import vera.agent.tools.ensure_ik_rig as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert EnsureIKRigTool().destructive is True


def test_encontrado_existente(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"rig_path": "/Game/R/IK_Mannequin", "skeleton": "SK_Mannequin",
                    "chains": ["Spine", "LeftArm"], "retarget_root": "pelvis",
                    "created": False})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = EnsureIKRigTool().execute({"actor_name": "UE4Guy"}, ToolContext())
    assert res.is_error is False
    assert '"created": false' in res.content
    assert '"UE4Guy"' in captured["script"]


def test_creado_nuevo(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"rig_path": "/Game/X/IK_VERA_SK_Y", "skeleton": "SK_Y",
         "chains": ["Spine"], "retarget_root": "pelvis", "created": True}))
    res = EnsureIKRigTool().execute({"skeleton_path": "/Game/X/SK_Y"}, ToolContext())
    assert res.is_error is False
    assert '"created": true' in res.content


def test_no_caracterizable_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "not_characterizable", "skeleton": "SK_SteampunkCar02",
         "detail": "no parece humanoide"}))
    res = EnsureIKRigTool().execute(
        {"skeleton_path": "/Game/S/SK_SteampunkCar02"}, ToolContext())
    assert res.is_error is True
    assert "not_characterizable" in res.content


def test_requiere_exactamente_una_ref(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = EnsureIKRigTool()
    assert t.execute({}, ToolContext()).is_error
    assert t.execute({"actor_name": "A", "skeleton_path": "/Game/B"},
                     ToolContext()).is_error


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = EnsureIKRigTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor cerrado" in res.content
```

- [ ] **Step 2:** Run → FAIL (ModuleNotFoundError).

- [ ] **Step 3: implementación** — crear `vera/agent/tools/ensure_ik_rig.py`:

```python
# vera/agent/tools/ensure_ik_rig.py
"""Find-first: garantiza que exista un IKRigDefinition para un esqueleto.

Si ya hay un rig para ese skeleton lo devuelve (created: false, idempotente);
si no, lo crea con auto-characterize. Si el esqueleto no coincide con ningún
template humanoide conocido, borra el asset a medio crear y reporta honesto.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._retarget_scripts import build_ensure_rig_script
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class EnsureIKRigTool(Tool):
    name = "ensure_ik_rig"
    description = (
        "Garantiza que exista un IK Rig para el esqueleto de un actor o "
        "SkeletalMesh (lo encuentra si ya existe, o lo crea con "
        "auto-characterize). Es el paso 1 del retargeting: usala antes de "
        "ensure_retargeter. Crea un asset: requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {"type": "string",
                           "description": "label de un actor skeletal del nivel"},
            "skeleton_path": {"type": "string",
                              "description": "path /Game/... de un SkeletalMesh o IKRig"},
        },
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor = (args.get("actor_name") or "").strip()
        skel = (args.get("skeleton_path") or "").strip()
        if bool(actor) == bool(skel):
            return ToolResult(
                "pasá exactamente una referencia: actor_name O skeleton_path",
                is_error=True)
        ref = actor or skel
        ctx.report("EnsureIKRig", f"resolviendo rig para {ref!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_ensure_rig_script(ref)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge caído: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo en el editor", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        return ToolResult(rendered, is_error=bool(data.get("error")))
```

- [ ] **Step 4:** Run tool tests → 6 passed. **Step 5:** `pytest tests/agent/ -v` → 117 passed.
- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/ensure_ik_rig.py tests/agent/test_ensure_ik_rig.py
git -C E:/PCW/VERA commit -m "feat(agent): tool ensure_ik_rig (find-first + auto-characterize con borrado si falla)"
```

---

### Task 3: Tool `ensure_retargeter`

**Files:**
- Create: `vera/agent/tools/ensure_retargeter.py`
- Test: `tests/agent/test_ensure_retargeter.py`

- [ ] **Step 1: failing tests** — crear `tests/agent/test_ensure_retargeter.py`:

```python
# tests/agent/test_ensure_retargeter.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.ensure_retargeter import EnsureRetargeterTool
import vera.agent.tools.ensure_retargeter as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert EnsureRetargeterTool().destructive is True


def test_encontrado_o_creado_devuelve_mapping(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"retargeter_path": "/Game/R/RTG_VERA_A_to_B",
                    "chain_mapping": [["LeftArm", "LeftArm"], ["Spine", "Spine"]],
                    "unmapped_chains": ["LeftPinky"], "created": True})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = EnsureRetargeterTool().execute(
        {"source": "/Game/A/SKM_Manny", "target": "UE4Guy"}, ToolContext())
    assert res.is_error is False
    assert "LeftArm" in res.content and "LeftPinky" in res.content
    assert '"/Game/A/SKM_Manny"' in captured["script"]
    assert '"UE4Guy"' in captured["script"]


def test_rig_faltante_es_error_que_apunta_a_ensure_ik_rig(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "missing_ik_rig", "missing": ["target"],
         "detail": "usa ensure_ik_rig primero (un gate por asset)"}))
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True
    assert "ensure_ik_rig" in res.content


def test_cero_chains_mapeadas_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "no_chains_mapped", "created_then_deleted": True,
         "target_chains": ["Tentacle1"], "detail": "sin pares"}))
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True


def test_requiere_source_y_target(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = EnsureRetargeterTool()
    assert t.execute({"source": "A"}, ToolContext()).is_error
    assert t.execute({"target": "B"}, ToolContext()).is_error


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = EnsureRetargeterTool().execute(
        {"source": "A", "target": "B"}, ToolContext())
    assert res.is_error is True
```

- [ ] **Step 2:** Run → FAIL. **Step 3: implementación** — crear `vera/agent/tools/ensure_retargeter.py`:

```python
# vera/agent/tools/ensure_retargeter.py
"""Find-first: garantiza que exista un IKRetargeter source→target.

Requiere que AMBOS IK Rigs existan (un gate por asset: si falta uno, el error
apunta a ensure_ik_rig — no lo crea implícitamente). El chain mapping va en el
output para que el cerebro juzgue la calidad ANTES de gastar el batch.
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._retarget_scripts import build_ensure_retargeter_script
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class EnsureRetargeterTool(Tool):
    name = "ensure_retargeter"
    description = (
        "Garantiza que exista un IK Retargeter del esqueleto source al target "
        "(lo encuentra o lo crea con auto-mapeo fuzzy de chains). Requiere que "
        "ambos IK Rigs existan (usá ensure_ik_rig antes). Devuelve el chain "
        "mapping para que evalúes su calidad. Es el paso 2 del retargeting. "
        "Crea un asset: requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string",
                       "description": "de dónde copiar la animación: label de actor o path de SkeletalMesh/IKRig"},
            "target": {"type": "string",
                       "description": "hacia dónde: label de actor o path de SkeletalMesh/IKRig"},
        },
        "required": ["source", "target"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        source = (args.get("source") or "").strip()
        target = (args.get("target") or "").strip()
        if not source or not target:
            return ToolResult("source y target son requeridos", is_error=True)
        ctx.report("EnsureRetargeter", f"{source!r} -> {target!r}")
        try:
            resp = send_json(ctx.bridge_port,
                             {"script": build_ensure_retargeter_script(source, target)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge caído: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo en el editor", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        return ToolResult(rendered, is_error=bool(data.get("error")))
```

- [ ] **Step 4:** tests de la tool → 6 passed. **Step 5:** suite → 123 passed.
- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/ensure_retargeter.py tests/agent/test_ensure_retargeter.py
git -C E:/PCW/VERA commit -m "feat(agent): tool ensure_retargeter (find-first + auto-map fuzzy, mapping visible para el cerebro)"
```

---

### Task 4: Tool `retarget_animations`

**Files:**
- Create: `vera/agent/tools/retarget_animations.py`
- Test: `tests/agent/test_retarget_animations.py`

- [ ] **Step 1: failing tests** — crear `tests/agent/test_retarget_animations.py`:

```python
# tests/agent/test_retarget_animations.py
import json

from vera.agent.tool import ToolContext
from vera.agent.tools.retarget_animations import RetargetAnimationsTool
import vera.agent.tools.retarget_animations as mod
from vera.tools.ue_conn import UEConnectionError


def _ok(payload):
    return {"success": True, "output": json.dumps(payload)}


def test_es_destructiva():
    assert RetargetAnimationsTool().destructive is True


def test_batch_feliz_con_play(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"created_anims": ["/Game/T/VERA_Retargeted/MM_Idle_VERA_RTG"],
                    "skipped": [], "played": "MM_Idle_VERA_RTG"})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R/RTG", "animations": ["MM_Idle"],
         "target_actor_name": "UE4Guy", "play_first": True}, ToolContext())
    assert res.is_error is False
    assert "MM_Idle_VERA_RTG" in res.content
    assert '"/Game/R/RTG"' in captured["script"]
    assert "play_first = True" in captured["script"]


def test_auto_por_default(monkeypatch):
    captured = {}

    def fake_send(port, payload, *a, **k):
        captured["script"] = payload["script"]
        return _ok({"created_anims": ["/Game/x"], "skipped": [], "played": None})

    monkeypatch.setattr(mod, "send_json", fake_send)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R/RTG"}, ToolContext())
    assert res.is_error is False
    assert '"auto"' in captured["script"]


def test_idempotente_todo_skipped_no_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"created_anims": [], "skipped": ["MM_Idle (ya retargeteada)"],
         "played": None}))
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R/RTG", "animations": ["MM_Idle"]},
        ToolContext())
    assert res.is_error is False
    assert "ya retargeteada" in res.content


def test_retargeter_inexistente_es_error(monkeypatch):
    monkeypatch.setattr(mod, "send_json", lambda *a, **k: _ok(
        {"error": "retargeter_not_found", "path": "/Game/Nada"}))
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/Nada"}, ToolContext())
    assert res.is_error is True


def test_play_first_requiere_actor(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no debe llamar al bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R", "play_first": True}, ToolContext())
    assert res.is_error is True


def test_bridge_caido(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor cerrado")
    monkeypatch.setattr(mod, "send_json", boom)
    res = RetargetAnimationsTool().execute(
        {"retargeter_path": "/Game/R"}, ToolContext())
    assert res.is_error is True
```

- [ ] **Step 2:** Run → FAIL. **Step 3: implementación** — crear `vera/agent/tools/retarget_animations.py`:

```python
# vera/agent/tools/retarget_animations.py
"""Batch retarget: duplica AnimSequences del skeleton source al target.

Find-first/idempotente: las anims ya retargeteadas (sufijo _VERA_RTG en
<carpeta del mesh target>/VERA_Retargeted/) se saltean, no se duplican.
Opcionalmente reproduce la primera en un actor (cerrando el loop con fase 1:
después usá capture_actor para VER el resultado).
"""
from __future__ import annotations

import json

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._retarget_scripts import build_retarget_batch_script
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError


class RetargetAnimationsTool(Tool):
    name = "retarget_animations"
    description = (
        "Retargetea AnimSequences del esqueleto source al target usando un IK "
        "Retargeter existente (usá ensure_retargeter antes). 'auto' elige el "
        "set básico de locomoción (idle/walk/jog, hasta 5). Crea assets nuevos "
        "(sufijo _VERA_RTG) y opcionalmente reproduce el primero en un actor. "
        "Es el paso 3 del retargeting. Requiere confirmación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "retargeter_path": {"type": "string",
                                "description": "path /Game/... del IKRetargeter"},
            "animations": {
                "description": "'auto' (default) o lista de nombres de AnimSequence del source",
            },
            "target_actor_name": {"type": "string",
                                  "description": "actor del nivel donde reproducir el resultado"},
            "play_first": {"type": "boolean",
                           "description": "reproducir la primera anim retargeteada (requiere target_actor_name)"},
        },
        "required": ["retargeter_path"],
    }
    destructive = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        rtg = (args.get("retargeter_path") or "").strip()
        if not rtg:
            return ToolResult("falta retargeter_path", is_error=True)
        animations = args.get("animations") or "auto"
        if not isinstance(animations, (str, list)):
            return ToolResult("animations debe ser 'auto' o una lista de nombres",
                              is_error=True)
        if isinstance(animations, str) and animations != "auto":
            animations = [animations]
        target_actor = (args.get("target_actor_name") or "").strip() or None
        play_first = bool(args.get("play_first", False))
        if play_first and target_actor is None:
            return ToolResult("play_first requiere target_actor_name", is_error=True)
        ctx.report("RetargetAnims", f"batch sobre {rtg!r}")
        try:
            resp = send_json(ctx.bridge_port, {"script": build_retarget_batch_script(
                rtg, animations, target_actor, play_first)})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge caído: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "fallo en el editor", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"respuesta no parseable:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
        return ToolResult(rendered, is_error=bool(data.get("error")))
```

- [ ] **Step 4:** tests de la tool → 7 passed. **Step 5:** suite → 130 passed.
- [ ] **Step 6: Commit**

```bash
git -C E:/PCW/VERA add vera/agent/tools/retarget_animations.py tests/agent/test_retarget_animations.py
git -C E:/PCW/VERA commit -m "feat(agent): tool retarget_animations (batch idempotente + play opcional, anims movidas a VERA_Retargeted)"
```

---

### Task 5: Suite completa + roadmap

**Files:**
- Modify: `E:/PCW/VERA/PLAN_VERA.md` (sección "Animaciones (roadmap)")

- [ ] **Step 1:** `python -m pytest tests/ -v` — los 130 de `tests/agent/` verdes; fallos preexistentes (perception/manager/python_agent — keys muertas) no bloquean si no tocan archivos de animación/retarget (verificar por grep como en fases anteriores).
- [ ] **Step 2:** En `PLAN_VERA.md`, reemplazar la línea de Fase 3 por:

```markdown
- **Fase 3 (implementada 2026-06-12):** retargeting — tools `ensure_ik_rig`,
  `ensure_retargeter`, `retarget_animations` (find-first, auto-creación). Spec:
  `docs/superpowers/specs/2026-06-12-vera-animation-phase3-retarget-design.md`.
  Pendientes futuros: Sequencer, Control Rig.
```

- [ ] **Step 3: Commit**

```bash
git -C E:/PCW/VERA add PLAN_VERA.md
git -C E:/PCW/VERA commit -m "docs: fase 3 de animaciones implementada en el roadmap"
```

---

### Task 6: E2E vivo (gate de éxito — editor abierto, bridge 9878)

Los 3 checks del spec, ejecutando las tools REALES (driver tipo `scratch/e2e_anim_phase1.py`). NO declarar éxito sin evidencia.

- [ ] **Step 1 — preparación:** spawnear un actor con el mesh UE4 vía bridge:
  `SkeletalMeshActor` con `/Game/TokyoStylizedEnvironment/DemoContent/Characters/Mannequin_UE4/Meshes/SK_Mannequin`, label `VERA_UE4Guy`, sobre el piso del START (z≈27, trace como fase 1). Confirmar con `inspect_actor_animability` que tiene `compatible_anims` pobre o vacío (las anims UE4 del pack pueden existir — anotar el conteo).
- [ ] **Step 2 — Check feliz (pipeline completo):**
  1. `ensure_ik_rig {actor_name: "VERA_UE4Guy"}` → esperado: encuentra `IK_UE4_Mannequin` existente (`created: false`) — el find-first probado contra assets reales.
  2. `ensure_retargeter {source: "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple", target: "VERA_UE4Guy"}` → esperado: encuentra `RTG_UE5Manny_UE4Manny` o crea `RTG_VERA_*` con mapping completo.
  3. `retarget_animations {retargeter_path: <el del paso 2>, animations: ["MF_Unarmed_Jog_Fwd"], target_actor_name: "VERA_UE4Guy", play_first: true}` → crea la anim en `VERA_Retargeted/` y la reproduce.
  4. **`capture_actor {actor_name: "VERA_UE4Guy", animation: "MF_Unarmed_Jog_Fwd_VERA_RTG", frames: 3}`** (ventana visible) → el cerebro DESCRIBE las zancadas — cierre del loop fases 1+2+3.
- [ ] **Step 3 — Check negativo:** `ensure_ik_rig {skeleton_path: "/Game/SteamPunkEnvironment01/Meshes/SK_SteampunkCar02"}` → esperado: `not_characterizable`, sin asset residual (verificar que no quedó `IK_VERA_*` en esa carpeta).
- [ ] **Step 4 — Check idempotencia:** repetir los 3 pasos del check feliz → `created: false` en rig y retargeter, `skipped: [... (ya retargeteada)]` en el batch, cero assets duplicados.
- [ ] **Step 5 — evidencia:** apéndice "E2E Fase 3" en `docs/vera_minigame_run_log.md` (tabla de checks + hallazgos) y commit:

```bash
git -C E:/PCW/VERA add docs/vera_minigame_run_log.md
git -C E:/PCW/VERA commit -m "docs: evidencia E2E fase 3 (retargeting en vivo)"
```

---

## Self-review del plan

- **Cobertura del spec:** 3 tools find-first (Tasks 2-4), auto-creación con borrado en fallo (Task 1 templates), mapping visible (Task 3), batch idempotente + play (Task 4), errores honestos por etapa (tests por rama), Task 0 de probing (COMPLETADA en el planning, hallazgos en el header), E2E con los 3 checks del spec (Task 6). Sin huecos.
- **Sin placeholders:** todo el código completo; las llamadas UE vienen del probing en vivo, no de la doc.
- **Consistencia:** firmas de builders idénticas entre Task 1 (definición) y Tasks 2-4 (uso); claves JSON (`created`, `chain_mapping`, `unmapped_chains`, `created_anims`, `skipped`, `played`, errores `bad_ref`/`missing_ik_rig`/`not_characterizable`/`no_chains_mapped`/`retarget_not_found`) consistentes entre templates, tools y tests; la regla de error (`is_error = bool(data.get("error"))`) es uniforme en las 3 tools.
