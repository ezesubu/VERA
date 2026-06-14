from vera.agent.loop import AgentLoop
from vera.agent.registry import ToolRegistry
from vera.agent.session import MAX_HISTORY_MESSAGES, AgentSession
from tests.agent.fakes import FakeClient, _Resp, _Text


def test_history_survives_across_commands():
    loop_client = FakeClient([
        _Resp("end_turn", [_Text("cube created")]),
        _Resp("end_turn", [_Text("now it is red")]),
    ])
    s = AgentSession(AgentLoop(ToolRegistry(), loop_client))
    s.run("create a cube")
    s.run("make it red")
    # the second request must carry the full previous turn
    msgs = loop_client.messages.calls[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "create a cube"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[2] == {"role": "user", "content": "make it red"}


def test_inject_adds_a_proactive_turn():
    client = FakeClient([_Resp("end_turn", [_Text("fixed")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    out = s.inject("Compilation error in the log: fix it if it is safe.")
    assert out["status"] == "success"
    assert s.messages[0]["role"] == "user"


def test_run_forwards_should_stop_to_the_loop():
    """AgentSession.run forwards should_stop to loop.run."""

    class _SpyLoop:
        def __init__(self):
            self.kwargs = None

        def run(self, command, emit=None, *, messages=None, confirm=None,
                include_destructive=True, should_stop=None, image=None):
            self.kwargs = {"should_stop": should_stop}
            return {"status": "success", "msg": "ok"}

    loop = _SpyLoop()
    s = AgentSession(loop)
    sentinel = lambda: True  # noqa: E731
    s.run("hi", should_stop=sentinel)
    assert loop.kwargs["should_stop"] is sentinel


def test_run_should_stop_default_none():
    """Without should_stop, AgentSession.run forwards None (backward compat)."""

    class _SpyLoop:
        def __init__(self):
            self.kwargs = None

        def run(self, command, emit=None, *, messages=None, confirm=None,
                include_destructive=True, should_stop=None, image=None):
            self.kwargs = {"should_stop": should_stop}
            return {"status": "success", "msg": "ok"}

    loop = _SpyLoop()
    AgentSession(loop).run("hi")
    assert loop.kwargs["should_stop"] is None


def test_run_forwards_image_to_the_loop():
    """AgentSession.run forwards image to loop.run."""

    class _SpyLoop:
        def __init__(self):
            self.kwargs = None

        def run(self, command, emit=None, *, messages=None, confirm=None,
                include_destructive=True, should_stop=None, image=None):
            self.kwargs = {"image": image}
            return {"status": "success", "msg": "ok"}

    loop = _SpyLoop()
    s = AgentSession(loop)
    img = {"data": "QUJD", "media_type": "image/png"}
    s.run("describe this", image=img)
    assert loop.kwargs["image"] is img


def test_run_image_default_none():
    """Without image, AgentSession.run forwards None (backward compat)."""

    class _SpyLoop:
        def __init__(self):
            self.kwargs = None

        def run(self, command, emit=None, *, messages=None, confirm=None,
                include_destructive=True, should_stop=None, image=None):
            self.kwargs = {"image": image}
            return {"status": "success", "msg": "ok"}

    loop = _SpyLoop()
    AgentSession(loop).run("hi")
    assert loop.kwargs["image"] is None


def test_trim_cuts_on_a_plain_text_user_turn():
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    # synthetic history longer than the maximum, with tool_use/tool_result pairs
    for i in range(MAX_HISTORY_MESSAGES):
        s.messages.append({"role": "user", "content": f"command {i}"})
        s.messages.append({"role": "assistant", "content": [{"type": "tool_use"}]})
        s.messages.append({"role": "user", "content": [{"type": "tool_result"}]})
        s.messages.append({"role": "assistant", "content": [{"type": "text"}]})
    s.run("last command")
    assert len(s.messages) <= MAX_HISTORY_MESSAGES + 2  # +new turn and response
    # never start the history in the middle of a tool_use/tool_result pair
    assert s.messages[0]["role"] == "user"
    assert isinstance(s.messages[0]["content"], str)


def test_trim_can_empty_when_no_plain_user():
    """If no plain-text user turn remains after the cut, the history ends up
    empty and the session keeps working with the new command."""
    client = FakeClient([_Resp("end_turn", [_Text("ok")])])
    s = AgentSession(AgentLoop(ToolRegistry(), client))
    for _ in range(MAX_HISTORY_MESSAGES + 1):
        s.messages.append({"role": "assistant", "content": [{"type": "text", "text": "x"}]})
        s.messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x"}]})
    s.run("new command")
    assert s.messages[0] == {"role": "user", "content": "new command"}
