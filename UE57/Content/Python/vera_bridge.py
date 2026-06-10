"""VERA Bridge — corre DENTRO del editor de Unreal (auto-arranca vía init_unreal.py).

Escucha en 127.0.0.1:9878. Recibe {"script": "..."} (JSON + newline) y ejecuta
el script en el MAIN THREAD del editor vía slate tick callback — tocar la API
de `unreal` desde un hilo de red crashea el editor. Responde JSON + newline:
{"success": bool, "output": str, "error"?: str}.

Solo stdlib. Corre en el Python embebido de Unreal.
"""
import json
import os
import queue
import socket
import threading
import traceback
import uuid

import unreal

HOST = "127.0.0.1"
PORT = 9878

# Cola de (task_id, script) hacia el main thread; resultados por task_id
_task_queue = queue.Queue()
_results = {}
_result_events = {}


def _execute_on_main_thread(task_id, script):
    """Corre en el main thread (llamado desde el slate tick)."""
    output_lines = []
    import builtins

    original_print = builtins.print

    def capture_print(*args, **kwargs):
        line = " ".join(str(a) for a in args)
        output_lines.append(line)
        unreal.log("[VERA] " + line)

    try:
        builtins.print = capture_print
        try:
            exec(script, {"unreal": unreal})  # noqa: S102
            _results[task_id] = {"success": True, "output": "\n".join(output_lines)}
        except Exception:
            _results[task_id] = {
                "success": False,
                "output": "\n".join(output_lines),
                "error": traceback.format_exc(),
            }
    finally:
        builtins.print = original_print
        _result_events[task_id].set()


def slate_tick_callback(delta_time):
    """Registrado en el slate post-tick: drena la cola en el main thread."""
    try:
        task_id, script = _task_queue.get_nowait()
    except queue.Empty:
        return
    _execute_on_main_thread(task_id, script)


def _handle_client(conn, addr):
    try:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        payload = json.loads(data.decode("utf-8").strip())
        script = payload.get("script", "")

        task_id = str(uuid.uuid4())
        event = threading.Event()
        _result_events[task_id] = event
        _task_queue.put((task_id, script))

        # Espera al main thread (el cliente maneja su propio timeout)
        event.wait()
        result = _results.pop(task_id)
        _result_events.pop(task_id, None)

        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))
    except Exception as e:
        unreal.log_error("VERA Bridge error: " + str(e))
    finally:
        conn.close()


def _serve(server):
    while True:
        conn, addr = server.accept()
        threading.Thread(target=_handle_client, args=(conn, addr), daemon=True).start()


def start(port=PORT):
    """Arranca el server en un hilo daemon. Devuelve el puerto real (útil con port=0)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen(5)
    actual_port = server.getsockname()[1]
    threading.Thread(target=_serve, args=(server,), daemon=True).start()
    unreal.log("VERA Bridge escuchando en %s:%s (main-thread safe)" % (HOST, actual_port))
    return actual_port


if not os.environ.get("VERA_BRIDGE_NO_AUTOSTART"):
    unreal.register_slate_post_tick_callback(slate_tick_callback)
    start()
