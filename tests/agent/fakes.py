"""Fakes que imitan la forma streaming del SDK de Anthropic, compartidos por los tests."""


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUse:
    type = "tool_use"

    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _ThinkingDelta:
    type = "thinking_delta"

    def __init__(self, thinking):
        self.thinking = thinking


class _StreamEvent:
    type = "content_block_delta"

    def __init__(self, delta):
        self.delta = delta


def thinking_event(text):
    return _StreamEvent(_ThinkingDelta(text))


class _FakeStream:
    """Context manager que itera eventos y devuelve el mensaje final."""

    def __init__(self, resp, events=()):
        self._resp = resp
        self._events = list(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._resp


class _FakeMessages:
    """Cada entrada de `scripted` es un _Resp o una tupla (_Resp, [eventos])."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        item = self._scripted.pop(0)
        resp, events = item if isinstance(item, tuple) else (item, ())
        return _FakeStream(resp, events)


class FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)
