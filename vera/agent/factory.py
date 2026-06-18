"""Production AgentLoop construction and LLM client selection."""
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
    "and fix things if something fails. Prefer the dedicated tools: to READ or "
    "inspect (list assets, read the level) use the read-only tools — they need no "
    "approval. Use `run_ue_python` only when no dedicated tool fits: it runs "
    "arbitrary code and asks the user to approve EACH call, so don't use it for "
    "things a read-only tool already covers (the `unreal` module is available; use "
    "print() to return data). Be concise in your final answer. Do NOT introduce "
    "yourself, greet the user, or repeat your identity in every message. Just jump "
    "straight into the answer."
)

# Short prompt for small local models (LM Studio). Same identity + the load-bearing
# rules, none of the long verbiage. Plugin skills are still appended on top.
COMPACT_SYSTEM_PROMPT = (
    "You are VERA, an autonomous Unreal Engine technical agent working inside the "
    "user's editor via tools. Use the tools, verify the result, fix on failure. "
    "Prefer dedicated read-only tools to inspect; use `run_ue_python` only when no "
    "dedicated tool fits — it asks the user to approve each call. Be concise. "
    "Do NOT introduce yourself or repeat your identity. Just answer directly."
)

DEFAULT_PROVIDER = "OPENAI"


def _repo_root() -> str:
    """Repo root, derived from this file (vera/agent/factory.py → three levels up).
    Portable: no hardcoded drive paths."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def llm_timeout_seconds() -> float:
    """LLM request timeout in seconds (env VERA_LLM_TIMEOUT_S). Generous default so
    a cold local-model load (which can take minutes) is not killed mid-request; the
    user raises it in the Setup panel to match their machine."""
    raw = os.environ.get("VERA_LLM_TIMEOUT_S")
    try:
        return float(raw) if raw else 600.0
    except (ValueError, TypeError):
        return 600.0


def deps_dir() -> str:
    """Where vendored pip deps live (on sys.path via init_unreal.py). Plugins that
    declare `deps` are installed here when enabled. Override with VERA_DEPS_DIR."""
    return os.environ.get("VERA_DEPS_DIR") or os.path.join(_repo_root(), ".ue_deps")


def _default_plugins_dir() -> str:
    """Locate VERA_Plugins, portable across the dev project and the packaged plugin.

    Order: env VERA_PLUGINS_DIR; else the first existing of
    <VERA_PROJECT_ROOT|repo/UE57>/VERA_Plugins (dev project) and
    <repo>/VERA_Plugins (packaged plugin: this file is Content/Python/vera/agent/
    factory.py, so _repo_root() is Content/Python and the studio plugins sit beside
    it)."""
    explicit = os.environ.get("VERA_PLUGINS_DIR")
    if explicit:
        return explicit
    repo = _repo_root()
    candidates = []
    root = os.environ.get("VERA_PROJECT_ROOT")
    if root:
        candidates.append(os.path.join(root, "VERA_Plugins"))
    candidates.append(os.path.join(repo, "UE57", "VERA_Plugins"))  # dev project
    candidates.append(os.path.join(repo, "VERA_Plugins"))          # packaged plugin
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[-1]


PLUGINS_DIR = _default_plugins_dir()


# Compact budget for the plugin-skill injection (no tokenizer dependency).
_COMPACT_SKILL_BUDGET_TOKENS = 1000          # ~4000 chars total across all skills
_COMPACT_PER_SKILL_CHARS = 600               # per-skill cap before truncation
_TRUNC_MARK = " …(truncated)"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _truncate_skill(text: str, cap: int = _COMPACT_PER_SKILL_CHARS) -> str:
    """Cut `text` to ~`cap` chars on a word/line boundary, appending a truncation
    marker. Returns the text untouched when it already fits."""
    if len(text) <= cap:
        return text
    cut = text[:cap]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > 0:
        cut = cut[:boundary]
    return cut.rstrip() + _TRUNC_MARK


def _build_system_prompt(base: str, enabled_plugins, compact: bool = False) -> str:
    """Append a '## Studio plugins / skills' section with each enabled plugin's
    SKILL.md, when present.

    When `compact=True`, apply a token budget: each skill is truncated to a
    per-skill cap and skills are added in order until the running total hits the
    budget; remaining skills are summarized as an omission line. Non-compact mode
    includes every skill in full (unchanged behavior)."""
    skills = [(p.name, p.skill_text) for p in enabled_plugins if p.skill_text]
    if not skills:
        return base

    if not compact:
        parts = [base, "", "## Studio plugins / skills"]
        for name, text in skills:
            parts.append(f"\n### {name}\n{text.strip()}")
        return "\n".join(parts)

    included = []
    used_tokens = 0
    omitted = 0
    for name, text in skills:
        if used_tokens >= _COMPACT_SKILL_BUDGET_TOKENS:
            omitted += 1
            continue
        body = _truncate_skill(text.strip())
        cost = _estimate_tokens(body)
        if included and used_tokens + cost > _COMPACT_SKILL_BUDGET_TOKENS:
            omitted += 1
            continue
        included.append((name, body))
        used_tokens += cost

    if not included:
        return base

    parts = [base, "", "## Studio plugins / skills"]
    for name, body in included:
        parts.append(f"\n### {name}\n{body}")
    if omitted:
        parts.append(f"\n({omitted} more plugin skills omitted to fit the context)")
    return "\n".join(parts)


def make_llm_client(provider: str, model: str):
    """Return the LLM client for `provider`.

    ANTHROPIC → `anthropic.Anthropic()` (native). Everything else →
    `OpenAICompatClient` pointed at the registry's `base_url`, with the key from
    the corresponding env var.
    """
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise ValueError(f"unknown provider: {provider!r}")

    # Pre-flight: refuse to build a client we know can't authenticate, with an
    # actionable message — otherwise a missing key surfaces much later as a
    # cryptic error deep inside the SDK when the first request is sent.
    from vera.agent.models import base_url_for, provider_status
    status = provider_status(provider)
    if status == "missing_key":
        raise ValueError(
            f"No API key set for {spec['label']}. Add it in VERA's Setup tab, "
            "or pick a provider that's already configured.")
    if status == "not_configured":  # LOCAL with no VERA_LOCAL_BASE_URL
        raise ValueError(
            f"{spec['label']} has no server URL. Set it in VERA's Setup tab "
            "(or the VERA_LOCAL_BASE_URL environment variable).")

    if spec.get("native"):
        import anthropic
        return anthropic.Anthropic(api_key=os.environ[spec["env"]])

    from vera.llm.openai_compat_client import OpenAICompatClient
    base_url = base_url_for(provider)
    env = spec.get("env")
    key = os.environ.get(env) if env else None
    return OpenAICompatClient(base_url, key, model, timeout=llm_timeout_seconds())


def list_tool_specs() -> list[dict]:
    """Catalog of currently-available tools for the UI's `/` slash-command menu.

    Returns the SAME set `build_agent_loop` would use: core tools from
    `vera/agent/tools/` PLUS the tools of ENABLED plugins. Each entry is a dict
    with `name`, `desc` (first sentence of the description), `plugin` (display
    name or None for core), and `args` (name/required/enum per input property).
    Result is sorted deterministically by (plugin or "", name).
    """
    import vera.agent.tools as tools_pkg
    from vera.agent.plugins import discover_plugins
    from vera.agent.registry import _first_sentence

    registry = ToolRegistry()
    registry.discover(tools_pkg)

    # Track which tool names belong to which plugin (core = None). Register
    # plugin tools the same way build_agent_loop does; a clash with a core/other
    # tool is skipped (keep the first), never crashes.
    tool_plugin: dict[str, Optional[str]] = {t.name: None for t in registry.all()}
    for plugin in (p for p in discover_plugins(PLUGINS_DIR) if p.enabled):
        for cls in plugin.tool_classes:
            try:
                tool = cls()
            except Exception:  # broken tool class: skip it, keep going
                continue
            if tool.name in registry._tools:  # clash: keep the first
                continue
            registry.register(tool)
            tool_plugin[tool.name] = plugin.name

    # Inject Epic MCP tools natively running in 5.8
    try:
        from vera.mcp_client import EpicMCPClient
        epic_mcp = EpicMCPClient(_repo_root())
        if epic_mcp.connect():
            for t in epic_mcp.discover_tools():
                if t.name not in registry._tools:
                    registry.register(t)
                    tool_plugin[t.name] = "Epic MCP"
    except Exception as e:
        logger.error(f"Failed to load Epic MCP Client: {e}")

    specs: list[dict] = []
    for tool in registry.all():
        schema = tool.input_schema or {}
        props = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        args = [
            {
                "name": prop,
                "required": prop in required,
                "enum": (prop_schema or {}).get("enum"),
            }
            for prop, prop_schema in props.items()
        ]
        specs.append(
            {
                "name": tool.name,
                "desc": _first_sentence(tool.description),
                "plugin": tool_plugin.get(tool.name),
                "args": args,
            }
        )

    specs.sort(key=lambda s: (s["plugin"] or "", s["name"]))
    return specs


def build_agent_loop(
    llm_client=None,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    confirm=None,
    compact: bool = False,
) -> AgentLoop:
    """Build an AgentLoop with all the core tools (vera/agent/tools/) PLUS the
    tools of the ENABLED plugins, and inject those plugins' SKILL.md into the
    system prompt.

    Backward compatibility: `build_agent_loop(some_client)` still works the same.
    If no `llm_client` is passed, one is built with `make_llm_client(provider,
    model)` (default ANTHROPIC / claude-opus-4-8).
    `compact=True` uses `COMPACT_SYSTEM_PROMPT` (small local models); plugin
    skills are appended regardless.
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

    # Inject Epic MCP tools natively running in 5.8
    try:
        from vera.mcp_client import EpicMCPClient
        epic_mcp = EpicMCPClient(_repo_root())
        if epic_mcp.connect():
            for t in epic_mcp.discover_tools():
                if t.name not in registry._tools:
                    registry.register(t)
    except Exception as e:
        logger.warning("[factory] Epic MCP Client failed to connect: %s", e)

    base = COMPACT_SYSTEM_PROMPT if compact else SYSTEM_PROMPT
    system = _build_system_prompt(base, enabled_plugins, compact=compact)

    return AgentLoop(
        registry,
        llm_client,
        model=model,
        system=system,
        confirm=confirm,
        compact=compact,
    )
