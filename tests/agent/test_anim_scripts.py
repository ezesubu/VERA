# tests/agent/test_anim_scripts.py
from vera.agent.tools._anim_scripts import (
    build_inspect_script,
    build_animate_script,
    build_spawn_script,
    build_stop_script,
    parse_json_output,
    tail_of_output,
)


def test_inspect_script_inyecta_label_seguro():
    s = build_inspect_script('Cyber "Head" 2')
    assert '"Cyber \\"Head\\" 2"' in s     # json.dumps escapa las comillas
    assert "__LABEL__" not in s
    assert "_find_actor" in s and "_diagnose" in s
    assert "indent" not in s               # JSON compacto, una línea


def test_animate_script_inyecta_parametros():
    s = build_animate_script("Bot", "MM_Idle", False, True)
    assert '"Bot"' in s and '"MM_Idle"' in s
    assert "looping = False" in s
    assert "allow_procedural = True" in s
    for token in ("__LABEL__", "__ANIM__", "__LOOPING__", "__ALLOW_PROC__"):
        assert token not in s


def test_play_habilita_update_de_animacion_en_editor():
    # sin este flag el skeletal mesh no tickea en el mundo del editor (UE 5.7)
    assert "set_update_animation_in_editor" in build_animate_script("Bot")
    assert "set_update_animation_in_editor" in build_spawn_script()


def test_spawn_script_con_location():
    s = build_spawn_script("auto", True, [100.0, 200.0, 90.0])
    assert "location = [100.0, 200.0, 90.0]" in s
    assert "SKM_Manny_Simple" in s
    assert "VERA_SPAWNED" in s
    assert "__LOCATION__" not in s


def test_spawn_script_sin_location():
    s = build_spawn_script("auto", True, None)
    assert "location = None" in s
    assert "get_level_viewport_camera_info" in s


def test_parse_json_output_tolera_ruido_de_log():
    out = 'LogPython: ruido\nLogTemp: mas ruido\n{"a": 1}'
    assert parse_json_output(out) == {"a": 1}


def test_parse_json_output_invalido_devuelve_none():
    assert parse_json_output("sin json") is None
    assert parse_json_output("") is None
    assert parse_json_output(None) is None


def test_tail_of_output_acota_y_tolera_none():
    assert tail_of_output(None) == ""
    assert tail_of_output("corto") == "corto"
    assert tail_of_output("a" * 600) == "a" * 500
    assert tail_of_output("abcdef", limit=3) == "def"


def test_stop_script_detiene_y_restaura():
    s = build_stop_script("Enemy_CyberHead")
    assert '"Enemy_CyberHead"' in s
    assert "vera_proc_anim" in s            # detiene el tick procedural
    assert "base_rot" in s                  # restaura la rotación original
    assert "ANIMATION_BLUEPRINT" in s       # devuelve el control al ABP si existe
    assert "__LABEL__" not in s


def test_animate_procedural_guarda_rotacion_base():
    # sin base_rot el stop no puede restaurar la orientación original
    assert "base_rot" in build_animate_script("X", allow_procedural=True)


def test_auto_prefiere_el_idle_mas_corto():
    # MM_Idle debe ganarle a MF_Pistol_Idle_ADS: orden por longitud de nombre
    assert "key=len" in build_animate_script("X")


def test_spawn_sin_location_tracea_al_piso():
    s = build_spawn_script("auto", True, None)
    assert "line_trace_single" in s
    assert "to_tuple()[4]" in s             # HitResult.location no existe en 5.7


def test_spawn_uniquifica_el_label():
    # set_actor_label NO uniquifica en UE: dos spawns = dos "VERA_Manny" y el
    # stop/animate posterior apunta al equivocado (encontrado en vivo)
    s = build_spawn_script()
    assert "while label in labels" in s
