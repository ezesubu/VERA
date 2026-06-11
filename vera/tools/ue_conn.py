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
    try:
        return json.loads(buf.decode("utf-8").strip())
    except ValueError as e:
        raise UEConnectionError(f"respuesta malformada del servidor: {e}") from e


def send_json_stream(port, payload, timeout=DEFAULT_TIMEOUT, host="127.0.0.1", on_event=None):
    """Envía un payload y lee un STREAM de líneas JSON hasta el evento
    {"type":"final"} (o cierre de conexión). Devuelve la lista de eventos.
    on_event(evento) se invoca por cada línea a medida que llega."""
    events = []
    s = None
    try:
        # Two-phase connect: separate timeout handling for connect vs. stream (Windows compat)
        try:
            s = socket.create_connection((host, port), timeout=timeout)
        except socket.timeout as e:
            raise UEConnectionError(f"sin respuesta al conectar en {timeout:.0f}s") from e
        except OSError as e:
            raise UEConnectionError(str(e)) from e

        # Connection established; stream with timeout
        s.settimeout(timeout)
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    event = json.loads(line.decode("utf-8"))
                except ValueError as e:
                    raise UEConnectionError(f"evento malformado: {e}") from e
                events.append(event)
                if on_event is not None:
                    try:
                        on_event(event)
                    except Exception:
                        pass
                if event.get("type") == "final":
                    return events
    except UEConnectionError:
        raise
    except socket.timeout as e:
        raise UETimeoutError(f"stream sin final en {timeout:.0f}s") from e
    except OSError as e:
        raise UEConnectionError(str(e)) from e
    finally:
        if s:
            s.close()

    if not events:
        raise UEConnectionError("el servidor cerró sin enviar eventos")
    return events
