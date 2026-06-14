"""Fake of the OpenAI SDK: duck-types chat.completions.create.

Lets you script responses and capture what was passed to it (model, messages,
tools, tool_choice) to verify the output translation.
"""
from __future__ import annotations

from types import SimpleNamespace


def _msg(content=None, tool_calls=None):
    """Builds a choices[0].message like the OpenAI SDK."""
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def text_response(text):
    """Response without tool_calls (text turn)."""
    return SimpleNamespace(choices=[SimpleNamespace(message=_msg(content=text))])


def tool_call(id, name, arguments):
    """A tool_call like the SDK's (function.name / function.arguments str)."""
    return SimpleNamespace(
        id=id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def tool_response(tool_calls, text=None):
    """Response with one or more tool_calls (tool_use turn)."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=_msg(content=text, tool_calls=list(tool_calls)))]
    )


class _FakeCompletions:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self._scripted.pop(0)


class FakeOpenAI:
    """Mimics openai.OpenAI: exposes .chat.completions.create."""

    def __init__(self, scripted):
        self.chat = SimpleNamespace(completions=_FakeCompletions(scripted))

    @property
    def calls(self):
        return self.chat.completions.calls
