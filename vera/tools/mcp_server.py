"""Servidor MCP de VERA: expone el editor de Unreal como herramientas para Claude Code.

Las funciones de este módulo son puras/testeables; el wiring FastMCP vive en main().
"""
import os
from pathlib import Path

# Raíz del repo = dos niveles arriba de vera/tools/
_REPO_ROOT = Path(__file__).resolve().parents[2]
UE_PROJECT_DIR = Path(os.environ.get("VERA_UE_PROJECT_DIR", _REPO_ROOT / "UE57"))
LOG_PATH = UE_PROJECT_DIR / "Saved" / "Logs" / "UE57.log"


def tail_log(path, lines=100):
    """Últimas N líneas del log del editor. Lee el archivo directo: funciona
    aunque el editor esté colgado o crasheado."""
    path = Path(path)
    if not path.exists():
        return f"No existe el log en {path}. ¿El editor llegó a abrir alguna vez?"
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])
