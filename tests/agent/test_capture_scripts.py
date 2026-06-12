# tests/agent/test_capture_scripts.py
from vera.agent.tools._capture_scripts import (
    build_setup_script,
    build_pose_script,
    build_capture_script,
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


def test_setup_aisla_por_show_only_sin_tocar_el_nivel():
    s = build_setup_script("X", None)
    # aislamiento quirúrgico: lista show-only del SceneCapture, NO ocultar actores
    assert "show_only_actor_components" in s
    assert "PRM_USE_SHOW_ONLY_LIST" in s
    assert "set_is_temporarily_hidden_in_editor" not in s
    assert "viewmode" not in s
    assert "set_level_viewport_camera_info" not in s


def test_setup_arma_rig_de_scene_capture():
    s = build_setup_script("X", None)
    assert "SceneCapture2D" in s
    assert "create_render_target2d" in s
    assert "SCS_FINAL_COLOR_LDR" in s       # BASE_COLOR da blanco inútil (5.7)
    assert "vera_capture_state" in s
    assert "screen_shot_dir" in s
    assert "get_actor_bounds" in s
    assert "indent" not in s                 # JSON compacto, una línea


def test_setup_reporta_no_anims_para_nombre_invalido():
    s = build_setup_script("X", "Samba_Inexistente")
    assert '"no_anims"' in s


def test_pose_anim_scrubea_sin_capturar():
    # pose y captura van en round-trips SEPARADOS: capture_scene en el mismo
    # call stack veria la pose anterior (la evaluacion ocurre entre ticks)
    s = build_pose_script("anim", 0.75)
    assert "set_position" in s
    assert "0.75" in s
    assert "capture_scene" not in s


def test_pose_orbit_mueve_el_rig():
    s = build_pose_script("orbit", 180.0)
    assert "find_look_at_rotation" in s
    assert "180.0" in s
    assert "set_position" in s              # mismo template, rama por modo


def test_capture_solo_captura():
    s = build_capture_script("vera_cap_ab_0.png")
    assert '"vera_cap_ab_0.png"' in s
    assert "capture_scene" in s
    assert "export_render_target" in s
    assert "set_position" not in s
    assert "__FILENAME__" not in s


def test_setup_anim_fuerza_tick_de_pose():
    # sin ALWAYS_TICK, los skel comps solo evaluan pose cuando son renderizados
    s = build_setup_script("X", "MM_Idle")
    assert "ALWAYS_TICK_POSE_AND_REFRESH_BONES" in s


def test_restore_idempotente_destruye_el_rig():
    s = build_restore_script()
    assert "sys.modules.pop" in s            # consumir el estado = idempotente
    assert "destroy_actor" in s
    assert "set_animation_mode" in s         # devuelve el modo previo del actor
    assert "visibility_based_anim_tick_option" in s   # revierte el tick option
    assert "__" not in s                     # sin tokens pendientes
