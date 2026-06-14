# tests/agent/test_retarget_scripts.py
from vera.agent.tools._retarget_scripts import (
    build_ensure_rig_script,
    build_ensure_retargeter_script,
    build_retarget_batch_script,
)


def test_ensure_rig_injects_ref_and_characterizes():
    s = build_ensure_rig_script('The "Mouse"')
    assert '"The \\"Mouse\\""' in s
    assert "apply_auto_generated_retarget_definition" in s
    assert "IKRigDefinitionFactory" in s
    assert "_find_rig_for" in s              # find-first before creating
    assert "__REF__" not in s
    assert "indent" not in s                 # JSON on one line


def test_ensure_rig_deletes_the_asset_if_it_does_not_characterize():
    # a rig with no chains is garbage: if auto-characterize fails, none must remain
    s = build_ensure_rig_script("X")
    assert "delete_asset" in s


def test_ensure_retargeter_has_the_57_piece():
    s = build_ensure_retargeter_script("A", "B")
    assert '"A"' in s and '"B"' in s
    assert "assign_ik_rig_to_all_ops" in s   # without this the mapping ends up empty (tested live)
    assert "auto_map_chains" in s
    assert "get_source_chain" in s
    assert "IKRetargetFactory" in s
    assert "__SRC__" not in s and "__TGT__" not in s


def test_retarget_batch_moves_and_is_idempotent():
    s = build_retarget_batch_script("/Game/R/RTG", ["MM_Idle"], "Bot", True)
    assert '"/Game/R/RTG"' in s
    assert '["MM_Idle"]' in s
    assert "duplicate_and_retarget" in s
    assert "rename_asset" in s               # the batch leaves everything in /Game root
    assert "does_asset_exist" in s           # skip already-retargeted ones
    assert "_VERA_RTG" in s
    assert "play_first = True" in s
    assert "__RTG__" not in s and "__ANIMS__" not in s


def test_retarget_batch_auto_and_no_actor():
    s = build_retarget_batch_script("/Game/R/RTG", "auto", None, False)
    assert '"auto"' in s
    assert "target_actor = None" in s
    assert "play_first = False" in s


def test_shared_helpers_present():
    s = build_ensure_rig_script("X")
    assert "_skeleton_from_ref" in s and "_find_actor" in s
    s2 = build_retarget_batch_script("/Game/R", "auto", None, False)
    assert "_anims_for_skeleton" in s2


def test_created_assets_are_saved_to_disk():
    # an editor restart without save loses everything created (discovered in E2E):
    # cross-session find-first depends on persisted assets
    assert "save_asset" in build_ensure_rig_script("X")
    assert "save_asset" in build_ensure_retargeter_script("A", "B")
    assert "save_asset" in build_retarget_batch_script("/Game/R", "auto", None, False)
