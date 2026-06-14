# tests/agent/test_capture_scripts.py
from vera.agent.tools._capture_scripts import (
    build_setup_script,
    build_pose_script,
    build_capture_script,
    build_restore_script,
)


def test_setup_injects_label_and_anim():
    s = build_setup_script('The "Mouse"', "MM_Idle")
    assert '"The \\"Mouse\\""' in s
    assert '"MM_Idle"' in s
    assert "__LABEL__" not in s and "__ANIM__" not in s


def test_setup_without_anim_for_orbit():
    s = build_setup_script("Cube", None)
    assert "anim_req = None" in s


def test_setup_isolates_by_show_only_without_touching_the_level():
    s = build_setup_script("X", None)
    # surgical isolation: SceneCapture show-only list, do NOT hide actors
    assert "show_only_actor_components" in s
    assert "PRM_USE_SHOW_ONLY_LIST" in s
    assert "set_is_temporarily_hidden_in_editor" not in s
    assert "viewmode" not in s
    assert "set_level_viewport_camera_info" not in s


def test_setup_builds_scene_capture_rig():
    s = build_setup_script("X", None)
    assert "SceneCapture2D" in s
    assert "create_render_target2d" in s
    assert "SCS_FINAL_COLOR_LDR" in s       # BASE_COLOR renders useless white (5.7)
    assert "vera_capture_state" in s
    assert "screen_shot_dir" in s
    assert "get_actor_bounds" in s
    assert "indent" not in s                 # compact JSON, one line


def test_setup_reports_no_anims_for_invalid_name():
    s = build_setup_script("X", "Samba_Nonexistent")
    assert '"no_anims"' in s


def test_pose_anim_scrubs_without_capturing():
    # pose and capture go in SEPARATE round-trips: capture_scene in the same
    # call stack would see the previous pose (evaluation happens between ticks)
    s = build_pose_script("anim", 0.75)
    assert "set_position" in s
    assert "0.75" in s
    assert "capture_scene" not in s


def test_pose_orbit_moves_the_rig():
    s = build_pose_script("orbit", 180.0)
    assert "find_look_at_rotation" in s
    assert "180.0" in s
    assert "set_position" in s              # same template, branch by mode


def test_capture_only_captures():
    s = build_capture_script("vera_cap_ab_0.png")
    assert '"vera_cap_ab_0.png"' in s
    assert "capture_scene" in s
    assert "export_render_target" in s
    assert "set_position" not in s
    assert "__FILENAME__" not in s


def test_setup_anim_forces_pose_tick():
    # without ALWAYS_TICK, the skel comps only evaluate pose when rendered
    s = build_setup_script("X", "MM_Idle")
    assert "ALWAYS_TICK_POSE_AND_REFRESH_BONES" in s


def test_restore_idempotent_destroys_the_rig():
    s = build_restore_script()
    assert "sys.modules.pop" in s            # consuming the state = idempotent
    assert "destroy_actor" in s
    assert "set_animation_mode" in s         # returns the actor's previous mode
    assert "visibility_based_anim_tick_option" in s   # reverts the tick option
    assert "__" not in s                     # no pending tokens
