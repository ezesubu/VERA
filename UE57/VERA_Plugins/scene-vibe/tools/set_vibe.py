"""set_vibe — instantly set the cinematic MOOD of the open level.

Spawns (or reuses) a tagged DirectionalLight + an unbound PostProcessVolume and
applies curated per-mood color grading / exposure / bloom / vignette + a matching
directional light (color, intensity, rotation). Everything is tagged so clear_vibe
can remove it later, and the tool is idempotent: repeated calls reuse the same two
actors instead of stacking new ones.

The heavy lifting runs as a curated UE python script through the bridge — the model
does not have to write any `unreal` code. Every risky `unreal` call is wrapped in
try/except so an unavailable property degrades gracefully and the rest still applies.
"""
from __future__ import annotations

from vera.agent.tool import Tool, ToolContext, ToolResult
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

MOODS = ["cyberpunk", "horror", "golden_hour", "noir", "aztec_dusk"]

# ---------------------------------------------------------------------------
# Curated UE python. {MOOD} is substituted with the validated mood string.
# Main-thread safe (runs in the bridge's editor tick), never crashes: every
# `unreal` touch is guarded and a JSON summary is always printed.
# ---------------------------------------------------------------------------
_SCRIPT_TEMPLATE = r'''
import unreal, json

MOOD = "{MOOD}"
TAG = "VERA_Vibe"
LABEL_PREFIX = "VERA_Vibe_"

applied = []   # human-readable list of what we managed to set
warnings = []  # non-fatal problems

def _safe(fn, desc):
    """Run fn(); record success/failure without ever raising."""
    try:
        fn()
        applied.append(desc)
        return True
    except Exception as e:
        warnings.append("%s: %s" % (desc, e))
        return False

def _C(r, g, b, a=1.0):
    # LinearColor helper (color grading + light color + tint live in 0..1+).
    try:
        return unreal.LinearColor(r, g, b, a)
    except Exception:
        return None

def _V4(r, g, b, lum):
    # Vector4 for split-tone color-grading channels (shadows/midtones/highlights).
    try:
        return unreal.Vector4(r, g, b, lum)
    except Exception:
        return None

# ---- Per-mood recipe -------------------------------------------------------
# pp:    dict of PostProcessSettings property -> (value, override_flag_name)
# light: dict with color (LinearColor), intensity (lux), pitch/yaw (degrees)
def _recipe(mood):
    if mood == "cyberpunk":
        return {
            "pp": {
                "color_saturation":  (_V4(1.15, 1.10, 1.30, 1.0), "override_color_saturation"),
                "color_contrast":    (_V4(1.15, 1.10, 1.20, 1.0), "override_color_contrast"),
                "color_gain":        (_V4(0.85, 0.95, 1.20, 1.0), "override_color_gain"),
                "color_shadows":     (_V4(0.70, 0.95, 1.30, 0.95), "override_color_shadows"),
                "color_highlights":  (_V4(1.30, 0.85, 1.20, 1.05), "override_color_highlights"),
                "bloom_intensity":   (1.6, "override_bloom_intensity"),
                "vignette_intensity":(0.45, "override_vignette_intensity"),
                "auto_exposure_bias":(0.2, "override_auto_exposure_bias"),
                "film_grain_intensity": (0.18, "override_film_grain_intensity"),
            },
            "light": {"color": _C(0.55, 0.75, 1.0), "intensity": 1.5, "pitch": -28.0, "yaw": 135.0},
        }
    if mood == "horror":
        return {
            "pp": {
                "color_saturation":  (_V4(0.45, 0.50, 0.55, 1.0), "override_color_saturation"),
                "color_contrast":    (_V4(1.20, 1.20, 1.25, 1.0), "override_color_contrast"),
                "color_gain":        (_V4(0.55, 0.60, 0.70, 1.0), "override_color_gain"),
                "color_shadows":     (_V4(0.60, 0.70, 0.95, 0.85), "override_color_shadows"),
                "bloom_intensity":   (0.2, "override_bloom_intensity"),
                "vignette_intensity":(0.85, "override_vignette_intensity"),
                "auto_exposure_bias":(-1.6, "override_auto_exposure_bias"),
                "film_grain_intensity": (0.35, "override_film_grain_intensity"),
            },
            "light": {"color": _C(0.45, 0.18, 0.18), "intensity": 0.6, "pitch": -15.0, "yaw": 200.0},
        }
    if mood == "golden_hour":
        return {
            "pp": {
                "color_saturation":  (_V4(1.10, 1.05, 0.95, 1.0), "override_color_saturation"),
                "color_contrast":    (_V4(1.05, 1.02, 1.00, 1.0), "override_color_contrast"),
                "color_gain":        (_V4(1.15, 1.05, 0.85, 1.0), "override_color_gain"),
                "color_highlights":  (_V4(1.20, 1.05, 0.80, 1.05), "override_color_highlights"),
                "bloom_intensity":   (0.9, "override_bloom_intensity"),
                "vignette_intensity":(0.25, "override_vignette_intensity"),
                "auto_exposure_bias":(0.3, "override_auto_exposure_bias"),
            },
            "light": {"color": _C(1.0, 0.72, 0.40), "intensity": 4.5, "pitch": -6.0, "yaw": 110.0},
        }
    if mood == "noir":
        return {
            "pp": {
                "color_saturation":  (_V4(0.12, 0.12, 0.12, 1.0), "override_color_saturation"),
                "color_contrast":    (_V4(1.35, 1.35, 1.35, 1.0), "override_color_contrast"),
                "color_gain":        (_V4(1.0, 1.0, 1.0, 1.0), "override_color_gain"),
                "bloom_intensity":   (0.3, "override_bloom_intensity"),
                "vignette_intensity":(0.80, "override_vignette_intensity"),
                "auto_exposure_bias":(0.0, "override_auto_exposure_bias"),
                "film_grain_intensity": (0.25, "override_film_grain_intensity"),
            },
            "light": {"color": _C(1.0, 1.0, 1.0), "intensity": 5.0, "pitch": -35.0, "yaw": 60.0},
        }
    if mood == "aztec_dusk":
        return {
            "pp": {
                "color_saturation":  (_V4(1.20, 1.10, 1.10, 1.0), "override_color_saturation"),
                "color_contrast":    (_V4(1.10, 1.08, 1.12, 1.0), "override_color_contrast"),
                "color_gain":        (_V4(1.10, 0.85, 0.95, 1.0), "override_color_gain"),
                "color_shadows":     (_V4(0.75, 0.60, 1.05, 0.90), "override_color_shadows"),
                "color_highlights":  (_V4(1.30, 0.95, 0.65, 1.05), "override_color_highlights"),
                "bloom_intensity":   (1.1, "override_bloom_intensity"),
                "vignette_intensity":(0.40, "override_vignette_intensity"),
                "auto_exposure_bias":(0.0, "override_auto_exposure_bias"),
            },
            "light": {"color": _C(1.0, 0.55, 0.30), "intensity": 3.0, "pitch": -8.0, "yaw": 160.0},
        }
    return None

def _find_tagged(eas, class_name):
    """First level actor carrying our TAG and matching class_name, else None."""
    try:
        actors = eas.get_all_level_actors()
    except Exception:
        return None
    for a in actors:
        try:
            if not a.actor_has_tag(TAG):
                continue
            if a.get_class().get_name() == class_name:
                return a
        except Exception:
            continue
    return None

def _tag_and_label(actor, suffix):
    def _do_tag():
        actor.tags = [unreal.Name(TAG)]
    _safe(_do_tag, "tag actor as %s" % TAG)
    def _do_label():
        actor.set_actor_label(LABEL_PREFIX + suffix)
    _safe(_do_label, "label actor %s%s" % (LABEL_PREFIX, suffix))

def main():
    recipe = _recipe(MOOD)
    if recipe is None:
        print(json.dumps({"success": False, "error": "unknown mood: %s" % MOOD}))
        return

    try:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    except Exception as e:
        print(json.dumps({"success": False, "error": "EditorActorSubsystem unavailable: %s" % e}))
        return

    # ---- DirectionalLight (reuse or spawn) --------------------------------
    light = _find_tagged(eas, "DirectionalLight")
    light_reused = light is not None
    if light is None:
        try:
            light = eas.spawn_actor_from_class(
                unreal.DirectionalLight, unreal.Vector(0, 0, 1000), unreal.Rotator(0, 0, 0))
        except Exception as e:
            warnings.append("spawn DirectionalLight: %s" % e)
            light = None
    if light is not None:
        if not light_reused:
            _tag_and_label(light, "DirectionalLight")
        spec = recipe["light"]
        # Rotation drives sun direction (pitch low on horizon for warm moods).
        def _rot():
            light.set_actor_rotation(
                unreal.Rotator(spec["pitch"], spec["yaw"], 0.0), False)
        _safe(_rot, "directional light rotation (pitch=%.0f yaw=%.0f)" % (spec["pitch"], spec["yaw"]))
        # The light component holds color + intensity.
        comp = None
        for getter in ("light_component", "directional_light_component"):
            try:
                comp = getattr(light, getter)
                if comp is not None:
                    break
            except Exception:
                comp = None
        if comp is None:
            try:
                comp = light.get_component_by_class(unreal.DirectionalLightComponent)
            except Exception:
                comp = None
        if comp is not None:
            if spec["color"] is not None:
                _safe(lambda: comp.set_light_color(spec["color"]), "directional light color")
            def _intensity():
                comp.set_editor_property("intensity", float(spec["intensity"]))
            _safe(_intensity, "directional light intensity (%.2f)" % spec["intensity"])
        else:
            warnings.append("directional light component not reachable")

    # ---- Unbound PostProcessVolume (reuse or spawn) -----------------------
    ppv = _find_tagged(eas, "PostProcessVolume")
    ppv_reused = ppv is not None
    if ppv is None:
        try:
            ppv = eas.spawn_actor_from_class(
                unreal.PostProcessVolume, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        except Exception as e:
            warnings.append("spawn PostProcessVolume: %s" % e)
            ppv = None
    if ppv is not None:
        if not ppv_reused:
            _tag_and_label(ppv, "PostProcess")
        # Make it affect the whole level regardless of camera position.
        _safe(lambda: ppv.set_editor_property("unbound", True), "post-process unbound=True")
        _safe(lambda: ppv.set_editor_property("priority", 1000.0), "post-process priority")

        # Build a fresh PostProcessSettings, set overrides, assign back.
        try:
            settings = ppv.get_editor_property("settings")
        except Exception as e:
            settings = None
            warnings.append("read post-process settings: %s" % e)
        if settings is not None:
            for prop, (val, flag) in recipe["pp"].items():
                if val is None:
                    warnings.append("skip %s (unsupported value type on this build)" % prop)
                    continue
                # Enable the override flag, then set the property; guard each.
                _safe(lambda f=flag: settings.set_editor_property(f, True),
                      "enable %s" % flag)
                _safe(lambda p=prop, v=val: settings.set_editor_property(p, v),
                      "set %s" % prop)
            _safe(lambda: ppv.set_editor_property("settings", settings),
                  "assign post-process settings")

    # ---- Summary ----------------------------------------------------------
    out = {
        "success": True,
        "mood": MOOD,
        "directional_light": ("reused" if light_reused else "spawned") if light is not None else "FAILED",
        "post_process_volume": ("reused" if ppv_reused else "spawned") if ppv is not None else "FAILED",
        "applied_count": len(applied),
        "applied": applied,
    }
    if warnings:
        out["warnings"] = warnings
    print(json.dumps(out, indent=2))

try:
    main()
except Exception as e:
    # Absolute last-resort guard: never let the bridge see a traceback as failure.
    print(json.dumps({"success": False, "error": "unexpected: %s" % e,
                      "applied": applied, "warnings": warnings}))
'''


def _build_script(mood: str) -> str:
    return _SCRIPT_TEMPLATE.replace("{MOOD}", mood)


class SetVibeTool(Tool):
    name = "set_vibe"
    description = (
        "Instantly set the cinematic MOOD of the level currently open in the Unreal editor "
        "for a showcase screenshot or demo recording. Spawns (or reuses) a tagged "
        "DirectionalLight + an unbound PostProcessVolume and applies a curated look — color "
        "grading, exposure, bloom and vignette — plus a matching sun color/intensity/angle. "
        "Moods: 'cyberpunk' (cool teal shadows + magenta highlights, high contrast, bloom), "
        "'horror' (very dark, desaturated, cold, heavy vignette), 'golden_hour' (warm low sun, "
        "soft bloom), 'noir' (near-monochrome, high contrast, hard white key light), "
        "'aztec_dusk' (warm amber + purple split-tone, atmospheric). Idempotent — repeated "
        "calls reuse the same two actors instead of stacking. USE THIS right before capturing "
        "a beauty shot; call clear_vibe afterwards to restore the level."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "mood": {
                "type": "string",
                "enum": MOODS,
                "description": "The cinematic mood to apply to the open level.",
            }
        },
        "required": ["mood"],
    }
    destructive = True  # modifies the level, but reversible via clear_vibe

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        mood = (args or {}).get("mood")
        if mood not in MOODS:
            return ToolResult(
                f"Invalid mood {mood!r}. Choose one of: {', '.join(MOODS)}.",
                is_error=True,
            )
        ctx.report("SceneVibe", f"setting the '{mood}' vibe on the open level")
        script = _build_script(mood)
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"Could not reach the Unreal editor: {e}", is_error=True)
        if resp.get("success"):
            return ToolResult(resp.get("output") or f"Applied '{mood}' vibe.")
        return ToolResult(resp.get("error") or "editor script failed", is_error=True)
