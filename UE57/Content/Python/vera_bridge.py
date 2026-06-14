"""VERA Bridge — runs INSIDE the Unreal editor (auto-starts via init_unreal.py).

Listens on 127.0.0.1:9878. Receives {"script": "..."} (JSON + newline) and runs
the script on the editor's MAIN THREAD via a slate tick callback — touching the
`unreal` API from a network thread crashes the editor. Replies JSON + newline:
{"success": bool, "output": str, "error"?: str}.

Stdlib only. Runs in Unreal's embedded Python.
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

# The server-side timeout must be LONGER than the client's (ue_conn default 60s):
# for normal slow scripts the client times out first; this only catches real
# tick stalls (modal dialogs, long loads).
MAIN_THREAD_TIMEOUT = 120.0

# Queue of (task_id, script) toward the main thread; results keyed by task_id
_task_queue = queue.Queue()
_results = {}
_result_events = {}


def _execute_on_main_thread(task_id, script):
    """Runs on the main thread (called from the slate tick)."""
    output_lines = []
    import builtins

    original_print = builtins.print

    # Patching builtins.print is safe ONLY because the tick drains ONE task at a
    # time and runs synchronously on the main thread: there are never two
    # overlapping executions that would clobber original_print.
    def capture_print(*args, **kwargs):
        line = " ".join(str(a) for a in args)
        output_lines.append(line)
        unreal.log("[VERA] " + line)

    try:
        builtins.print = capture_print
        try:
            exec(script, {"unreal": unreal})  # noqa: S102
            result = {"success": True, "output": "\n".join(output_lines)}
        except Exception:
            result = {
                "success": False,
                "output": "\n".join(output_lines),
                "error": traceback.format_exc(),
            }
    finally:
        builtins.print = original_print

    event = _result_events.get(task_id)
    if event is not None:
        # Only publish if someone is still waiting: a task that finished after
        # the handler's timeout must not leave orphaned results behind.
        _results[task_id] = result
        event.set()


def slate_tick_callback(delta_time):
    """Registered on the slate post-tick: drains the queue on the main thread."""
    try:
        task_id, script = _task_queue.get_nowait()
    except queue.Empty:
        return
    _execute_on_main_thread(task_id, script)


def _handle_client(conn, addr):
    task_id = None
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

        if event.wait(timeout=MAIN_THREAD_TIMEOUT):
            result = _results.pop(task_id, None)
        else:
            result = {
                "success": None,
                "output": "",
                "error": "The editor did not process the script in %.0fs "
                         "(modal dialog open or long load?)." % MAIN_THREAD_TIMEOUT,
            }
        if result is None:
            result = {"success": False, "output": "", "error": "result lost"}

        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))
    except Exception as e:
        unreal.log_error("VERA Bridge error: " + str(e))
    finally:
        if task_id is not None:
            _results.pop(task_id, None)
            _result_events.pop(task_id, None)
        conn.close()


def _serve(server):
    while True:
        conn, addr = server.accept()
        threading.Thread(target=_handle_client, args=(conn, addr), daemon=True).start()


def start(port=PORT):
    """Starts the server on a daemon thread. Returns the real port (useful with port=0)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, port))
    server.listen(5)
    actual_port = server.getsockname()[1]
    threading.Thread(target=_serve, args=(server,), daemon=True).start()
    unreal.log("VERA Bridge listening on %s:%s (main-thread safe)" % (HOST, actual_port))
    return actual_port


if not os.environ.get("VERA_BRIDGE_NO_AUTOSTART"):
    unreal.register_slate_post_tick_callback(slate_tick_callback)
    start()
