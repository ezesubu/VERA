"""Newline-framed TCP client for the Unreal bridge (9878) and the VERA backend (9880)."""
import json
import socket

DEFAULT_TIMEOUT = 60.0


class UEConnectionError(RuntimeError):
    """Could not connect: editor closed or bridge/backend not loaded."""


class UETimeoutError(RuntimeError):
    """The target accepted the connection but did not respond in time."""


def send_json(port, payload, timeout=DEFAULT_TIMEOUT, host="127.0.0.1"):
    """Sends a dict as JSON + '\\n' and reads a JSON response terminated by '\\n'."""
    s = None
    try:
        # Attempt connection (may timeout on closed ports)
        try:
            s = socket.create_connection((host, port), timeout=timeout)
        except socket.timeout as e:
            raise UEConnectionError(f"no response while connecting within {timeout:.0f}s") from e
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
        raise UETimeoutError(f"no response within {timeout:.0f}s") from e
    except OSError as e:
        raise UEConnectionError(str(e)) from e
    finally:
        if s:
            s.close()

    if not buf.strip():
        raise UEConnectionError("the server closed the connection without responding")
    try:
        return json.loads(buf.decode("utf-8").strip())
    except ValueError as e:
        raise UEConnectionError(f"malformed response from the server: {e}") from e


def send_json_stream(port, payload, timeout=DEFAULT_TIMEOUT, host="127.0.0.1", on_event=None):
    """Sends a payload and reads a STREAM of JSON lines until the
    {"type":"final"} event (or connection close). Returns the list of events.
    on_event(event) is invoked for each line as it arrives."""
    events = []
    s = None
    try:
        # Two-phase connect: separate timeout handling for connect vs. stream (Windows compat)
        try:
            s = socket.create_connection((host, port), timeout=timeout)
        except socket.timeout as e:
            raise UEConnectionError(f"no response while connecting within {timeout:.0f}s") from e
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
                    raise UEConnectionError(f"malformed event: {e}") from e
                events.append(event)
                if on_event is not None:
                    try:
                        on_event(event)
                    except Exception:
                        # on_event is best-effort: a broken callback must not abort the stream
                        pass
                if event.get("type") == "final":
                    return events
    except UEConnectionError:
        raise
    except socket.timeout as e:
        raise UETimeoutError(f"stream without a final event within {timeout:.0f}s") from e
    except OSError as e:
        raise UEConnectionError(str(e)) from e
    finally:
        if s:
            s.close()

    if not events:
        raise UEConnectionError("the server closed without sending any events")
    return events
