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


def test_setup_reporta_no_anims_para_nombre_invalido():
    # rama observable del refactor _pick_name: nombre explícito no compatible
    s = build_setup_script("X", "Samba_Inexistente")
    assert '"no_anims"' in s


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


def test_setup_copia_la_camara_no_referencias():
    # structs de UE pueden ser referencias vivas: el restore necesita copias
    s = build_setup_script("X", None)
    assert "unreal.Vector(cam_loc.x" in s
    assert "unreal.Rotator(roll=cam_rot.roll" in s
