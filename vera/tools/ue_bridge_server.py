"""
VERA UE Bridge Server — Runs INSIDE Unreal Engine's Python console.

SETUP INSTRUCTIONS:
1. In Unreal Editor: Edit > Plugins → Enable "Python Editor Script Plugin"
2. In Unreal Editor: Edit > Editor Preferences → Python → Enable Remote Execution
3. Open the Output Log (Window > Output Log)
4. In the Python tab at the bottom, paste and run this entire script.
5. VERA will now be able to call the UE Python API directly.

This server listens on localhost:9877 for JSON script payloads from VERA.
"""

import json
import socket
import threading
import traceback

import unreal

HOST = "127.0.0.1"
PORT = 9877


def handle_client(conn: socket.socket, addr) -> None:
    unreal.log(f"VERA Bridge: connection from {addr}")
    try:
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if data.endswith(b"\n"):
                break

        payload = json.loads(data.decode("utf-8").strip())
        script = payload.get("script", "")

        # Execute the script in UE's Python context
        output_lines = []
        original_log = unreal.log

        try:
            # Redirect print to capture output
            import builtins
            original_print = builtins.print

            def capture_print(*args, **kwargs):
                line = " ".join(str(a) for a in args)
                output_lines.append(line)
                unreal.log(f"[VERA] {line}")

            builtins.print = capture_print
            exec(script, {"unreal": unreal})  # noqa: S102
            builtins.print = original_print

            response = json.dumps({
                "success": True,
                "output": "\n".join(output_lines),
            })
        except Exception as e:
            response = json.dumps({
                "success": False,
                "output": "\n".join(output_lines),
                "error": traceback.format_exc(),
            })

        conn.sendall(response.encode("utf-8"))
    except Exception as e:
        unreal.log_error(f"VERA Bridge error: {e}")
    finally:
        conn.close()


def start_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    unreal.log(f"VERA Bridge listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        thread.start()


# Start in background thread so UE editor stays responsive
bridge_thread = threading.Thread(target=start_server, daemon=True)
bridge_thread.start()
unreal.log("✅ VERA Python Bridge started successfully. Ready for commands.")
