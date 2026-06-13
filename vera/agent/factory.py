"""Construcción del AgentLoop de producción y selección de cliente LLM."""
from __future__ import annotations

import logging
import os
from typing import Optional

from vera.agent.loop import AgentLoop, DEFAULT_MODEL

logger = logging.getLogger(__name__)
from vera.agent.models import PROVIDERS
from vera.agent.registry import ToolRegistry

SYSTEM_PROMPT = (
    "You are VERA, an autonomous Unreal Engine technical engineer. "
    "You work inside the user's editor through tools. "
    "Plan your approach, use the tools you need, verify the results, "
    "and fix things if something fails. For any operation without a dedicated "
    "tool, write code with `run_ue_python` (the `unreal` module is available; "
    "use print() to return data). Be concise in your final answer."
)

# Short prompt for small local models (LM Studio). Same identity + the load-bearing
# rules, none of the long verbiage. Plugin skills are still appended on top.
COMPACT_SYSTEM_PROMPT = (
    "You are VERA, an autonomous Unreal Engine technical agent working inside the "
    "user's editor via tools. Use the tools, verify the result, fix on failure. "
    "For anything without a dedicated tool, write Python with `run_ue_python` "
    "(the `unreal` module is available; print() to return data). Be concise."
)

DEFAULT_PROVIDER = "ANTHROPIC"


def _default_plugins_dir() -> str:
    """Resolve the plugins directory. Order: env VERA_PLUGINS_DIR, else
    <UE project root>/VERA_Plugins (root from env VERA_PROJECT_ROOT, default
    E:/PCW/VERA/UE57)."""
    explicit = os.environ.get("VERA_PLUGINS_DIR")
    if explicit:
        return explicit
    root = os.environ.get("VERA_PROJECT_ROOT", "E:/PCW/VERA/UE57")
    return os.path.join(root, "VERA_Plugins")


PLUGINS_DIR = _default_plugins_dir()


def _build_system_prompt(base: str, enabled_plugins) -> str:
    """Append a '## Studio plugins / skills' section with each enabled plugin's
    SKILL.md, when present."""
    skills = [(p.name, p.skill_text) for p in enabled_plugins if p.skill_text]
    if not skills:
        return base
    parts = [base, "", "## Studio plugins / skills"]
    for name, text in skills:
        parts.append(f"\n### {name}\n{text.strip()}")
    return "\n".join(parts)


def make_llm_client(provider: str, model: str):
    """Devuelve el cliente LLM para `provider`.

    ANTHROPIC → `anthropic.Anthropic()` (nativo). El resto → `OpenAICompatClient`
    apuntado al `base_url` del registro, con la key del env correspondiente.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise ValueError(f"proveedor desconocido: {provider!r}")

    if spec.get("native"):
        import anthropic
        return anthropic.Anthropic()

    from vera.llm.openai_compat_client import OpenAICompatClient
    env = spec.get("env")
    key = os.environ.get(env) if env else None
    return OpenAICompatClient(spec["base_url"], key, model)


def build_agent_loop(
    llm_client=None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    confirm=None,
    compact: bool = False,
) -> AgentLoop:
    """Arma un AgentLoop con todas las tools core (vera/agent/tools/) MÁS las tools
    de los plugins HABILITADOS, e inyecta los SKILL.md de esos plugins al system
    prompt.

    Compatibilidad: `build_agent_loop(some_client)` sigue funcionando igual.
    Si no se pasa `llm_client`, se construye uno con `make_llm_client(provider,
    model)` (default ANTHROPIC / claude-opus-4-8).
    `compact=True` usa `COMPACT_SYSTEM_PROMPT` (modelos locales chicos); los
    skills de plugins se appendean igual.
    """
    import vera.agent.tools as tools_pkg
    from vera.agent.plugins import discover_plugins

    model = model or DEFAULT_MODEL
    if llm_client is None:
        llm_client = make_llm_client(provider or DEFAULT_PROVIDER, model)

    registry = ToolRegistry()
    registry.discover(tools_pkg)

    enabled_plugins = [p for p in discover_plugins(PLUGINS_DIR) if p.enabled]
    for plugin in enabled_plugins:
        try:
            registry.discover_classes(plugin.tool_classes)
        except ValueError as e:  # name clash with a core/other tool: skip, keep going
            logger.warning("[factory] plugin %r tool clash: %s", plugin.id, e)

    base = COMPACT_SYSTEM_PROMPT if compact else SYSTEM_PROMPT
    system = _build_system_prompt(base, enabled_plugins)

    return AgentLoop(
        registry,
        llm_client,
        model=model,
        system=system,
        confirm=confirm,
    )
