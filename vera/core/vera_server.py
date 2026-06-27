import json
import logging
import os
import socket
import sys
import threading

from vera.agent.factory import make_llm_client
from vera.agent.models import default_model, default_provider

# Stream to stdout so VERA logs land in Unreal's Output Log under LogPython
# instead of being swallowed/flagged as stderr.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "ANTHROPIC"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MODE = "ask"

CONFIRM_TIMEOUT = 300.0  # seconds to approve a destructive action (Stop is always available)
MAX_CONFIRM_BYTES = 4096  # a legitimate response ({"approve": true}) weighs < 100 bytes


class VeraServer:
    """VERA agent backend. Streaming protocol: for each command it replies with
    N JSON lines (progress/image/error) and ALWAYS a final one:
        {"type":"final","status":"success"|"error","msg":"..."}
    Assumption: a single active UI client at a time (progress_callback points to
    the in-flight connection)."""

    def __init__(self, host="127.0.0.1", port=9880, blackboard=None, manager=None):
        self.host = host
        self.port = port
        # .env first: ManagerAgent builds its LLM client in __init__ and reads the key from the environment
        self._load_env()
        # Injectable for tests; in production the real ones are created.
        if blackboard is None:
            from vera.core.blackboard import Blackboard
            blackboard = Blackboard()
        self.blackboard = blackboard
        # Legacy manager crew removed — the AgentLoop is the only brain. `manager`
        # stays injectable for tests but is no longer constructed in production.
        self.manager = manager
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stop = threading.Event()
        self._session_locks = {}
        # Set by the {"op":"cancel"} control op; the running AgentLoop checks it
        # between iterations and stops cleanly. Control ops don't take _busy, so
        # a cancel can arrive while a command is streaming.
        self._cancel = threading.Event()
        # One persistent AgentSession per tab/session_id (each tab = its own
        # conversation context). entry = {"session": AgentSession, "compact": bool}.
        self._sessions = {}

    # ---- emission ----

    def _make_emitter(self, conn, lock):
        def emit(event):
            with lock:
                conn.sendall((json.dumps(event) + "\n").encode("utf-8"))
        return emit

    def _make_confirm(self, conn, emit):
        """Destructive gate with a round-trip to the client: emits a `question`
        event and waits for ONE JSON line {"approve": bool} over the same socket.
        When in doubt (timeout, disconnect, invalid JSON) it DENIES.
        VERA_AUTO_APPROVE=1 skips the gate (autopilot/testing).

        Invariant: while the gate waits on recv, NO thread may emit over this
        socket (holds today: the session serializes commands and there are no
        watchers; revisit when implementing Phase 3).
        With several destructive tool_use calls in one turn, the questions travel
        serially (the loop executes tools sequentially) — that ordering is part of
        the protocol contract."""
        def confirm(tool, args):
            if os.environ.get("VERA_AUTO_APPROVE"):
                return True
            emit({
                "type": "question",
                "tool": tool.name,
                "msg": f"VERA wants to run the destructive action '{tool.name}'. Approve?",
                "args_preview": str(args)[:500],
            })
            try:
                conn.settimeout(CONFIRM_TIMEOUT)
                data = b""
                while not data.endswith(b"\n"):
                    if len(data) >= MAX_CONFIRM_BYTES:
                        return False  # response without \n too long → deny
                    chunk = conn.recv(4096)
                    if not chunk:
                        return False  # client disconnected → deny
                    data += chunk
                return bool(json.loads(data.decode("utf-8").strip()).get("approve"))
            except (OSError, ValueError):
                return False  # timeout or invalid response → deny
            finally:
                try:
                    conn.settimeout(None)
                except OSError:
                    pass
        return confirm

    def handle_client(self, conn, addr):
        logger.info(f"[VeraServer] Connection from {addr}")
        lock = threading.Lock()
        emit = self._make_emitter(conn, lock)
        try:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data.strip():
                return

            payload = json.loads(data.decode("utf-8").strip())

            # Control ops: NOT agent commands. One JSON line with "op" →
            # one JSON line of response. They don't touch the busy lock.
            if "op" in payload:
                emit(self._handle_control_op(payload))
                return

            command = payload.get("command", "")
            if not command:
                emit({"type": "final", "status": "error", "msg": "Empty command."})
                return
            # No explicit provider/model (e.g. first run before Setup): resolve to
            # whatever the user actually configured, not a hardcoded Anthropic.
            provider = payload.get("provider") or default_provider()
            model = payload.get("model") or default_model(provider)
            mode = payload.get("mode") or DEFAULT_MODE
            session_id = payload.get("session_id") or "default"
            # Optional attached image: {"data": "<base64>", "media_type": "..."}.
            # Validate lightly — a dict with non-empty data; otherwise ignore it.
            image = payload.get("image")
            if not (isinstance(image, dict) and image.get("data")):
                image = None
            # Compact prompt is automatic for LOCAL providers (small models choke on
            # the long prompt); cloud can still opt in via the toggle.
            compact = bool(payload.get("compact", False)) or provider == "LOCAL"

            if command.strip().lower() in ("hello world", "hello world!"):
                emit({"type": "final", "status": "success",
                      "msg": "Hello World! The VERA-Unreal communication bridge is online."})
                return

            session_busy = self._session_locks.setdefault(session_id, threading.Lock())
            if not session_busy.acquire(blocking=False):
                emit({"type": "final", "status": "error",
                      "msg": "VERA is busy with another command. Wait for it to finish."})
                return

            self.blackboard.progress_callback = emit
            try:
                # The AgentLoop is the only brain (the legacy manager crew was
                # removed). session.run emits the final event itself.
                session = self._agent_session(session_id, provider, model, compact)
                self._reconfigure_session(session_id, provider, model)
                if mode == "auto":
                    confirm = lambda tool, args: True  # noqa: E731
                else:
                    confirm = self._make_confirm(conn, emit)
                self._cancel.clear()
                session.run(
                    command, emit=emit, confirm=confirm,
                    include_destructive=self._include_destructive_for_mode(mode),
                    should_stop=lambda: self._cancel.is_set(), image=image)
            except Exception as llm_error:
                logger.error(f"[VeraServer] Error: {llm_error}")
                emit({"type": "final", "status": "error",
                      "msg": f"Error processing the command: {llm_error}"})
            finally:
                if getattr(self.blackboard, "progress_callback", None) == emit:
                    self.blackboard.progress_callback = None
                session_busy.release()
        except Exception as e:
            logger.error(f"[VeraServer] Error handling client: {e}")
        finally:
            conn.close()

    def _agent_session(self, session_id, provider=DEFAULT_PROVIDER,
                       model=DEFAULT_MODEL, compact=False):
        """Persistent agent session per tab/session_id. Each tab keeps its own
        conversation history. Rebuilt only if `compact` changed for that tab
        (compact vs full system prompt). Lazy: built on first use."""
        entry = self._sessions.get(session_id)
        if entry is None or entry["compact"] != compact:
            from vera.agent.factory import build_agent_loop
            from vera.agent.session import AgentSession
            sess = AgentSession(
                build_agent_loop(provider=provider, model=model, compact=compact))
            entry = {"session": sess, "compact": compact}
            self._sessions[session_id] = entry
        return entry["session"]

    def _reconfigure_session(self, session_id, provider, model):
        """Reconfigure this tab's loop for the turn: swap LLM client and model
        without losing the tab's history."""
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        loop = entry["session"].loop
        loop.llm = make_llm_client(provider, model)
        loop.model = model

    @staticmethod
    def _include_destructive_for_mode(mode):
        """readonly hides the destructive tools from the schema the model sees."""
        return mode != "readonly"

    # ---- control ops ----

    def _env_path(self):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

    def _handle_control_op(self, payload):
        """Dispatches a control op (JSON line with "op") → a response dict."""
        op = payload.get("op")
        try:
            if op == "cancel":
                # Signal the in-flight AgentLoop to stop between iterations.
                # Handled without the busy lock so it arrives mid-command.
                self._cancel.set()
                return {"type": "cancelled", "ok": True}
            if op == "providers":
                from vera.agent.models import list_providers
                return {"type": "providers", "providers": list_providers()}
            if op == "list_models":
                from vera.agent import models
                provider = payload.get("provider")
                out = models.list_models(provider)
                return {"type": "models", "provider": provider,
                        "models": out["models"], "status": out["status"]}
            if op == "test_connection":
                return self._test_connection(payload.get("provider"))
            if op == "save_credentials":
                return self._save_credentials(payload.get("provider"), payload.get("key"))
            if op == "commands":
                from vera.agent.factory import list_tool_specs
                return {"type": "commands", "commands": list_tool_specs()}
            if op == "plugins":
                return self._list_plugins()
            if op == "set_plugin":
                return self._set_plugin(payload.get("id"), bool(payload.get("enabled")))
            if op == "get_local_config":
                return self._get_local_config()
            if op == "set_local_config":
                return self._set_local_config(payload.get("url"), payload.get("timeout"))
        except Exception as e:  # never return a raw stacktrace over the socket
            logger.error("[VeraServer] control op %s failed: %s", op, e)
            return {"type": "error", "msg": f"control op failed: {e}"}
        return {"type": "error", "msg": f"unknown op: {op}"}

    def _test_connection(self, provider):
        """Checks availability without running the agent. LOCAL → pings /models;
        the rest → checks that the credential is present."""
        from vera.agent import models
        spec = models.PROVIDERS.get(provider)
        if spec is None:
            return {"type": "conn", "provider": provider, "ok": False,
                    "detail": "unknown provider"}
        if spec.get("discover"):
            out = models.list_models(provider)
            ok = out["status"] == "online"
            detail = (f"{len(out['models'])} model(s) loaded" if ok
                      else "LM Studio not responding (load a model)")
            return {"type": "conn", "provider": provider, "ok": ok, "detail": detail}
        if not models.has_key(provider):
            return {"type": "conn", "provider": provider, "ok": False,
                    "detail": "missing API key"}
        return {"type": "conn", "provider": provider, "ok": True, "detail": "credential present"}

    def _get_local_config(self):
        """Current local-server settings, for the Setup panel to display."""
        url = os.environ.get("VERA_LOCAL_BASE_URL") or ""
        raw = os.environ.get("VERA_LLM_TIMEOUT_S")
        try:
            secs = int(float(raw)) if raw else 0
        except (ValueError, TypeError):
            secs = 0
        return {"type": "local_config", "url": url, "timeout_s": secs}

    def _set_local_config(self, url, timeout):
        """Persist the local server URL and the LLM request timeout (seconds) to
        .env and os.environ, then drop sessions so the next command rebuilds the
        loop with the new config. Reuses the same .env upsert as save_credentials."""
        resp = {"type": "local_config_set", "ok": True}
        if url is not None:
            url = str(url).strip()
            self._write_env_var("VERA_LOCAL_BASE_URL", url)
            if url:
                os.environ["VERA_LOCAL_BASE_URL"] = url
            else:
                os.environ.pop("VERA_LOCAL_BASE_URL", None)
            resp["url"] = url
        if timeout not in (None, ""):
            try:
                secs = max(1, int(float(timeout)))
                self._write_env_var("VERA_LLM_TIMEOUT_S", str(secs))
                os.environ["VERA_LLM_TIMEOUT_S"] = str(secs)
                resp["timeout_s"] = secs
            except (ValueError, TypeError):
                resp["ok"] = False
        self._sessions = {}  # next command rebuilds the loop with the new config
        return resp

    def _save_credentials(self, provider, key):
        """Writes/updates the provider's key in the repo .env and in
        os.environ. The key is NEVER returned."""
        from vera.agent.models import PROVIDERS
        spec = PROVIDERS.get(provider)
        env_name = spec.get("env") if spec else None
        if not env_name:
            return {"type": "error", "msg": f"provider {provider} does not use an API key"}
        self._write_env_var(env_name, key)
        os.environ[env_name] = key
        return {"type": "saved", "provider": provider, "ok": True}

    def _write_env_var(self, name, value):
        """Upserts a variable in the .env (preserves the remaining lines)."""
        path = self._env_path()
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        out = []
        found = False
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped \
                    and stripped.split("=", 1)[0].strip() == name:
                out.append(f"{name}={value}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"{name}={value}")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")

    # ---- plugins ----

    def _plugins_dir(self):
        from vera.agent import factory
        return factory.PLUGINS_DIR

    def _list_plugins(self):
        """Lists the discovered plugins with their tools and whether they ship a skill."""
        from vera.agent.plugins import discover_plugins
        out = []
        for p in discover_plugins(self._plugins_dir()):
            out.append({
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "author": p.author,
                "description": p.description,
                "enabled": p.enabled,
                "tools": [tc.name for tc in p.tool_classes],
                "has_skill": p.skill_text is not None,
            })
        return {"type": "plugins", "plugins": out}

    def _set_plugin(self, plugin_id, enabled):
        """Persists the plugin state and discards the session so the next command
        rebuilds the registry/loop with the change applied. When enabling a plugin
        that declares pip `deps`, installs the missing ones (one time) and reports
        it to the user — no silent magic."""
        from vera.agent.plugins import (set_plugin_enabled, discover_plugins,
                                         plugin_missing_deps, install_packages)
        from vera.agent import factory
        ok = set_plugin_enabled(self._plugins_dir(), plugin_id, enabled)
        msg = None
        if ok and enabled:
            plugin = next((p for p in discover_plugins(self._plugins_dir())
                           if p.id == plugin_id), None)
            missing = plugin_missing_deps(plugin) if plugin else []
            if missing:
                logger.info("[VeraServer] installing deps for %s: %s", plugin_id, missing)
                installed = install_packages(missing, factory.deps_dir())
                msg = (f"Installed {', '.join(missing)} for {plugin.name}."
                       if installed else
                       f"Could not install {', '.join(missing)} for {plugin.name} "
                       f"— check the server log.")
        if ok:
            self._sessions = {}  # all tabs rebuild with the new plugin set next turn
        resp = {"type": "plugin_set", "id": plugin_id, "enabled": enabled, "ok": ok}
        if msg:
            resp["msg"] = msg
        return resp

    # ---- lifecycle ----

    def _load_env(self):
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if not line.strip() or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        if key and not os.environ.get(key):
                            os.environ[key] = value

    def _bind(self):
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.port = self.server_socket.getsockname()[1]
        return self.port

    def _accept_loop(self):
        self.server_socket.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, addr = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

    def start_in_thread(self):
        """For tests: binds (port=0 → ephemeral) and accepts on a thread. Returns the port."""
        port = self._bind()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return port

    def stop(self):
        self._stop.set()
        self.server_socket.close()

    def start(self):
        """Production mode: blocking."""
        self._bind()
        logger.info(f"[VeraServer] VERA streaming server on {self.host}:{self.port}")
        self._accept_loop()


if __name__ == "__main__":
    VeraServer().start()
