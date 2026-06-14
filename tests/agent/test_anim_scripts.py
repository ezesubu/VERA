# tests/agent/test_anim_scripts.py
from vera.agent.tools._anim_scripts import (
    build_inspect_script,
    build_animate_script,
    build_spawn_script,
    build_stop_script,
    parse_json_output,
    tail_of_output,
)


def test_inspect_script_injects_label_safely():
    s = build_inspect_script('Cyber "Head" 2')
    assert '"Cyber \\"Head\\" 2"' in s     # json.dumps escapes the quotes
    assert "__LABEL__" not in s
    assert "_find_actor" in s and "_diagnose" in s
    assert "indent" not in s               # compact JSON, one line


def test_animate_script_injects_parameters():
    s = build_animate_script("Bot", "MM_Idle", False, True)
    assert '"Bot"' in s and '"MM_Idle"' in s
    assert "looping = False" in s
    assert "allow_procedural = True" in s
    for token in ("__LABEL__", "__ANIM__", "__LOOPING__", "__ALLOW_PROC__"):
        assert token not in s


def test_play_enables_animation_update_in_editor():
    # without this flag the skeletal mesh does not tick in the editor world (UE 5.7)
    assert "set_update_animation_in_editor" in build_animate_script("Bot")
    assert "set_update_animation_in_editor" in build_spawn_script()


def test_spawn_script_with_location():
    s = build_spawn_script("auto", True, [100.0, 200.0, 90.0])
    assert "location = [100.0, 200.0, 90.0]" in s
    assert "SKM_Manny_Simple" in s
    assert "VERA_SPAWNED" in s
    assert "__LOCATION__" not in s


def test_spawn_script_without_location():
    s = build_spawn_script("auto", True, None)
    assert "location = None" in s
    assert "get_level_viewport_camera_info" in s


def test_parse_json_output_tolerates_log_noise():
    out = 'LogPython: noise\nLogTemp: more noise\n{"a": 1}'
    assert parse_json_output(out) == {"a": 1}


def test_parse_json_output_invalid_returns_none():
    assert parse_json_output("no json") is None
    assert parse_json_output("") is None
    assert parse_json_output(None) is None


def test_tail_of_output_bounds_and_tolerates_none():
    assert tail_of_output(None) == ""
    assert tail_of_output("short") == "short"
    assert tail_of_output("a" * 600) == "a" * 500
    assert tail_of_output("abcdef", limit=3) == "def"


def test_stop_script_halts_and_restores():
    s = build_stop_script("Enemy_CyberHead")
    assert '"Enemy_CyberHead"' in s
    assert "vera_proc_anim" in s            # halts the procedural tick
    assert "base_rot" in s                  # restores the original rotation
    assert "ANIMATION_BLUEPRINT" in s       # returns control to the ABP if it exists
    assert "__LABEL__" not in s


def test_animate_procedural_saves_base_rotation():
    # without base_rot the stop cannot restore the original orientation
    assert "base_rot" in build_animate_script("X", allow_procedural=True)


def test_auto_prefers_the_shortest_idle():
    # MM_Idle must beat MF_Pistol_Idle_ADS: order by name length
    assert "key=len" in build_animate_script("X")


def test_spawn_without_location_traces_to_the_floor():
    s = build_spawn_script("auto", True, None)
    assert "line_trace_single" in s
    assert "to_tuple()[4]" in s             # HitResult.location does not exist in 5.7


def test_spawn_uniquifies_the_label():
    # set_actor_label does NOT uniquify in UE: two spawns = two "VERA_Manny" and the
    # later stop/animate points to the wrong one (found live)
    s = build_spawn_script()
    assert "while label in labels" in s


def test_common_exposes_pick_name_separate_from_play():
    # capture_actor needs to resolve the anim BEFORE mutating the level
    s = build_animate_script("X")
    assert "def _pick_name" in s
    assert "_pick_name(info, anim_req)" in s
