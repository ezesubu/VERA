# tests/agent/test_anim_scripts.py
from vera.agent.tools._anim_scripts import (
    build_inspect_script,
    build_animate_script,
    build_spawn_script,
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
