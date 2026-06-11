import json
import logging
import os
import socket
import threading
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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
        self._session = None  # AgentSession persistente (solo con VERA_USE_AGENT_LOOP)

    # ---- emisión ----

    def _make_emitter(self, conn, lock):
        def emit(event):
            with lock:
                conn.sendall((json.dumps(event) + "\n").encode("utf-8"))
        return emit

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
            command = payload.get("command", "")
            if not command:
                emit({"type": "final", "status": "error", "msg": "Comando vacío."})
                return

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
                    result = self._agent_session().run(command, emit=emit)
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

    def _agent_session(self):
        """Sesión agéntica persistente: el historial sobrevive entre comandos.
        Lazy: solo se construye si el flag está activo."""
        if self._session is None:
            import anthropic
            from vera.agent.factory import build_agent_loop
            from vera.agent.session import AgentSession
            self._session = AgentSession(build_agent_loop(anthropic.Anthropic()))
        return self._session

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
