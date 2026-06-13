"""VERA Chat UI — shell Qt con interior HTML (QWebEngineView).
Fallback automático a la UI de burbujas si QtWebEngineWidgets no está disponible."""
import json
import os
import queue
import threading

import unreal

# ---------- disponibilidad de Qt / WebEngine ----------
HAS_PYSIDE = False
HAS_WEBENGINE = False
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
    except ImportError:
        pass
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
# __file__ = UE57/Content/Python/vera_ui.py
# dirname x1 = UE57/Content/Python
# dirname x2 = UE57/Content
# dirname x3 = UE57   ← project root; Saved/ lives here
HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Saved", "VERA", "chat_history.jsonl")
TABS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Saved", "VERA", "tabs.json")
BACKEND = ("127.0.0.1", 9880)
STREAM_FINAL_TIMEOUT = 300.0

_pending_events = []          # eventos del hilo lector → tick de Qt → JS (WebEngine)
_pending_vera_responses = []  # respuestas del hilo fallback → tick de Qt → VeraChatWindow
_answer_queue = queue.Queue()  # respuestas aprobar/denegar (JS → hilo lector del stream)
CONFIRM_UI_TIMEOUT = 110.0     # menor que el timeout del server (120s)
global_vera_window = None


def module_level_tick_qt(delta_time):
    """Tick global (registrado una vez): bombea Qt y drena eventos hacia JS (WebEngine)
    y también drena _pending_vera_responses para el fallback de burbujas."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            return
        app.processEvents()
        global _pending_events, _pending_vera_responses, global_vera_window
        if global_vera_window:
            # Drenaje WebEngine: eventos del hilo lector de stream → handle_event → runJavaScript
            if HAS_WEBENGINE and isinstance(global_vera_window, VeraWebWindow):
                while _pending_events:
                    event = _pending_events.pop(0)
                    global_vera_window.handle_event(event)
            # Drenaje fallback: respuestas del hilo _send_to_backend → add_vera_message
            else:
                while _pending_vera_responses:
                    color, msg = _pending_vera_responses.pop(0)
                    global_vera_window.add_vera_message(msg, color == "red")
    except Exception as e:
        unreal.log_error(f"[VERA UI] tick error: {e}")


# ---------- puente JS→Python ----------
class PyBridge(QObject):
    def __init__(self, window):
        super().__init__()
        self._window = window

    @Slot()
    def js_ready(self):
        self._window.on_js_ready()

    @Slot(str, str, str, str, str)
    def send_command(self, text, provider="", model="", mode="", session_id=""):
        """User command. provider/model/mode/session_id come from the active tab.
        'mode' is already the EFFECTIVE mode for this turn."""
        self._window.send_command(text, provider or None, model or None,
                                  mode or None, session_id or None)

    @Slot(bool)
    def answer_question(self, approve):
        """El usuario tocó Aprobar/Rechazar en el chat (round-trip del gate)."""
        _answer_queue.put(bool(approve))

    # ---- selección persistente (provider/model/mode) ----
    @Slot(str, str)
    def set_model(self, provider, model):
        self._window.provider = provider or None
        self._window.model = model or None

    @Slot(str)
    def set_mode(self, mode):
        self._window.mode = mode or None

    # ---- control ops (round-trip al backend en un hilo) ----
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
                unreal.log_warning(f"[VERA UI] open_image rechazado (fuera de Saved): {real}")
                return
            if _os.path.splitext(real)[1].lower() not in (".png", ".jpg", ".jpeg", ".bmp"):
                unreal.log_warning(f"[VERA UI] open_image rechazado (no es imagen): {real}")
                return
            _os.startfile(real)
        except OSError as e:
            unreal.log_error(f"[VERA UI] no pude abrir la imagen: {e}")


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


# ---------- ventana WebEngine ----------
class VeraWebWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VERA")
        self.resize(460, 720)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

        # selección persistente del cerebro (la pisa el JS vía set_model/set_mode)
        self.provider = None
        self.model = None
        self.mode = None
        self.compact = False  # compact prompt toggle (JS via set_compact)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView()
        self.web_page = VeraWebPage(self.view)
        self.view.setPage(self.web_page)
        self.channel = QWebChannel()
        self.pybridge = PyBridge(self)
        self.channel.registerObject("pybridge", self.pybridge)
        self.web_page.setWebChannel(self.channel)
        self.web_page.load(QUrl.fromLocalFile(os.path.join(CHAT_DIR, "index.html")))
        layout.addWidget(self.view)
        self.setLayout(layout)

    # --- eventos hacia JS (siempre desde el main thread vía tick) ---
    def handle_event(self, event):
        # question/question_resolved/thinking NO se persisten a propósito:
        # al recargar la sesión, un botón de aprobar muerto sería peor que nada.
        if event.get("type") in ("user", "progress", "image", "final", "error"):
            try:
                vera_history.append_event(HISTORY_PATH, event)
            except OSError as e:
                unreal.log_warning(f"[VERA UI] historial no disponible: {e}")
        js = "veraChat.dispatch(" + json.dumps(event, ensure_ascii=True) + ")"
        self.view.page().runJavaScript(js)

    def on_js_ready(self):
        # Restore saved tabs (full state lives in one tabs.json); JS rebuilds them.
        saved = self._load_tabs()
        self.view.page().runJavaScript(
            "veraChat.dispatch(" + json.dumps(
                {"type": "restore_tabs", "tabs": saved.get("tabs", []),
                 "active": saved.get("active")}, ensure_ascii=True) + ")")
        threading.Thread(target=self._check_status, daemon=True).start()

    # --- backend ---
    def send_command(self, text, provider=None, model=None, mode=None, session_id=None):
        # The JS already painted the user bubble; here we just send.
        # provider/model fall back to the persisted selection if the turn omits them.
        # mode is already EFFECTIVE; session_id routes to the right tab's context.
        prov = provider or self.provider
        mdl = model or self.model
        md = mode or self.mode
        threading.Thread(target=self._stream_command,
                         args=(text, prov, mdl, md, session_id), daemon=True).start()

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
        """Round-trip de una línea JSON al backend: empuja el evento de respuesta a JS."""
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
            # Sin backend: degradamos en silencio (la UI ya tiene fallback visual).
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

    def _stream_command(self, text, provider=None, model=None, mode=None, session_id=None):
        import socket
        global _pending_events

        # Fast keyword route: if it's about project analysis, use ProjectAnalyzer directly
        lower_text = text.lower()
        analyzer_kw = ["missing", "analyze", "analysis", "scan", "niagara", "acf", "gas",
                       "what assets", "que falta", "assets are", "plugins", "installed",
                       "detect", "check for", "falta", "tiene", "project has"]

        if any(kw in lower_text for kw in analyzer_kw):
            try:
                _pending_events.append({"type": "progress", "agent": "Analyzer", "msg": "scanning project"})
                import sys
                sys.path.insert(0, "E:/PCW/VERA")
                from vera.core.blackboard import Blackboard
                from vera.core.project_analyzer_agent import ProjectAnalyzerAgent

                bb = Blackboard()
                analyzer = ProjectAnalyzerAgent(bb)
                result = analyzer.analyze()

                if result and result.get("summary"):
                    _pending_events.append({"type": "final", "status": "success", "msg": result["summary"]})
                else:
                    _pending_events.append({"type": "final", "status": "error", "msg": "No se pudo analizar el proyecto."})
                return
            except Exception as e:
                _pending_events.append({"type": "error", "msg": f"Analyzer error: {str(e)}"})
                _pending_events.append({"type": "final", "status": "error", "msg": "Analysis failed"})
                return

        # Default: send to vera_server
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
        try:
            with socket.create_connection(BACKEND, timeout=STREAM_FINAL_TIMEOUT) as s:
                s.settimeout(STREAM_FINAL_TIMEOUT)
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        _pending_events.append({"type": "interrupted"})
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
                            # Round-trip del gate destructivo: mostrar la pregunta
                            # y esperar la decisión del usuario (botones en el chat).
                            while not _answer_queue.empty():
                                _answer_queue.get_nowait()  # descartar respuestas viejas
                            _pending_events.append(event)
                            try:
                                approve = _answer_queue.get(timeout=CONFIRM_UI_TIMEOUT)
                            except queue.Empty:
                                approve = False
                                _pending_events.append({"type": "question_resolved", "approved": False})
                                _pending_events.append({
                                    "type": "progress", "agent": "Gate",
                                    "msg": "sin respuesta del usuario — acción denegada"})
                            s.sendall((json.dumps({"approve": approve}) + "\n").encode("utf-8"))
                            continue
                        _pending_events.append(event)
                        if event.get("type") == "final":
                            return
        except ConnectionRefusedError:
            _pending_events.append({"type": "error",
                "msg": "El backend VERA no está corriendo. "
                       "Arrancalo con: `python -m vera.core.vera_server`"})
            _pending_events.append({"type": "status", "online": False})
        except OSError:
            _pending_events.append({"type": "interrupted"})

    def _check_status(self):
        import socket
        global _pending_events
        try:
            with socket.create_connection(BACKEND, timeout=3.0) as s:
                s.settimeout(5.0)
                s.sendall((json.dumps({"command": "hello world"}) + "\n").encode("utf-8"))
                s.recv(4096)
            _pending_events.append({"type": "status", "online": True, "version": "UE 5.7"})
        except OSError:
            _pending_events.append({"type": "status", "online": False})


# ==============================================================================
# FALLBACK UI (burbujas QFrame) — COPIA TEXTUAL de las clases actuales de
# vera_ui.py: Bubble, ChatInputEdit, VeraChatWindow.
# _pending_vera_responses se mantiene como lista global separada de _pending_events.
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

            # Leemos línea a línea para manejar el protocolo multi-evento del
            # agent loop (VERA_USE_AGENT_LOOP).  Cada línea es un JSON independiente.
            buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # Procesamos todas las líneas completas acumuladas en el buffer.
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
                        # Gate destructivo: la UI básica no tiene botón de aprobar.
                        # Denegamos explícitamente para que el agent loop no quede
                        # bloqueado esperando una respuesta que nunca va a llegar.
                        try:
                            s.sendall((json.dumps({"approve": False}) + "\n").encode("utf-8"))
                        except OSError:
                            pass
                        _pending_vera_responses.append((
                            "red",
                            "La UI básica no soporta confirmaciones — acción destructiva denegada. "
                            "Usá la UI WebEngine para aprobar acciones."
                        ))
                        # Seguimos leyendo: el server enviará más eventos tras la denegación.
                        continue

                    if etype in ("final", "error"):
                        msg = event.get("message", "Done.")
                        color = "green" if etype == "final" else "red"
                        _pending_vera_responses.append((color, msg))
                        return  # Respuesta definitiva recibida, cerramos.

                    # Eventos intermedios (progress, thinking, etc.): los ignoramos
                    # en la UI degradada; sólo nos interesa el mensaje final.

        except ConnectionRefusedError:
            _pending_vera_responses.append(("red", "Cannot connect. Is vera_server.py running?"))
        except Exception as e:
            _pending_vera_responses.append(("red", str(e)))


# ==============================================================================
# FIN FALLBACK UI
# ==============================================================================


def install_pyside_and_open():
    global HAS_PYSIDE
    global QApplication, QWidget, QVBoxLayout

    unreal.log_warning("[VERA] Detectado: PySide6 no está instalado. Instalando automáticamente en el motor...")

    try:
        import sys
        import subprocess
        # Find the actual python.exe avoiding UnrealEditor.exe
        python_exe = os.path.join(sys.exec_prefix, "python.exe")

        if not os.path.exists(python_exe):
            # Fallback for some UE versions
            python_exe = os.path.join(unreal.Paths.engine_dir(), "Binaries", "ThirdParty", "Python3", "Win64", "python.exe")

        # Auto-install PySide6
        subprocess.check_call([python_exe, "-m", "pip", "install", "PySide6"])
        unreal.log("[VERA] PySide6 instalado correctamente. Cargando módulos...")

        from PySide6.QtWidgets import (QApplication as QApp, QWidget as QWid,
                                       QVBoxLayout as QVBox)
        from PySide6.QtCore import Qt as QCoreQt, QObject as QObj, QUrl as QU, Slot as QSlot

        QApplication = QApp
        QWidget = QWid
        QVBoxLayout = QVBox

        HAS_PYSIDE = True

        # Reintentar los imports de ESTE módulo para activar WebEngine si ya estaba disponible
        import importlib
        import sys as _sys
        importlib.reload(_sys.modules[__name__])

    except Exception as e:
        unreal.log_error(f"[VERA] Falló la instalación automática de PySide6: {e}")
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
            unreal.log_warning("[VERA] QtWebEngine no disponible — usando UI básica.")
            global_vera_window = VeraChatWindow()  # fallback de burbujas
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

        # Restauramos el cerebro (antenita) porque Unreal fuerza la llave inglesa si está vacío
        entry.set_icon("EditorStyle", "ClassIcon.AIController")

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
