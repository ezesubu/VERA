"""Cliente TCP newline-framed para el bridge de Unreal (9878) y el backend VERA (9880)."""
import json
import socket

DEFAULT_TIMEOUT = 60.0


class UEConnectionError(RuntimeError):
    """No se pudo conectar: editor cerrado o bridge/backend no cargado."""


class UETimeoutError(RuntimeError):
    """El destino aceptó la conexión pero no respondió a tiempo."""


def send_json(port, payload, timeout=DEFAULT_TIMEOUT, host="127.0.0.1"):
    """Envía un dict como JSON + '\\n' y lee una respuesta JSON terminada en '\\n'."""
    s = None
    try:
        # Attempt connection (may timeout on closed ports)
        try:
            s = socket.create_connection((host, port), timeout=timeout)
        except socket.timeout as e:
            raise UEConnectionError(f"sin respuesta al conectar en {timeout:.0f}s") from e
        except OSError as e:
            raise UEConnectionError(str(e)) from e

        # Connection established; now do data exchange with timeout
        s.settimeout(timeout)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except (UEConnectionError, UETimeoutError):
        raise
    except socket.timeout as e:
        raise UETimeoutError(f"sin respuesta en {timeout:.0f}s") from e
    except OSError as e:
        raise UEConnectionError(str(e)) from e
    finally:
        if s:
            s.close()

    if not buf.strip():
        raise UEConnectionError("el servidor cerró la conexión sin responder")
    return json.loads(buf.decode("utf-8").strip())
