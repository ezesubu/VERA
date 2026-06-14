"""
Starts vera_server on a separate thread inside the editor.
Loaded automatically from init_unreal.py.
"""
import threading
import sys
import os

# Add VERA to the path so it imports correctly
vera_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if vera_root not in sys.path:
    sys.path.insert(0, vera_root)

def launch_vera_server():
    """Starts vera_server in the background"""
    try:
        from vera.core.vera_server import VeraServer
        server = VeraServer()
        print(f"[VERA] Starting vera_server on {server.host}:{server.port}")
        server.start()
    except Exception as e:
        print(f"[VERA] Error launching vera_server: {e}")

# Start on a daemon thread (does not block the editor)
thread = threading.Thread(target=launch_vera_server, daemon=True)
thread.start()
print("[VERA] vera_server thread started in background")
