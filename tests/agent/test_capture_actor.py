# tests/agent/test_capture_actor.py
import json
import re

from vera.agent.tool import ToolContext
from vera.agent.tools.capture_actor import CaptureActorTool
import vera.agent.tools.capture_actor as mod
from vera.tools.ue_conn import UEConnectionError


def _setup_payload(tmp_path, **over):
    d = {"actor": "VERA_Manny", "isolation": "show_only_list",
         "screenshot_dir": str(tmp_path), "animation": "MM_Idle",
         "anim_length": 2.0}
    d.update(over)
    return d


class FakeBridge:
    """Simulates the editor: discriminates setup/frame/restore by script
    markers, writes the PNG when it sees a frame, and records the order."""

    def __init__(self, tmp_path, setup=None, frame_fail_at=None,
                 write_files=True, restore=None):
        self.tmp = tmp_path
        self.setup = setup if setup is not None else _setup_payload(tmp_path)
        self.frame_fail_at = frame_fail_at
        self.write_files = write_files
        self.restore = restore or {"restored": True, "unhidden": 3, "errors": []}
        self.scripts = []
        self.frame_count = 0

    def __call__(self, port, payload, *a, **k):
        s = payload["script"]
        self.scripts.append(s)
        if "sys.modules.pop" in s:                      # restore
            return {"success": True, "output": json.dumps(self.restore)}
        if "capture_scene" in s:                        # capture (2nd round-trip)
            self.frame_count += 1
            if self.frame_fail_at == self.frame_count:
                return {"success": False, "error": "boom in the frame"}
            m = re.search(r"vera_cap_[0-9a-f]+_\d+\.png", s)
            if self.write_files and m:
                (self.tmp / m.group(0)).write_bytes(b"PNGDATA")
            return {"success": True, "output": json.dumps({"ok": True})}
        if "set_position" in s:                         # pose (1st round-trip)
            return {"success": True, "output": json.dumps({"ok": True})}
        return {"success": True, "output": json.dumps(self.setup)}   # setup

    @property
    def kinds(self):
        out = []
        for s in self.scripts:
            if "sys.modules.pop" in s:
                out.append("restore")
            elif "capture_scene" in s:
                out.append("capture")
            elif "set_position" in s:
                out.append("pose")
            else:
                out.append("setup")
        return out


def _fast(monkeypatch):
    monkeypatch.setattr(mod, "POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(mod, "FILE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(mod, "POSE_SETTLE_S", 0.0)


def test_is_read_only():
    assert CaptureActorTool().destructive is False


def test_orbit_happy(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "VERA_Manny", "frames": 2}, ToolContext())
    assert res.is_error is False
    assert bridge.kinds == ["setup", "pose", "capture", "pose", "capture", "restore"]
    assert isinstance(res.content, list)
    meta = json.loads(res.content[0]["text"])
    assert meta["mode"] == "orbit"
    assert meta["angles"] == [0.0, 180.0]
    assert meta["restored"] is True
    images = [b for b in res.content if b.get("type") == "image"]
    assert len(images) == 2


def test_anim_happy_computes_times(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "VERA_Manny", "animation": "auto", "frames": 4},
        ToolContext())
    assert res.is_error is False
    meta = json.loads(res.content[0]["text"])
    assert meta["mode"] == "anim"                 # inferred from animation
    assert meta["times"] == [0.25, 0.75, 1.25, 1.75]
    assert meta["animation"] == "MM_Idle"


def test_anim_length_zero_is_error(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, setup=_setup_payload(tmp_path, anim_length=0.0))
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "animation": "auto"}, ToolContext())
    assert res.is_error is True
    assert bridge.kinds[-1] == "restore"          # setup ALREADY mutated: restore anyway


def test_orbit_rejects_animation(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "mode": "orbit", "animation": "MM_Idle"},
        ToolContext())
    assert res.is_error is True


def test_validations_without_bridge(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the bridge")
    monkeypatch.setattr(mod, "send_json", boom)
    t = CaptureActorTool()
    assert t.execute({"actor_name": "  "}, ToolContext()).is_error
    assert t.execute({"actor_name": "X", "frames": 0}, ToolContext()).is_error
    assert t.execute({"actor_name": "X", "frames": 7}, ToolContext()).is_error
    assert t.execute({"actor_name": "X", "mode": "spin"}, ToolContext()).is_error


def test_not_found_does_not_mutate_or_restore(monkeypatch, tmp_path):
    bridge = FakeBridge(tmp_path, setup={"error": "not_found", "actor": "Nothing",
                                         "candidates": ["Goal"]})
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute({"actor_name": "Nothing"}, ToolContext())
    assert res.is_error is True
    assert bridge.kinds == ["setup"]              # no frames and NO restore


def test_not_skeletal_is_a_clear_error(monkeypatch, tmp_path):
    bridge = FakeBridge(tmp_path, setup={"error": "not_skeletal",
                                         "kind": "static", "hint": "use mode=orbit"})
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "CyberHead", "animation": "auto"}, ToolContext())
    assert res.is_error is True
    assert "orbit" in res.content


def test_frame_fails_but_restore_travels(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, frame_fail_at=1)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 3}, ToolContext())
    assert res.is_error is True                   # 0 images
    assert bridge.kinds[-1] == "restore"          # the finally sent it anyway


def test_partial_returns_what_was_captured_with_warning(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, frame_fail_at=2)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 2}, ToolContext())
    assert res.is_error is False                  # there is 1 useful frame
    meta = json.loads(res.content[0]["text"])
    assert meta["frames_captured"] == 1
    assert meta["warnings"]
    assert meta["restored"] is True


def test_png_timeout_restores_and_fails(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, write_files=False)
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 1}, ToolContext())
    assert res.is_error is True
    assert bridge.kinds[-1] == "restore"


def test_failed_restore_is_reported(monkeypatch, tmp_path):
    _fast(monkeypatch)
    bridge = FakeBridge(tmp_path, restore={"restored": False,
                                           "unhidden": 1, "errors": ["x"]})
    monkeypatch.setattr(mod, "send_json", bridge)
    res = CaptureActorTool().execute(
        {"actor_name": "X", "frames": 1}, ToolContext())
    assert res.is_error is False                  # the captures are still useful
    meta = json.loads(res.content[0]["text"])
    assert meta["restored"] is False
    assert "restore_detail" in meta


def test_bridge_down_in_setup(monkeypatch):
    def boom(*a, **k):
        raise UEConnectionError("editor closed")
    monkeypatch.setattr(mod, "send_json", boom)
    res = CaptureActorTool().execute({"actor_name": "X"}, ToolContext())
    assert res.is_error is True
    assert "editor closed" in res.content
