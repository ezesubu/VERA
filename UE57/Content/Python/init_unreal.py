"""Unreal ejecuta este archivo automáticamente al abrir el proyecto
(convención init_unreal.py del Python Editor Script Plugin)."""
import unreal

# QtWebEngine exige este flag ANTES de crear cualquier QApplication.
# Se setea acá (arranque del editor) para que open_vera_ui lo herede.
try:
    from PySide6.QtCore import Qt, QCoreApplication
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
except ImportError:
    pass  # PySide6 se instala on-demand al abrir la UI por primera vez

try:
    import vera_bridge  # noqa: F401  — TCP bridge para Claude Code/VERA (puerto 9878)
except Exception as e:
    unreal.log_error("[VERA] No se pudo iniciar el bridge: " + str(e))

try:
    import vera_ui  # noqa: F401  — inyecta el botón VERA en la toolbar
except Exception as e:
    unreal.log_error("[VERA] No se pudo cargar la UI: " + str(e))
