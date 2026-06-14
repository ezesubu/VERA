import socket
import json
import time

def test_heartbeat():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", 9878))
        print("🔌 Connected to VERA Bridge at 127.0.0.1:9878!")
        
        # We simulate a "heavy task" by sleeping for 12 seconds in Unreal's main thread.
        # Without stream=True, the client might timeout. With stream=True, we should see heartbeats every 5s.
        payload = {
            "script": "import time\nunreal.log('VERA: Starting 12s heavy task...')\ntime.sleep(12)\nprint('Heavy task completed!')",
            "stream": True
        }
        
        print("📤 Sending heavy task (12 seconds sleep) with stream=True...")
        start_time = time.time()
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        print("⏳ Waiting for stream...\n")
        
        buffer = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                msg = json.loads(line.decode("utf-8"))
                
                if msg.get("type") == "heartbeat":
                    elapsed = time.time() - start_time
                    print(f"💓 [HEARTBEAT] Bridge is alive! Editor is crunching... (Waited: {msg.get('waited')}s)")
                elif msg.get("type") == "final":
                    print(f"\n✅ [FINAL RESULT]")
                    print(f"Output:\n{msg.get('output')}")
                    return
                else:
                    print(f"❓ [UNKNOWN] {msg}")
                    
    except ConnectionRefusedError:
        print("❌ Editor is not running or VERA Bridge is not active on 9878.")
        print("Please ensure your PCWMaster 4.3 project is open and has loaded the new vera_bridge.py!")

if __name__ == "__main__":
    test_heartbeat()
