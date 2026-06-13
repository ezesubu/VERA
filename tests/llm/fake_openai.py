"""Fake del SDK de OpenAI: duck-typea chat.completions.create.

Permite scriptar respuestas y capturar lo que se le pasó (model, messages,
tools, tool_choice) para verificar la traducción de salida.
"""
from __future__ import annotations

from types import SimpleNamespace


def _msg(content=None, tool_calls=None):
    """Construye un choices[0].message como el SDK de OpenAI."""
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def text_response(text):
    """Respuesta sin tool_calls (turno de texto)."""
    return SimpleNamespace(choices=[SimpleNamespace(message=_msg(content=text))])


def tool_call(id, name, arguments):
    """Un tool_call como el del SDK (function.name / function.arguments str)."""
    return SimpleNamespace(
        id=id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def tool_response(tool_calls, text=None):
    """Respuesta con uno o más tool_calls (turno tool_use)."""
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
    """Imita openai.OpenAI: expone .chat.completions.create."""

    def __init__(self, scripted):
        self.chat = SimpleNamespace(completions=_FakeCompletions(scripted))

    @property
    def calls(self):
        return self.chat.completions.calls
