import json
import logging
import os
import socket
import threading
import importlib

from vera.agent.factory import make_llm_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "ANTHROPIC"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MODE = "ask"

CONFIRM_TIMEOUT = 120.0  # segundos para que el usuario apruebe una accion destructiva
MAX_CONFIRM_BYTES = 4096  # una respuesta legitima ({"approve": true}) pesa < 100 bytes


class VeraServer:
    """Backend de agentes de VERA. Protocolo streaming: por cada comando responde
    N líneas JSON (progress/image/error) y SIEMPRE una final:
        {"type":"final","status":"success"|"error","msg":"..."}
    Asunción: un solo cliente UI activo a la vez (progress_callback apunta a la
    conexión en curso)."""

    def __init__(self, host="127.0.0.1", port=9880, blackboard=None, manager=None):
        self.host = host
        self.port = port
        # .env primero: ManagerAgent construye su cliente LLM en __init__ y lee la key del entorno
        self._load_env()
        # Inyectables para tests; en producción se crean los reales.
        if blackboard is None:
            from vera.core.blackboard import Blackboard
            blackboard = Blackboard()
        self.blackboard = blackboard
        if manager is None:
            import vera.core.manager_agent
            importlib.reload(vera.core.manager_agent)
            from vera.core.manager_agent import ManagerAgent
            manager = ManagerAgent(self.blackboard)
        self.manager = manager
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stop = threading.Event()
        self._busy = threading.Lock()
        # One persistent AgentSession per tab/session_id (each tab = its own
        # conversation context). entry = {"session": AgentSession, "compact": bool}.
        self._sessions = {}

    # ---- emisión ----

    def _make_emitter(self, conn, lock):
        def emit(event):
            with lock:
                conn.sendall((json.dumps(event) + "\n").encode("utf-8"))
        return emit

    def _make_confirm(self, conn, emit):
        """Gate destructivo con round-trip al cliente: emite un evento `question`
        y espera UNA línea JSON {"approve": bool} por el mismo socket.
        Ante la duda (timeout, desconexión, JSON inválido) DENIEGA.
        VERA_AUTO_APPROVE=1 saltea el gate (autopilot/testing).

        Invariante: mientras el gate espera en recv, NINGÚN hilo debe emitir por
        este socket (hoy se cumple: la sesión serializa los comandos y no hay
        watchers; revisar al implementar Fase 3).
        Con varios tool_use destructivos en un turno, las preguntas viajan en
        serie (el loop ejecuta tools secuencialmente) — ese orden es parte del
        contrato del protocolo."""
        def confirm(tool, args):
            if os.environ.get("VERA_AUTO_APPROVE"):
                return True
            emit({
                "type": "question",
                "tool": tool.name,
                "msg": f"VERA quiere ejecutar la acción destructiva '{tool.name}'. ¿Aprobar?",
                "args_preview": str(args)[:500],
            })
            try:
                conn.settimeout(CONFIRM_TIMEOUT)
                data = b""
                while not data.endswith(b"\n"):
                    if len(data) >= MAX_CONFIRM_BYTES:
                        return False  # respuesta sin \n demasiado larga → denegar
                    chunk = conn.recv(4096)
                    if not chunk:
                        return False  # cliente desconectado → denegar
                    data += chunk
                return bool(json.loads(data.decode("utf-8").strip()).get("approve"))
            except (OSError, ValueError):
                return False  # timeout o respuesta inválida → denegar
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

            # Control ops: NO son comandos del agente. Una línea JSON con "op" →
            # una línea JSON de respuesta. No tocan el lock de ocupado.
            if "op" in payload:
                emit(self._handle_control_op(payload))
                return

            command = payload.get("command", "")
            if not command:
                emit({"type": "final", "status": "error", "msg": "Comando vacío."})
                return
            provider = payload.get("provider") or DEFAULT_PROVIDER
            model = payload.get("model") or DEFAULT_MODEL
            mode = payload.get("mode") or DEFAULT_MODE
            session_id = payload.get("session_id") or "default"
            compact = bool(payload.get("compact", False))

            if command.strip().lower() in ("hello world", "hello world!"):
                emit({"type": "final", "status": "success",
                      "msg": "Hello World! The VERA-Unreal communication bridge is online."})
                return

            if not self._busy.acquire(blocking=False):
                emit({"type": "final", "status": "error",
                      "msg": "VERA está ocupada con otro comando. Esperá a que termine."})
                return

            self.blackboard.progress_callback = emit
            try:
                # Cerebro agéntico: sesión persistente (historial entre comandos),
                # Manager viejo como fallback si el flag está apagado.
                if os.environ.get("VERA_USE_AGENT_LOOP"):
                    session = self._agent_session(session_id, provider, model, compact)
                    self._reconfigure_session(session_id, provider, model)
                    if mode == "auto":
                        confirm = lambda tool, args: True  # noqa: E731
                    else:
                        confirm = self._make_confirm(conn, emit)
                    result = session.run(
                        command, emit=emit, confirm=confirm,
                        include_destructive=self._include_destructive_for_mode(mode))
                    success = result.get("status") == "success"
                    return

                # Fast keyword route: bypass manager_agent caching issue
                lower_cmd = command.lower()
                analyzer_kw = ["missing", "analyze", "analysis", "scan", "niagara", "acf", "gas",
                               "what assets", "que falta", "assets are", "plugins", "installed",
                               "detect", "check for", "falta", "tiene", "project has"]
                if any(kw in lower_cmd for kw in analyzer_kw):
                    emit({"type": "progress", "agent": "Analyzer", "msg": "scanning project"})
                    from vera.core.project_analyzer_agent import ProjectAnalyzerAgent
                    analyzer = ProjectAnalyzerAgent(self.blackboard)
                    result = analyzer.analyze()
                    if result and result.get("summary"):
                        success = True
                        emit({"type": "final", "status": "success", "msg": result["summary"]})
                    else:
                        success = False
                        emit({"type": "final", "status": "error", "msg": "No se pudo analizar el proyecto."})
                    return

                success = self.manager.execute_command(command)
                if success:
                    emit({"type": "final", "status": "success", "msg": "Done."})
                else:
                    emit({"type": "final", "status": "error",
                          "msg": "No pude completar el comando. Revisá la timeline y los logs del servidor."})
            except Exception as llm_error:
                logger.error(f"[VeraServer] Error: {llm_error}")
                emit({"type": "final", "status": "error",
                      "msg": f"Error procesando el comando: {llm_error}"})
            finally:
                self.blackboard.progress_callback = None
                self._busy.release()
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
        """readonly esconde las tools destructivas del schema que ve el modelo."""
        return mode != "readonly"

    # ---- control ops ----

    def _env_path(self):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

    def _handle_control_op(self, payload):
        """Despacha una control op (línea JSON con "op") → un dict de respuesta."""
        op = payload.get("op")
        try:
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
            if op == "plugins":
                return self._list_plugins()
            if op == "set_plugin":
                return self._set_plugin(payload.get("id"), bool(payload.get("enabled")))
        except Exception as e:  # nunca devolver un stacktrace crudo por el socket
            logger.error("[VeraServer] control op %s falló: %s", op, e)
            return {"type": "error", "msg": f"control op falló: {e}"}
        return {"type": "error", "msg": f"op desconocida: {op}"}

    def _test_connection(self, provider):
        """Verifica disponibilidad sin correr el agente. LOCAL → pinga /models;
        el resto → chequea que la credencial esté presente."""
        from vera.agent import models
        spec = models.PROVIDERS.get(provider)
        if spec is None:
            return {"type": "conn", "provider": provider, "ok": False,
                    "detail": "proveedor desconocido"}
        if spec.get("discover"):
            out = models.list_models(provider)
            ok = out["status"] == "online"
            detail = (f"{len(out['models'])} modelo(s) cargado(s)" if ok
                      else "LM Studio no responde (cargá un modelo)")
            return {"type": "conn", "provider": provider, "ok": ok, "detail": detail}
        if not models.has_key(provider):
            return {"type": "conn", "provider": provider, "ok": False,
                    "detail": "falta la API key"}
        return {"type": "conn", "provider": provider, "ok": True, "detail": "credencial presente"}

    def _save_credentials(self, provider, key):
        """Escribe/actualiza la key del proveedor en el .env del repo y en
        os.environ. La key NUNCA se devuelve."""
        from vera.agent.models import PROVIDERS
        spec = PROVIDERS.get(provider)
        env_name = spec.get("env") if spec else None
        if not env_name:
            return {"type": "error", "msg": f"el proveedor {provider} no usa API key"}
        self._write_env_var(env_name, key)
        os.environ[env_name] = key
        return {"type": "saved", "provider": provider, "ok": True}

    def _write_env_var(self, name, value):
        """Upsert de una variable en el .env (preserva el resto de las líneas)."""
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
        """Lista los plugins descubiertos con sus tools y si traen skill."""
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
        """Persiste el estado del plugin y descarta la sesión para que el próximo
        comando rearme el registry/loop con el cambio aplicado."""
        from vera.agent.plugins import set_plugin_enabled
        ok = set_plugin_enabled(self._plugins_dir(), plugin_id, enabled)
        if ok:
            self._sessions = {}  # all tabs rebuild with the new plugin set next turn
        return {"type": "plugin_set", "id": plugin_id, "enabled": enabled, "ok": ok}

    # ---- ciclo de vida ----

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
        """Para tests: bindea (port=0 → efímero) y acepta en un hilo. Devuelve el puerto."""
        port = self._bind()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return port

    def stop(self):
        self._stop.set()
        self.server_socket.close()

    def start(self):
        """Modo producción: bloqueante."""
        self._bind()
        logger.info(f"[VeraServer] VERA streaming server on {self.host}:{self.port}")
        self._accept_loop()


if __name__ == "__main__":
    VeraServer().start()
