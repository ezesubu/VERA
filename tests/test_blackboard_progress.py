from vera.core.blackboard import Blackboard


def test_report_progress_without_callback_is_noop():
    bb = Blackboard()
    bb.report_progress("Manager", "routing")  # must not raise


def test_report_progress_calls_callback_with_event():
    bb = Blackboard()
    events = []
    bb.progress_callback = events.append
    bb.report_progress("Architect", "plan: 3 steps")
    assert events == [{"type": "progress", "agent": "Architect", "msg": "plan: 3 steps"}]


def test_report_image_emits_image_event():
    bb = Blackboard()
    events = []
    bb.progress_callback = events.append
    bb.report_image("E:/shots/vera_x.png")
    assert events == [{"type": "image", "path": "E:/shots/vera_x.png"}]


def test_broken_callback_does_not_break_agents():
    bb = Blackboard()

    def boom(event):
        raise RuntimeError("ui disconnected")

    bb.progress_callback = boom
    bb.report_progress("QA", "testing")  # must not propagate
