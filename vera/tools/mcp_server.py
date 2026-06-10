"""Servidor MCP de VERA: expone el editor de Unreal como herramientas para Claude Code.

Las funciones de este módulo son puras/testeables; el wiring FastMCP vive en main().
"""
import os
import time
import uuid
from pathlib import Path

from vera.tools.ue_conn import UEConnectionError, UETimeoutError, send_json

# Raíz del repo = dos niveles arriba de vera/tools/
_REPO_ROOT = Path(__file__).resolve().parents[2]
UE_PROJECT_DIR = Path(os.environ.get("VERA_UE_PROJECT_DIR", _REPO_ROOT / "UE57"))
LOG_PATH = UE_PROJECT_DIR / "Saved" / "Logs" / "UE57.log"
SCREENSHOTS_DIR = UE_PROJECT_DIR / "Saved" / "Screenshots" / "WindowsEditor"

BRIDGE_PORT = int(os.environ.get("VERA_BRIDGE_PORT", "9878"))
BACKEND_PORT = int(os.environ.get("VERA_BACKEND_PORT", "9880"))

BRIDGE_DOWN_MSG = (
    "Unreal no está corriendo o el bridge no cargó. Abrí el proyecto UE57 "
    "(el bridge auto-arranca con init_unreal.py) o ejecutá `import vera_bridge` "
    "en la consola Python del editor. Probá `ue_status` para diagnosticar."
)
BACKEND_DOWN_MSG = (
    "El backend VERA (puerto 9880) no está corriendo. "
    "Arrancalo con: python -m vera.core.vera_server"
)


def tail_log(path, lines=100):
    """Últimas N líneas del log del editor. Lee el archivo directo: funciona
    aunque el editor esté colgado o crasheado."""
    path = Path(path)
    if not path.exists():
        return f"No existe el log en {path}. ¿El editor llegó a abrir alguna vez?"
    text = path.read_text(encoding="utf-8", errors="replace")
    if lines <= 0:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def run_script(script, timeout=60.0, port=None):
    """Ejecuta Python en el main thread del editor. El traceback de UE vuelve
    como resultado normal (success=False), no como excepción — el agente lo lee
    y corrige. success=None significa timeout: el script puede seguir corriendo."""
    try:
        result = send_json(port or BRIDGE_PORT, {"script": script}, timeout=timeout)
    except UETimeoutError:
        return {
            "success": None,
            "output": (
                f"El editor no respondió en {timeout:.0f}s — el script sigue "
                "ejecutando (compilar shaders o cargar assets puede tardar). "
                "Verificá con ue_log o ue_status; no se abortó nada."
            ),
        }
    except UEConnectionError:
        return {"success": False, "output": "", "error": BRIDGE_DOWN_MSG}
    return result


def check_status(bridge_port=None, backend_port=None):
    """Ping a bridge y backend. Para el bridge pide la versión del engine."""
    status = {"bridge": {"online": False, "engine_version": None}, "backend": {"online": False}}

    version_script = "import unreal\nprint(unreal.SystemLibrary.get_engine_version())"
    try:
        result = send_json(
            bridge_port or BRIDGE_PORT, {"script": version_script}, timeout=10.0
        )
        status["bridge"]["online"] = bool(result.get("success"))
        status["bridge"]["engine_version"] = result.get("output", "").strip()
    except (UEConnectionError, UETimeoutError) as e:
        status["bridge"]["error"] = f"{BRIDGE_DOWN_MSG} ({e})"

    try:
        result = send_json(
            backend_port or BACKEND_PORT, {"command": "hello world"}, timeout=10.0
        )
        status["backend"]["online"] = result.get("status") == "success"
    except (UEConnectionError, UETimeoutError) as e:
        status["backend"]["error"] = f"{BACKEND_DOWN_MSG} ({e})"

    return status


def send_vera_command(text, timeout=300.0, port=None):
    """Comando de alto nivel al ManagerAgent (pipeline de agentes/recetas)."""
    try:
        return send_json(port or BACKEND_PORT, {"command": text}, timeout=timeout)
    except UEConnectionError:
        return {"status": "error", "message": BACKEND_DOWN_MSG}
    except UETimeoutError:
        return {
            "status": "error",
            "message": f"El backend no respondió en {timeout:.0f}s. Mirá sus logs.",
        }


_SCREENSHOT_SCRIPT = (
    "import unreal\n"
    'unreal.AutomationLibrary.take_high_res_screenshot(1280, 720, "{name}")\n'
    "print('screenshot solicitado: {name}')"
)


def request_screenshot(timeout=20.0, port=None, screenshots_dir=None):
    """Pide una captura del viewport y espera a que el PNG aparezca en disco.

    Devuelve el Path del PNG, o None si falló (bridge caído o el archivo
    nunca apareció). take_high_res_screenshot es asíncrona: UE escribe el
    archivo unos frames después de ejecutar el script.
    """
    target_dir = Path(screenshots_dir) if screenshots_dir else SCREENSHOTS_DIR
    name = f"vera_{uuid.uuid4().hex[:8]}.png"

    result = run_script(_SCREENSHOT_SCRIPT.format(name=name), timeout=15.0, port=port)
    if result.get("success") is False:
        return None

    target = target_dir / name
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        if target.exists():
            size = target.stat().st_size
            # UE escribe directo al path final (sin temp+rename): exigir tamaño
            # estable en dos polls consecutivos evita devolver un PNG a medias.
            if size > 0 and size == last_size:
                return target
            last_size = size
        time.sleep(0.25)
    return None


def main():
    # Import adentro de main(): los tests importan este módulo sin necesitar el SDK
    from mcp.server.fastmcp import FastMCP, Image

    mcp = FastMCP("vera-ue")

    @mcp.tool()
    def ue_exec(script: str, timeout: float = 60.0) -> str:
        """Ejecuta Python en el main thread del editor de Unreal (módulo `unreal`
        disponible). Devuelve stdout capturado, o el traceback si el script falló."""
        result = run_script(script, timeout=timeout)
        if result.get("success") is False:
            return f"ERROR:\n{result.get('error', result.get('output', 'sin detalle'))}"
        return result.get("output", "") or "(sin output)"

    @mcp.tool()
    def ue_screenshot() -> Image:
        """Captura el viewport activo del editor y devuelve el PNG."""
        path = request_screenshot()
        if path is None:
            raise RuntimeError(
                "No se pudo capturar el viewport. " + BRIDGE_DOWN_MSG
                + " Si el bridge está OK, mirá ue_log(100)."
            )
        return Image(data=path.read_bytes(), format="png")

    @mcp.tool()
    def ue_log(lines: int = 100) -> str:
        """Últimas N líneas del Output Log del editor (lee el archivo directo:
        funciona aunque el editor esté colgado)."""
        return tail_log(LOG_PATH, lines=lines)

    @mcp.tool()
    def ue_status() -> dict:
        """Estado del bridge (9878) y del backend VERA (9880), con versión del engine."""
        return check_status()

    @mcp.tool()
    def vera_command(text: str) -> str:
        """Comando de alto nivel al pipeline de agentes VERA (ManagerAgent → recetas)."""
        result = send_vera_command(text)
        return result.get("message", str(result))

    mcp.run()


if __name__ == "__main__":
    main()
