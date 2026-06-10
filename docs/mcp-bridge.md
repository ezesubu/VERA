# VERA MCP Bridge — uso

Claude Code controla el editor de Unreal vía el server MCP `vera-ue` (registrado
en `.mcp.json`). Herramientas: `ue_exec`, `ue_screenshot`, `ue_log`, `ue_status`,
`vera_command`.

## Requisitos

1. Proyecto `UE57` abierto en el editor (el bridge auto-arranca vía
   `Content/Python/init_unreal.py`; requiere el plugin "Python Editor Script
   Plugin" habilitado).
   - Si el editor ya estaba abierto cuando se instaló el bridge, cargalo una
     vez a mano: en el Output Log, pestaña Python, ejecutar `import vera_bridge`.
2. `pip install -e .[dev]` en `E:\PCW\VERA` (instala `mcp`).
3. Opcional para `vera_command`: backend corriendo — `python -m vera.core.vera_server`.

## Seguridad

El bridge ejecuta Python ARBITRARIO sin autenticación en `127.0.0.1:9878`:
cualquier proceso local puede controlar el editor mientras esté abierto. Es un
diseño aceptado para herramienta de desarrollo local — no usar en máquinas
compartidas/multiusuario. Nunca cambiar el bind a `0.0.0.0`.

## Nota sobre el intérprete

`.mcp.json` usa la ruta ABSOLUTA de Python 3.14
(`C:/Users/ezesu/AppData/Local/Programs/Python/Python314/python.exe`): esta
máquina tiene varios `python.exe` en el PATH (incluido el stub de Microsoft
Store) y Claude Code lanza el server desde su propio entorno, no desde tu venv.
Si movés el proyecto a otra máquina, actualizá esa ruta.

## Smoke test (manual, con el editor abierto)

Desde una sesión de Claude Code en este repo (reiniciada para que cargue `.mcp.json`):

1. `ue_status` → bridge online, versión del engine visible.
2. `ue_exec("import unreal\nprint(unreal.SystemLibrary.get_engine_version())")`
   → imprime la versión.
3. `ue_screenshot()` → devuelve un PNG del viewport. ⚠️ Requiere que el editor
   tenga foco o esté renderizando (UE throttlea el render en background y la
   captura asíncrona no se materializa — limitación conocida, fix pendiente).
4. `ue_log(50)` → últimas líneas del Output Log.

## Test de aceptación — "loop con ojos"

Pedirle a Claude Code: *"Construí un puente de vidrio entre las dos plataformas
y verificá visualmente que quedó bien."* Claude debe: ejecutar scripts con
`ue_exec`, mirar el resultado con `ue_screenshot`, diagnosticar con `ue_log`
si algo falla, y corregir sin intervención del usuario.

## Variables de entorno

| Variable | Default | Para qué |
|---|---|---|
| `VERA_UE_PROJECT_DIR` | `<repo>/UE57` | Localiza `Saved/Logs` y `Saved/Screenshots` |
| `VERA_BRIDGE_PORT` | `9878` | Puerto del bridge en el editor |
| `VERA_BACKEND_PORT` | `9880` | Puerto del backend de agentes |
| `VERA_BRIDGE_NO_AUTOSTART` | (vacío) | Si está seteada, `vera_bridge` no auto-arranca (tests) |

## Detalles de comportamiento

- `ue_exec` es stateless: cada llamada usa un namespace nuevo (variables e
  imports no persisten entre llamadas).
- Si un script excede el timeout del cliente, el bridge NO lo aborta (el main
  thread de UE no se puede interrumpir); `ue_exec` devuelve `TIMEOUT:` y el
  script sigue corriendo. El bridge tiene su propio timeout de 120 s para
  stalls del tick (diálogos modales).
- Los screenshots se acumulan en `UE57/Saved/Screenshots/WindowsEditor/`
  (`vera_*.png`); limpieza pendiente como mejora futura.
