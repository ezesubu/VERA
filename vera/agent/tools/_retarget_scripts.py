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
                # sin save, un restart del editor pierde el asset (E2E vivo):
                # el find-first entre sesiones depende de assets persistidos
                unreal.EditorAssetLibrary.save_asset(rig.get_path_name().rsplit(".", 1)[0])
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
            if created:
                unreal.EditorAssetLibrary.save_asset(rtg.get_path_name().rsplit(".", 1)[0])
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
                unreal.EditorAssetLibrary.save_asset(new)
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
