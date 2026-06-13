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


def test_los_assets_creados_se_guardan_a_disco():
    # un restart del editor sin save pierde todo lo creado (descubierto en E2E):
    # el find-first entre sesiones depende de assets persistidos
    assert "save_asset" in build_ensure_rig_script("X")
    assert "save_asset" in build_ensure_retargeter_script("A", "B")
    assert "save_asset" in build_retarget_batch_script("/Game/R", "auto", None, False)
