# vera/agent/tools/capture_actor.py
"""Visual perception (read-only): the brain SEES an isolated actor.

"A on the outside, C on the inside": a single call with guaranteed restore;
inside, separate setup/frame/restore scripts orchestrated here. The restore runs
in a client-side finally: even if a frame fails, the level returns to its state.
Capture via SceneCapture2D (render on demand, works with the editor minimized);
isolation via show-only list — the level is not touched.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

from vera.agent.tool import Tool, ToolContext, ToolResult, image_block
from vera.agent.tools._anim_scripts import parse_json_output, tail_of_output
from vera.agent.tools._capture_scripts import (
    build_setup_script, build_pose_script, build_capture_script,
    build_restore_script)
from vera.tools.ue_conn import send_json, UEConnectionError, UETimeoutError

MAX_FRAMES = 6
FILE_TIMEOUT_S = 15.0
POLL_INTERVAL_S = 0.3
# after the scrub, the editor needs to tick (~60fps visible) to evaluate the
# pose BEFORE capturing; without this wait the capture sees the previous pose
POSE_SETTLE_S = 0.25


class CaptureActorTool(Tool):
    name = "capture_actor"
    description = (
        "Visual perception (read-only): isolates a level actor (hides the "
        "rest, neutral background) and captures N frames at 640x360 that come back "
        "to you as images — use it to SEE an actor or judge an animation. "
        "mode=anim scrubs an animation across N times (requires skeletal); "
        "mode=orbit circles it across N angles (any actor). Restores the level "
        "automatically when done."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "actor_name": {
                "type": "string",
                "description": "actor label (exact or partial match)",
            },
            "mode": {
                "type": "string", "enum": ["anim", "orbit"],
                "description": "default: anim if animation is given, otherwise orbit",
            },
            "animation": {
                "type": "string",
                "description": "mode=anim only: 'auto' or AnimSequence name",
            },
            "frames": {
                "type": "integer", "minimum": 1, "maximum": 6,
                "description": "number of captures (default 4)",
            },
        },
        "required": ["actor_name"],
    }
    destructive = False

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        actor_name = (args.get("actor_name") or "").strip()
        if not actor_name:
            return ToolResult("missing actor_name (actor label)", is_error=True)
        try:
            frames = int(args.get("frames", 4))
        except (TypeError, ValueError):
            return ToolResult("frames must be an integer between 1 and 6", is_error=True)
        if not 1 <= frames <= MAX_FRAMES:
            return ToolResult("frames must be between 1 and 6", is_error=True)
        animation = args.get("animation")
        mode = args.get("mode") or ("anim" if animation else "orbit")
        if mode not in ("anim", "orbit"):
            return ToolResult(f"invalid mode: {mode!r} (anim|orbit)", is_error=True)
        if mode == "orbit" and animation:
            return ToolResult("animation only applies to mode=anim", is_error=True)
        if mode == "anim" and not animation:
            animation = "auto"

        ctx.report("CaptureActor", f"isolating {actor_name!r} ({mode}, {frames} frames)")
        setup = self._send(ctx, build_setup_script(
            actor_name, animation if mode == "anim" else None))
        if isinstance(setup, ToolResult):
            return setup
        if setup.get("error"):
            # setup errors happen BEFORE mutating the level: no restore
            return ToolResult(
                json.dumps(setup, ensure_ascii=False, sort_keys=True), is_error=True)

        warnings = []
        if mode == "anim":
            length = float(setup.get("anim_length") or 0.0)
            if length <= 0.0:
                # setup ALREADY mutated the level: we must go through restore anyway
                values = []
                warnings.append(
                    f"invalid anim_length ({length}): nothing to scrub")
            else:
                values = [round((i + 0.5) / frames * length, 3)
                          for i in range(frames)]
        else:
            values = [round(360.0 * i / frames, 1) for i in range(frames)]

        nonce = uuid.uuid4().hex[:8]
        shot_dir = setup.get("screenshot_dir") or ""
        files, images = [], []
        try:
            for i, value in enumerate(values):
                fname = f"vera_cap_{nonce}_{i}.png"
                ctx.report("CaptureActor", f"frame {i + 1}/{len(values)}")
                # pose and capture in separate round-trips: the editor evaluates
                # the pose between messages; capturing in the same call stack would
                # see the previous pose (off-by-one, found in live E2E)
                pose = self._send(ctx, build_pose_script(mode, value))
                if isinstance(pose, ToolResult):
                    warnings.append(f"frame {i} (pose): {pose.content}")
                    break
                if pose.get("error"):
                    warnings.append(f"frame {i} (pose): {pose['error']}")
                    break
                if mode == "anim":
                    time.sleep(POSE_SETTLE_S)
                frame = self._send(ctx, build_capture_script(fname))
                if isinstance(frame, ToolResult):
                    warnings.append(f"frame {i}: {frame.content}")
                    break
                if frame.get("error"):
                    warnings.append(f"frame {i}: {frame['error']}")
                    break
                path = os.path.join(shot_dir, fname)
                data = self._wait_for_file(path)
                if data is None:
                    warnings.append(f"frame {i}: timeout waiting for {fname}")
                    break
                files.append(path)
                images.append(image_block(base64.b64encode(data).decode("ascii")))
                # Surface the shot in the VERA chat too (the model already gets the
                # base64; this lets the USER see each frame inline as it's captured).
                if ctx.emit:
                    ctx.emit({"type": "image", "path": path})
        finally:
            restore_info = self._restore(ctx)

        meta = {
            "actor": setup.get("actor"), "mode": mode,
            "frames_captured": len(images), "files": files,
            "isolation": setup.get("isolation"),
            "restored": bool(restore_info.get("restored")),
        }
        if mode == "anim":
            meta["animation"] = setup.get("animation")
            meta["anim_length"] = setup.get("anim_length")
            meta["times"] = values[: len(images)]
        else:
            meta["angles"] = values[: len(images)]
        if warnings:
            meta["warnings"] = warnings
        if not restore_info.get("restored"):
            meta["restore_detail"] = restore_info

        text = json.dumps(meta, ensure_ascii=False, sort_keys=True)
        if not images:
            return ToolResult(text, is_error=True)
        return ToolResult([{"type": "text", "text": text}] + images)

    # ---- helpers ----

    def _send(self, ctx: ToolContext, script: str):
        """One round-trip over the bridge: parsed dict or an error ToolResult."""
        try:
            resp = send_json(ctx.bridge_port, {"script": script})
        except (UEConnectionError, UETimeoutError) as e:
            return ToolResult(f"bridge down: {e}", is_error=True)
        if not resp.get("success"):
            return ToolResult(resp.get("error") or "editor failure", is_error=True)
        data = parse_json_output(resp.get("output"))
        if data is None:
            return ToolResult(
                f"unparseable response:\n{tail_of_output(resp.get('output'))}",
                is_error=True)
        return data

    def _restore(self, ctx: ToolContext) -> dict:
        """Best-effort and never raises: the finally must not mask the real error."""
        try:
            data = self._send(ctx, build_restore_script())
        except Exception as e:  # noqa: BLE001
            return {"restored": False, "reason": str(e)}
        if isinstance(data, ToolResult):
            return {"restored": False, "reason": str(data.content)}
        if data.get("reason") == "no_state":
            # setup never got to mutate: there was nothing to restore
            return {"restored": True, "reason": "no_state"}
        return data

    def _wait_for_file(self, path: str, timeout=None, interval=None):
        """Waits for the PNG to exist with a stable size. bytes or None.
        Reads the module limits at runtime so tests can shrink them."""
        timeout = FILE_TIMEOUT_S if timeout is None else timeout
        interval = POLL_INTERVAL_S if interval is None else interval
        deadline = time.monotonic() + timeout
        last = -1
        while time.monotonic() < deadline:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            if size > 0 and size == last:
                with open(path, "rb") as f:
                    return f.read()
            last = size
            time.sleep(interval)
        return None
