"""VERA Chat UI — Qt shell with an HTML interior (QWebEngineView).
Falls back automatically to the bubble UI if QtWebEngineWidgets is unavailable."""
import json
import os
import queue
import threading

import unreal

# Force software rendering for the embedded QtWebEngine — the editor's GPU context
# conflicts with Chromium's and crashes (0x80000003 in Qt6WebEngineCore). Must be
# set before any WebEngine view is created. init_unreal sets this too; harmless to
# repeat. The chat UI is light, so software rendering costs nothing noticeable.
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing --no-sandbox"

# ---------- Qt / WebEngine availability ----------
HAS_PYSIDE = False
HAS_WEBENGINE = False
_WEBENGINE_IMPORT_ERROR = None
try:
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PySide6.QtCore import Qt, QObject, QUrl, Slot
    HAS_PYSIDE = True
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtGui import QDesktopServices
        HAS_WEBENGINE = True
    except ImportError as e:
        # Don't swallow this silently — a broken QtWebEngine (e.g. a bundled
        # PySide6 whose Qt DLLs mismatch the host engine's) drops VERA to the
        # basic no-tabs UI, and without the real error it's near-impossible to
        # diagnose. Keep it so we can surface it when the fallback kicks in.
        _WEBENGINE_IMPORT_ERROR = repr(e)
except ImportError:
    # PySide6 isn't available yet (it's pip-installed on-demand the first time
    # the UI opens). Define no-op stand-ins so this module can still be IMPORTED
    # without Qt; the real UI only runs once PySide6 is present. Without these,
    # the module-level `@Slot(...)` decorators on PyBridge raise NameError at
    # import time and the on-demand installer never gets a chance to run.
    HAS_PYSIDE = False

    def Slot(*args, **kwargs):
        """No-op replacement for QtCore.Slot; supports @Slot() and @Slot(str,...)."""
        def _decorator(func):
            return func
        return _decorator

    class QWidget(object):
        pass

    class QObject(object):
        pass

    Qt = None
    QUrl = None
    QApplication = None
    QVBoxLayout = None

import vera_history

CHAT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vera_chat")
try:
    import unreal
    # Robust resolution: __file__ can be unreliable in embedded or zipped environments.
    # We use the Unreal API to get the absolute path to the plugin and project saved dir.
    _plugin = unreal.PluginManager.get().find_plugin("VERA")
    if _plugin:
        CHAT_DIR = os.path.join(_plugin.get_base_dir(), "Content", "Python", "vera_chat")
    
    _saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    HISTORY_PATH = os.path.join(_saved_dir, "VERA", "chat_history.jsonl")
    TABS_PATH = os.path.join(_saved_dir, "VERA", "tabs.json")
except Exception:
    # Fallback if unreal API fails
    HISTORY_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "Saved", "VERA", "chat_history.jsonl")
    TABS_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "Saved", "VERA", "tabs.json")
BACKEND = ("127.0.0.1", 9880)
STREAM_FINAL_TIMEOUT = 300.0

_pending_events = []          # events from the reader thread → Qt tick → JS (WebEngine)
_pending_vera_responses = []  # responses from the fallback thread → Qt tick → VeraChatWindow
_answer_queue = queue.Queue()  # approve/deny answers (JS → stream reader thread)
CONFIRM_UI_TIMEOUT = 290.0     # a bit under the server's 300s gate timeout
global_vera_window = None


# ---------- Epic native MCP toolset discovery ----------
# Unreal 5.8 exposes only 3 meta-tools at the top level (list_toolsets,
# describe_toolset, call_tool); the real toolsets live one level down. These
# pure helpers fetch and shape that nested layer for the MCP settings panel.

_global_custom_mcp_port = None

def _read_mcp_url():
    """Reads the path and port from Unreal's ModelContextProtocolSettings to build the URL."""
    url = "http://127.0.0.1:8000/mcp"
    try:
        import unreal
        cls = unreal.find_object(None, "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings")
        if cls:
            s = unreal.get_default_object(cls)
            port = 8000
            path = "/mcp"
            for prop in dir(s):
                try:
                    if "port" in prop.lower():
                        port = s.get_editor_property(prop)
                    elif "path" in prop.lower() or "url" in prop.lower():
                        path = s.get_editor_property(prop)
                except Exception:
                    pass
            
            if _global_custom_mcp_port is not None:
                port = _global_custom_mcp_port
                
            # Epic Bug Workaround: UE 5.8 saves MCP settings to EditorPerProjectUserSettings.ini
            # but registers the class as an Engine setting, so the CDO never updates on restart.
            # We explicitly parse the ini file as the source of truth if we suspect stale defaults.
            elif port == 8000:
                try:
                    import os
                    proj_dir = unreal.SystemLibrary.get_project_directory()
                    ini_path = os.path.join(proj_dir, "Saved", "Config", "WindowsEditor", "EditorPerProjectUserSettings.ini")
                    if os.path.exists(ini_path):
                        with open(ini_path, "rb") as f:
                            content_bytes = f.read()
                        # Robustly handle both UTF-8 and UTF-16 by ignoring errors and stripping null bytes
                        content = content_bytes.decode("utf-8", errors="ignore").replace("\x00", "")
                        
                        in_mcp_section = False
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith("[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]"):
                                in_mcp_section = True
                            elif in_mcp_section and line.startswith("["):
                                break
                            elif in_mcp_section and line.startswith("ServerPortNumber="):
                                port = int(line.split("=")[1].strip())
                            elif in_mcp_section and line.startswith("ServerUrlPath="):
                                path = line.split("=")[1].strip()
                except Exception as ini_err:
                    unreal.log_warning(f"VERA: Failed to parse MCP ini settings: {ini_err}")

            url = f"http://127.0.0.1:{port}{path}"
    except Exception:
        pass
    return url


def _epic_mcp_tools(url=None):
    """Returns {tool_name: Tool} from a freshly connected Epic MCP client, or {}
    if Unreal's MCP server isn't reachable. Network only — safe on a worker
    thread because the url is passed in (no `unreal` API touched here)."""
    try:
        from vera.mcp_client import EpicMCPClient
        client = EpicMCPClient(None)
        if url:
            client.url = url
        if not client.connect(probe_settings=(url is None)):
            return {}
        return {t.name: t for t in client.discover_tools()}
    except Exception:
        return {}


def _parse_toolset_list(text):
    """`list_toolsets` returns lines like '- Name: description'; a description may
    wrap onto unprefixed continuation lines. Fold them into {name, description}."""
    toolsets = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            name, _, desc = line[2:].partition(":")
            toolsets.append({"name": name.strip(), "description": desc.strip()})
        elif line.strip() and toolsets:
            toolsets[-1]["description"] = (
                toolsets[-1]["description"] + " " + line.strip()).strip()
    return toolsets


def fetch_mcp_toolsets(url=None):
    """List of {name, description} for every toolset registered in Unreal's MCP."""
    tools = _epic_mcp_tools(url)
    lt = tools.get("list_toolsets")
    if not lt:
        return []
    res = lt.execute({}, None)
    if getattr(res, "is_error", False):
        return []
    return _parse_toolset_list(getattr(res, "content", "") or "")


def _describe_mcp_toolset(toolset_name, url=None):
    """List of {name, full, description} for the functions inside one toolset."""
    tools = _epic_mcp_tools(url)
    dt = tools.get("describe_toolset")
    if not dt:
        return []
    res = dt.execute({"toolset_name": toolset_name}, None)
    if getattr(res, "is_error", False):
        return []
    try:
        data = json.loads(getattr(res, "content", "") or "{}")
    except (json.JSONDecodeError, TypeError):
        return []
    funcs = []
    for fn in data.get("tools", []):
        full = fn.get("name", "")
        funcs.append({
            "name": full.split(".")[-1] if full else full,
            "full": full,
            "description": (fn.get("description") or "").strip(),
        })
    return funcs


def module_level_tick_qt(delta_time):
    """Global tick (registered once): pumps Qt and drains events toward JS (WebEngine),
    and also drains _pending_vera_responses for the bubble fallback."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            return
        app.processEvents()
        global _pending_events, _pending_vera_responses, global_vera_window
        if global_vera_window:
            # WebEngine drain: events from the stream reader thread → handle_event → runJavaScript
            if HAS_WEBENGINE and isinstance(global_vera_window, VeraWebWindow):
                while _pending_events:
                    event = _pending_events.pop(0)
                    global_vera_window.handle_event(event)
            # Fallback drain: responses from the _send_to_backend thread → add_vera_message
            else:
                while _pending_vera_responses:
                    color, msg = _pending_vera_responses.pop(0)
                    global_vera_window.add_vera_message(msg, color == "red")
    except Exception as e:
        unreal.log_error(f"[VERA UI] tick error: {e}")


# ---------- JS→Python bridge ----------
class PyBridge(QObject):
    def __init__(self, window):
        super().__init__()
        self._window = window

    @Slot()
    def js_ready(self):
        self._window.on_js_ready()

    @Slot(str, str, str, str, str, str)
    def send_command(self, text, provider="", model="", mode="", session_id="", image_json=""):
        """User command. provider/model/mode/session_id come from the active tab.
        image_json: JSON {data, media_type} or "" — an optional image attachment."""
        image = None
        if image_json:
            try:
                image = json.loads(image_json)
            except ValueError:
                image = None
        self._window.send_command(text, provider or None, model or None,
                                  mode or None, session_id or None, image)

    @Slot(bool)
    def answer_question(self, approve):
        """The user tapped Approve/Reject in the chat (gate round-trip)."""
        _answer_queue.put(bool(approve))

    # ---- persistent selection (provider/model/mode) ----
    @Slot(str, str)
    def set_model(self, provider, model):
        self._window.provider = provider or None
        self._window.model = model or None

    @Slot(str)
    def set_mode(self, mode):
        self._window.mode = mode or None

    # ---- control ops (round-trip to the backend on a thread) ----
    @Slot(str)
    def list_models(self, provider):
        self._window.control_op({"op": "list_models", "provider": provider})

    @Slot(str)
    def test_connection(self, provider):
        self._window.control_op({"op": "test_connection", "provider": provider})

    @Slot()
    def providers(self):
        self._window.control_op({"op": "providers"})

    @Slot(str, str)
    def save_credentials(self, provider, key):
        self._window.control_op({"op": "save_credentials", "provider": provider, "key": key})

    @Slot()
    def google_login(self):
        self._window.control_op({"op": "google_login"})

    @Slot()
    def check_google_login(self):
        self._window.control_op({"op": "check_google_login"})

    # ---- local server config (URL + LLM request timeout) ----
    @Slot()
    def get_local_config(self):
        self._window.control_op({"op": "get_local_config"})

    @Slot(str, str)
    def set_local_config(self, url, timeout):
        self._window.control_op({"op": "set_local_config", "url": url, "timeout": timeout})

    # ---- compact prompt toggle (per-turn flag, persisted on the window) ----
    @Slot(bool)
    def set_compact(self, on):
        self._window.compact = bool(on)

    # ---- plugins ----
    @Slot()
    def plugins(self):
        self._window.control_op({"op": "plugins"})

    @Slot(str, bool)
    def set_plugin(self, plugin_id, enabled):
        self._window.control_op({"op": "set_plugin", "id": plugin_id, "enabled": bool(enabled)})

    # ---- tabs persistence ----
    @Slot(str)
    def save_tabs(self, data_json):
        self._window.save_tabs(data_json)

    # ---- unreal mcp settings ----
    @Slot()
    def get_unreal_mcp_settings(self):
        url_path = "/mcp"
        port = 8000
        has_mcp = False
        try:
            import unreal
            
            # Use dir(unreal) instead of hasattr to check if the class is exposed.
            # hasattr() forces a LoadObject which throws a yellow warning in the log
            # if the class doesn't exist (e.g. UE 5.7, or 5.8 with the plugin disabled).
            cls = unreal.find_object(None, "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings")
            if cls:
                settings = unreal.get_default_object(cls)
                has_mcp = True
                for prop in dir(settings):
                    try:
                        if "port" in prop.lower():
                            port = settings.get_editor_property(prop)
                        elif "path" in prop.lower() or "url" in prop.lower():
                            url_path = settings.get_editor_property(prop)
                    except Exception:
                        pass
                
                if _global_custom_mcp_port is not None:
                    port = _global_custom_mcp_port
                
                # Epic Bug Workaround for UI labels
                elif port == 8000:
                    try:
                        import os
                        proj_dir = unreal.SystemLibrary.get_project_directory()
                        ini_path = os.path.join(proj_dir, "Saved", "Config", "WindowsEditor", "EditorPerProjectUserSettings.ini")
                        if os.path.exists(ini_path):
                            with open(ini_path, "rb") as f:
                                content_bytes = f.read()
                            # Robustly handle both UTF-8 and UTF-16 by ignoring errors and stripping null bytes
                            content = content_bytes.decode("utf-8", errors="ignore").replace("\x00", "")
                            
                            in_mcp_section = False
                            for line in content.splitlines():
                                line = line.strip()
                                if line.startswith("[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]"):
                                    in_mcp_section = True
                                elif in_mcp_section and line.startswith("["):
                                    break
                                elif in_mcp_section and line.startswith("ServerPortNumber="):
                                    port = int(line.split("=")[1].strip())
                                elif in_mcp_section and line.startswith("ServerUrlPath="):
                                    url_path = line.split("=")[1].strip()
                    except Exception as ini_err:
                        pass
        except Exception:
            pass # Ignore if the class isn't exposed to Python
            
        payload = {
            "type": "mcp_settings",
            "installed": has_mcp,
            "url_path": url_path,
            "port": port
        }
        _pending_events.append(payload)

    @Slot(int)
    def start_epic_mcp(self, port):
        global _global_custom_mcp_port
        _global_custom_mcp_port = port
        try:
            import unreal
            cls = unreal.find_object(None, "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings")
            if cls:
                s = unreal.get_default_object(cls)
                for prop in dir(s):
                    try:
                        if "port" in prop.lower():
                            s.set_editor_property(prop, port)
                            break
                    except Exception:
                        pass
            unreal.SystemLibrary.execute_console_command(None, f"ModelContextProtocol.StartServer {port}")
        except Exception as e:
            unreal.log_error(f"[VERA] Failed to start MCP server: {e}")

    # ---- unreal mcp toolsets (the nested layer behind list_toolsets) ----
    # These do blocking network I/O, so the work runs on a daemon thread and the
    # result is delivered via _pending_events (drained by the Qt tick). The slot
    # itself returns instantly — otherwise the editor's game thread would freeze.
    # The MCP url is resolved here (game thread) and handed to the worker, which
    # must never touch the `unreal` API.
    @Slot()
    def get_unreal_mcp_toolsets(self):
        url = _read_mcp_url()

        def _work():
            try:
                toolsets = fetch_mcp_toolsets(url)
            except Exception:
                toolsets = []
            _pending_events.append({"type": "mcp_toolsets", "toolsets": toolsets})

        threading.Thread(target=_work, daemon=True).start()

    @Slot(str)
    def describe_mcp_toolset(self, toolset_name):
        url = _read_mcp_url()

        def _work():
            try:
                funcs = _describe_mcp_toolset(toolset_name, url)
            except Exception:
                funcs = []
            _pending_events.append({
                "type": "mcp_toolset_detail",
                "toolset": toolset_name,
                "tools": funcs,
            })

        threading.Thread(target=_work, daemon=True).start()

    # ---- stop / cancel the running command ----
    @Slot()
    def stop(self):
        self._window.control_op({"op": "cancel"})

    # ---- command catalog (for the / slash menu) ----
    @Slot()
    def commands(self):
        self._window.control_op({"op": "commands"})

    @Slot(str)
    def open_image(self, path):
        try:
            import os as _os
            real = _os.path.realpath(path)
            # __file__ = UE57/Content/Python/vera_ui.py
            # dirname x1 = UE57/Content/Python
            # dirname x2 = UE57/Content
            # dirname x3 = UE57  ← UE project root; Saved/ is a direct child
            _ue_root = _os.path.dirname(
                _os.path.dirname(
                    _os.path.dirname(_os.path.abspath(__file__))))
            shots_dir = _os.path.realpath(_os.path.join(_ue_root, "Saved", "Screenshots"))
            saved_vera = _os.path.realpath(_os.path.join(_ue_root, "Saved", "VERA"))
            def _inside(child, parent):
                return child == parent or child.startswith(parent + _os.sep)
            if not (_inside(real, shots_dir) or _inside(real, saved_vera)):
                unreal.log_warning(f"[VERA UI] open_image rejected (outside Saved): {real}")
                return
            if _os.path.splitext(real)[1].lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
                unreal.log_warning(f"[VERA UI] open_image rejected (not an image): {real}")
                return
            import sys as _sys, subprocess as _subprocess
            if _sys.platform == "win32":
                _os.startfile(real)  # Windows-only API
            elif _sys.platform == "darwin":
                _subprocess.run(["open", real], check=False)
            else:
                _subprocess.run(["xdg-open", real], check=False)
        except OSError as e:
            unreal.log_error(f"[VERA UI] could not open the image: {e}")


# ---------- web page: external links open in the system browser ----------
class VeraWebPage(QWebEnginePage if HAS_WEBENGINE else object):
    """Keeps the chat in the view; opens external links in the OS browser.

    Without this, clicking a link inside a message (e.g. a billing URL in a
    provider error) navigates the whole webview away and the VERA chat is lost.
    We intercept link clicks and hand http(s) URLs to the system browser, so the
    chat stays intact and the page opens OUTSIDE Unreal.
    """
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        try:
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                QDesktopServices.openUrl(url)
                return False  # do NOT navigate the chat view away
        except Exception as e:
            unreal.log_warning(f"[VERA UI] could not open external link: {e}")
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        unreal.log_warning(f"[JS Console] {message} (line {lineNumber} in {sourceID})")



# ---------- WebEngine window ----------
class VeraWebWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VERA")
        self.resize(460, 720)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

        # persistent brain selection (overridden by JS via set_model/set_mode)
        self.provider = None
        self.model = None
        self.mode = None
        self.compact = False  # compact prompt toggle (JS via set_compact)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView()
        self.web_page = VeraWebPage(self.view)
        
        # CLEAR CACHE to prevent gray screen corruption
        self.web_page.profile().clearHttpCache()
        
        self.view.setPage(self.web_page)
        
        # Enable local file access explicitly (required in newer PySide6 versions)
        settings = self.view.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        
        self.channel = QWebChannel()
        self.pybridge = PyBridge(self)
        self.channel.registerObject("pybridge", self.pybridge)
        self.web_page.setWebChannel(self.channel)
        # QtWebEngine caches even file:// responses in a global on-disk cache
        # (AppData/.../UnrealEngine/.../webcache_*). That cache survives plugin
        # updates, so a stale index.html/CSS/JS renders an ancient UI even when
        # the files on disk are current. This is a local dev UI — disable the
        # HTTP cache and flush any existing entries so we always load from disk.
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfile
            _profile = self.web_page.profile()
            _profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
            _profile.clearHttpCache()
        except Exception:
            pass
        self.web_page.load(QUrl.fromLocalFile(os.path.join(CHAT_DIR, "index.html")))
        layout.addWidget(self.view)
        self.setLayout(layout)

    # --- events toward JS (always from the main thread via tick) ---
    def handle_event(self, event):
        # question/question_resolved/thinking are deliberately NOT persisted:
        # on session reload, a dead approve button would be worse than nothing.
        if event.get("type") in ("user", "progress", "image", "final", "error"):
            try:
                vera_history.append_event(HISTORY_PATH, event)
            except OSError as e:
                unreal.log_warning(f"[VERA UI] history unavailable: {e}")
        js = "veraChat.dispatch(" + json.dumps(event, ensure_ascii=True) + ")"
        self.view.page().runJavaScript(js)

    def on_js_ready(self):
        # Restore saved tabs (full state lives in one tabs.json); JS rebuilds them.
        saved = self._load_tabs()
        self.view.page().runJavaScript(
            "veraChat.dispatch(" + json.dumps(
                {"type": "restore_tabs", "tabs": saved.get("tabs", []),
                 "active": saved.get("active")}, ensure_ascii=True) + ")")
        self.pybridge.get_unreal_mcp_settings()
        threading.Thread(target=self._check_status, daemon=True).start()

    # --- backend ---
    def send_command(self, text, provider=None, model=None, mode=None, session_id=None, image=None):
        # The JS already painted the user bubble; here we just send.
        # provider/model fall back to the persisted selection if the turn omits them.
        # mode is already EFFECTIVE; session_id routes to the right tab's context.
        # image: optional {data, media_type} attachment for vision-capable models.
        prov = provider or self.provider
        mdl = model or self.model
        md = mode or self.mode
        threading.Thread(target=self._stream_command,
                         args=(text, prov, mdl, md, session_id, image), daemon=True).start()

    # --- tabs persistence (JS-driven; full state in one tabs.json) ---
    def save_tabs(self, data_json):
        try:
            json.loads(data_json)  # validate before writing
            os.makedirs(os.path.dirname(TABS_PATH), exist_ok=True)
            with open(TABS_PATH, "w", encoding="utf-8") as f:
                f.write(data_json)
        except (OSError, ValueError) as e:
            unreal.log_warning(f"[VERA UI] could not save tabs: {e}")

    def _load_tabs(self):
        try:
            with open(TABS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"tabs": []}

    # --- control ops (list_models / test_connection / providers / save_credentials) ---
    def control_op(self, op_payload):
        """One-line JSON round-trip to the backend: pushes the response event to JS."""
        threading.Thread(target=self._control_op, args=(op_payload,), daemon=True).start()

    def _control_op(self, op_payload):
        import socket
        global _pending_events
        try:
            with socket.create_connection(BACKEND, timeout=10.0) as s:
                s.settimeout(15.0)
                s.sendall((json.dumps(op_payload) + "\n").encode("utf-8"))
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                line = buf.split(b"\n", 1)[0].strip()
                if line:
                    try:
                        event = json.loads(line.decode("utf-8"))
                        _pending_events.append(event)
                    except ValueError:
                        pass
        except OSError:
            # No backend: degrade silently (the UI already has a visual fallback).
            op = op_payload.get("op")
            prov = op_payload.get("provider")
            if op == "list_models":
                _pending_events.append({"type": "models", "provider": prov,
                                        "models": [], "status": "offline"})
            elif op == "test_connection":
                _pending_events.append({"type": "conn", "provider": prov,
                                        "ok": False, "detail": "backend offline"})
            elif op == "save_credentials":
                _pending_events.append({"type": "saved", "provider": prov, "ok": False})

    def _stream_command(self, text, provider=None, model=None, mode=None, session_id=None, image=None):
        import socket
        global _pending_events

        # Every command goes to the brain (vera_server) — no keyword interception.
        # Project analysis is now an agent TOOL (analyze_project, project-intelligence
        # plugin) that the brain decides to call, instead of a regex hijack here.
        payload = {"command": text}
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        if mode:
            payload["mode"] = mode
        if getattr(self, "compact", False):
            payload["compact"] = True
        if session_id:
            payload["session_id"] = session_id
        if image and isinstance(image, dict) and image.get("data"):
            payload["image"] = image
        try:
            with socket.create_connection(BACKEND, timeout=STREAM_FINAL_TIMEOUT) as s:
                s.settimeout(STREAM_FINAL_TIMEOUT)
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        _pending_events.append({"type": "interrupted", "_tab": session_id})
                        return
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line.decode("utf-8"))
                        except ValueError:
                            continue
                        if event.get("type") == "question":
                            event["_tab"] = session_id
                            # Destructive-gate round-trip: show the question and
                            # wait for the user's decision (buttons in the chat).
                            while not _answer_queue.empty():
                                _answer_queue.get_nowait()  # discard stale answers
                            _pending_events.append(event)
                            try:
                                approve = _answer_queue.get(timeout=CONFIRM_UI_TIMEOUT)
                            except queue.Empty:
                                approve = False
                                _pending_events.append({"type": "question_resolved", "approved": False, "_tab": session_id})
                                _pending_events.append({
                                    "type": "progress", "agent": "Gate",
                                    "msg": "no response from the user — action denied", "_tab": session_id})
                            s.sendall((json.dumps({"approve": approve}) + "\n").encode("utf-8"))
                            continue
                        event["_tab"] = session_id
                        _pending_events.append(event)
                        if event.get("type") == "final":
                            return
        except ConnectionRefusedError:
            _pending_events.append({"type": "error",
                "msg": "The VERA backend isn't running. "
                       "Start it with: `python -m vera.core.vera_server`", "_tab": session_id})
            _pending_events.append({"type": "status", "online": False})
        except OSError:
            _pending_events.append({"type": "interrupted", "_tab": session_id})

    def _check_status(self):
        import socket
        global _pending_events
        try:
            import unreal
            ver = "UE " + unreal.SystemLibrary.get_engine_version().split('-')[0]
        except Exception:
            ver = "UE"
            
        try:
            with socket.create_connection(BACKEND, timeout=3.0) as s:
                s.settimeout(5.0)
                s.sendall((json.dumps({"command": "hello world"}) + "\n").encode("utf-8"))
                s.recv(4096)
            _pending_events.append({"type": "status", "online": True, "version": ver})
        except OSError:
            _pending_events.append({"type": "status", "online": False})


# ==============================================================================
# FALLBACK UI (QFrame bubbles) — VERBATIM COPY of vera_ui.py's current classes:
# Bubble, ChatInputEdit, VeraChatWindow.
# _pending_vera_responses is kept as a global list separate from _pending_events.
# ==============================================================================

# Handle PySide imports gracefully for fallback (import extra widgets if available)
try:
    from PySide6.QtWidgets import (QHBoxLayout, QTextEdit, QLineEdit, QPushButton,
                                   QScrollArea, QLabel, QFrame, QSizePolicy,
                                   QGraphicsOpacityEffect)
    from PySide6.QtCore import QTimer, Signal, QPropertyAnimation, QEasingCurve
    from PySide6.QtGui import QFont, QColor, QPalette, QCursor
    _HAS_FALLBACK_WIDGETS = True
except ImportError:
    # PySide6 missing: define no-op stand-ins so this module still imports.
    # `Signal()` runs at class-body level in ChatInputEdit, so it must exist as
    # a callable even when Qt is absent (the fallback UI never actually runs).
    _HAS_FALLBACK_WIDGETS = False

    def Signal(*args, **kwargs):
        return None

    QHBoxLayout = QTextEdit = QLineEdit = QPushButton = None
    QScrollArea = QLabel = QFrame = QSizePolicy = QGraphicsOpacityEffect = None
    QTimer = QPropertyAnimation = QEasingCurve = None
    QFont = QColor = QPalette = QCursor = None


class Bubble(QFrame if _HAS_FALLBACK_WIDGETS else object):
    def __init__(self, text, is_user=False, is_error=False):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)

        font = QFont("Inter", 10)
        font.setStyleHint(QFont.SansSerif)
        label.setFont(font)

        layout.addWidget(label)
        self.setLayout(layout)
        self.label_widget = label  # Save ref for dynamic updates

        # Fade In Animation
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation.setDuration(350)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.start()

        # Styling
        if is_user:
            self.setStyleSheet("""
                QFrame {
                    background-color: #0e639c;
                    color: #ffffff;
                    border-radius: 12px;
                    border-bottom-right-radius: 2px;
                }
            """)
        elif is_error:
            self.setStyleSheet("""
                QFrame {
                    background-color: #4d1a1a;
                    color: #ff8080;
                    border-radius: 12px;
                    border-bottom-left-radius: 2px;
                    border: 1px solid #802b2b;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #2d2d30;
                    color: #cccccc;
                    border-radius: 12px;
                    border-bottom-left-radius: 2px;
                    border: 1px solid #3e3e42;
                }
            """)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)


class ChatInputEdit(QTextEdit if _HAS_FALLBACK_WIDGETS else object):
    send_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setPlaceholderText("Command VERA... (Shift+Enter for newline)")
        self.setFixedHeight(38)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QTextEdit {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 15px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #007acc;
            }
        """)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if event.modifiers() & Qt.ShiftModifier:
                # Insert newline
                super().keyPressEvent(event)
                self._adjust_height()
            else:
                # Send command
                self.send_requested.emit()
                event.accept()
        else:
            super().keyPressEvent(event)
            self._adjust_height()

    def _adjust_height(self):
        doc_height = int(self.document().size().height())
        # Add some padding to height
        new_height = max(38, min(120, doc_height + 18))
        if self.height() != new_height:
            self.setFixedHeight(new_height)


class VeraChatWindow(QWidget if HAS_PYSIDE else object):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VERA")
        self.resize(450, 700)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: #1e1e1e;")

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background-color: #252526; border-bottom: 1px solid #333333;")
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(15, 10, 15, 10)

        title_label = QLabel("VERA")
        title_label.setStyleSheet("color: #cccccc; font-weight: bold; font-size: 16px; font-family: 'Segoe UI', Inter;")
        status_label = QLabel("● Online")
        status_label.setStyleSheet("color: #89d185; font-size: 11px; font-family: 'Segoe UI', Inter;")

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(status_label)
        header.setLayout(header_layout)
        main_layout.addWidget(header)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #1e1e1e; }
            QScrollBar:vertical {
                border: none;
                background: #1e1e1e;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #424242;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4f4f4f;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
        """)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: #1e1e1e;")
        self.chat_layout = QVBoxLayout()
        self.chat_layout.setAlignment(Qt.AlignTop)
        self.chat_layout.setContentsMargins(15, 15, 15, 15)
        self.chat_layout.setSpacing(10)

        self.scroll_content.setLayout(self.chat_layout)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        # Input Area
        input_container = QFrame()
        input_container.setStyleSheet("background-color: #252526; border-top: 1px solid #333333;")
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(15, 15, 15, 15)
        input_layout.setSpacing(10)

        self.input_field = ChatInputEdit()
        self.input_field.send_requested.connect(self.send_command)
        input_layout.addWidget(self.input_field, 1)

        self.send_button = QPushButton("🤖")
        self.send_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #cccccc;
                border: 1px solid #333333;
                border-radius: 6px;
                min-width: 38px;
                max-width: 38px;
                min-height: 38px;
                max-height: 38px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #3e3e42;
                border: 1px solid #007acc;
            }
        """)
        self.send_button.clicked.connect(self.send_command)
        input_layout.addWidget(self.send_button)

        input_container.setLayout(input_layout)
        main_layout.addWidget(input_container)

        self.setLayout(main_layout)

        # Initial greeting
        self.thinking_bubble = None
        self.thinking_timer = None
        self.thinking_dots = 0
        self.add_vera_message("Hi, I'm VERA! How can I help you build your project today?")

    def _scroll_to_bottom(self):
        # Allow UI to update before scrolling
        QTimer.singleShot(10, lambda: self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum()))

    def add_bubble(self, text, is_user=False, is_error=False):
        bubble = Bubble(text, is_user, is_error)

        row = QHBoxLayout()
        if is_user:
            row.addStretch()
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch()

        self.chat_layout.addLayout(row)
        self._scroll_to_bottom()
        return row

    def add_user_message(self, text):
        self.add_bubble(text, is_user=True)

    def add_vera_message(self, text, is_error=False):
        if self.thinking_timer:
            self.thinking_timer.stop()
            self.thinking_timer.deleteLater()
            self.thinking_timer = None

        if self.thinking_bubble:
            # Remove thinking bubble
            self.thinking_bubble.deleteLater()
            self.chat_layout.removeItem(self.thinking_bubble_row)
            self.thinking_bubble = None
            self.thinking_bubble_row = None

        self.add_bubble(text, is_user=False, is_error=is_error)

    def show_thinking(self):
        if not self.thinking_bubble:
            self.thinking_bubble_row = self.add_bubble("⠋", is_user=False)
            self.thinking_bubble = self.thinking_bubble_row.itemAt(0).widget()

            # Give it a slight fade styling
            if self.thinking_bubble:
                self.thinking_bubble.setStyleSheet("""
                    QFrame {
                        background-color: #2d2d30;
                        color: #858585;
                        border-radius: 12px;
                        border-bottom-left-radius: 2px;
                        border: 1px solid #3e3e42;
                    }
                """)

            # Start dynamic dot animation
            self.thinking_dots = 1
            self.thinking_timer = QTimer(self)
            self.thinking_timer.timeout.connect(self._update_thinking_dots)
            self.thinking_timer.start(400)

    def _update_thinking_dots(self):
        if self.thinking_bubble and hasattr(self.thinking_bubble, 'label_widget'):
            spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            self.thinking_dots = (self.thinking_dots + 1) % len(spinner_chars)
            char = spinner_chars[self.thinking_dots]
            self.thinking_bubble.label_widget.setText(char)

    def send_command(self):
        command = self.input_field.toPlainText().strip()
        if not command:
            return

        self.add_user_message(command)
        self.input_field.clear()
        self.input_field.setFixedHeight(38)
        self.show_thinking()

        # Run network call in background thread so UI doesn't freeze
        threading.Thread(target=self._send_to_backend, args=(command,), daemon=True).start()

    def _send_to_backend(self, command):
        global _pending_vera_responses
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(60.0)
            s.connect(("127.0.0.1", 9880))

            payload = json.dumps({"command": command}) + "\n"
            s.sendall(payload.encode("utf-8"))

            # Read line by line to handle the agent loop's multi-event protocol
            # (VERA_USE_AGENT_LOOP). Each line is an independent JSON object.
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # Process every complete line accumulated in the buffer.
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except Exception as parse_err:
                        _pending_vera_responses.append(("red", f"parse error: {parse_err}"))
                        continue

                    etype = event.get("type")

                    if etype == "question":
                        # Destructive gate: the basic UI has no approve button.
                        # We deny explicitly so the agent loop doesn't stay
                        # blocked waiting for an answer that will never arrive.
                        try:
                            s.sendall((json.dumps({"approve": False}) + "\n").encode("utf-8"))
                        except OSError:
                            pass
                        _pending_vera_responses.append((
                            "red",
                            "The basic UI doesn't support confirmations — destructive action denied. "
                            "Use the WebEngine UI to approve actions."
                        ))
                        # Keep reading: the server will send more events after the denial.
                        continue

                    if etype in ("final", "error"):
                        msg = event.get("message", "Done.")
                        color = "green" if etype == "final" else "red"
                        _pending_vera_responses.append((color, msg))
                        return  # Final response received, close.

                    # Intermediate events (progress, thinking, etc.): we ignore them
                    # in the degraded UI; we only care about the final message.

        except ConnectionRefusedError:
            _pending_vera_responses.append(("red", "Cannot connect. Is vera_server.py running?"))
        except Exception as e:
            _pending_vera_responses.append(("red", str(e)))


# ==============================================================================
# END FALLBACK UI
# ==============================================================================


def install_pyside_and_open():
    global HAS_PYSIDE
    global QApplication, QWidget, QVBoxLayout

    unreal.log_warning("[VERA] Detected: PySide6 is not installed. Installing it into the engine automatically...")

    try:
        import sys
        import subprocess
        # Find the embedded interpreter (avoid UnrealEditor.exe), per platform.
        if sys.platform == "win32":
            python_exe = os.path.join(sys.exec_prefix, "python.exe")
            engine_sub = os.path.join("Binaries", "ThirdParty", "Python3", "Win64", "python.exe")
        elif sys.platform == "darwin":
            python_exe = os.path.join(sys.exec_prefix, "bin", "python3")
            engine_sub = os.path.join("Binaries", "ThirdParty", "Python3", "Mac", "bin", "python3")
        else:
            python_exe = os.path.join(sys.exec_prefix, "bin", "python3")
            engine_sub = os.path.join("Binaries", "ThirdParty", "Python3", "Linux", "bin", "python3")

        if not os.path.exists(python_exe):
            # Fallback for some UE versions: the engine's bundled interpreter
            python_exe = os.path.join(unreal.Paths.engine_dir(), engine_sub)

        # Auto-install PySide6
        subprocess.check_call([python_exe, "-m", "pip", "install", "PySide6"])
        unreal.log("[VERA] PySide6 installed successfully. Loading modules...")

        from PySide6.QtWidgets import (QApplication as QApp, QWidget as QWid,
                                       QVBoxLayout as QVBox)
        from PySide6.QtCore import Qt as QCoreQt, QObject as QObj, QUrl as QU, Slot as QSlot

        QApplication = QApp
        QWidget = QWid
        QVBoxLayout = QVBox

        HAS_PYSIDE = True

        # Retry THIS module's imports to enable WebEngine if it was already available
        import importlib
        import sys as _sys
        importlib.reload(_sys.modules[__name__])

    except Exception as e:
        unreal.log_error(f"[VERA] Automatic PySide6 installation failed: {e}")
        return False

    return True


def open_vera_ui():
    global global_vera_window
    if not HAS_PYSIDE:
        if not install_pyside_and_open():
            return

    app = QApplication.instance()
    if not app:
        app = QApplication([])

    if global_vera_window is None:
        if HAS_WEBENGINE:
            global_vera_window = VeraWebWindow()
        else:
            why = f" Reason: {_WEBENGINE_IMPORT_ERROR}" if _WEBENGINE_IMPORT_ERROR else ""
            unreal.log_warning(
                "[VERA] QtWebEngine unavailable — using the basic UI (no tabs)." + why
                + " This usually means the bundled PySide6 version mismatches the"
                + " editor's Qt runtime. Try PySide6 6.11.x for UE 5.8.")
            global_vera_window = VeraChatWindow()  # bubble fallback
        try:
            unreal.parent_external_window_to_slate(global_vera_window.winId())
        except Exception:
            pass
        if not hasattr(unreal, "_vera_qt_tick_registered_v6"):
            unreal._vera_tick_func = module_level_tick_qt
            unreal.register_slate_post_tick_callback(unreal._vera_tick_func)
            unreal._vera_qt_tick_registered_v6 = True

    global_vera_window.show()


# ==============================================================================
# MENU INJECTION: Add "VERA" button to the Unreal Editor Toolbar
# ==============================================================================
def create_vera_menu():
    menus = unreal.ToolMenus.get()
    toolbar = menus.find_menu("LevelEditor.LevelEditorToolBar.PlayToolBar")
    if not toolbar:
        toolbar = menus.find_menu("LevelEditor.LevelEditorToolBar")

    if toolbar:
        entry = unreal.ToolMenuEntry(
            name="VERA_AI",
            type=unreal.MultiBlockType.TOOL_BAR_BUTTON,
            insert_position=unreal.ToolMenuInsert("", unreal.ToolMenuInsertType.FIRST)
        )
        entry.set_label("🤖 VERA")
        entry.set_tool_tip("Open VERA chat interface")

        # VERA logo, registered as a Slate brush by the C++ module (FVERAModule).
        # If that module isn't loaded (e.g. running the Python in a dev project
        # without the compiled plugin), Unreal falls back to a default glyph.
        entry.set_icon("VERAStyle", "VERA.Logo")

        entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type="Python",
            string="import vera_ui; vera_ui.open_vera_ui()"
        )

        toolbar.add_menu_entry("Settings", entry)
        menus.refresh_all_widgets()
        unreal.log("[VERA] VERA Menu injected into the Editor toolbar.")
    else:
        unreal.log_warning("[VERA] Could not find the Toolbar to inject the menu.")

create_vera_menu()
