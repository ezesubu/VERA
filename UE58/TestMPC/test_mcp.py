import sys
import json
import logging
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO)

def main():
    print("Testing connection to Epic MCP Server...")
    
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "VERA Test",
                "version": "1.0.0"
            }
        }
    }

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/mcp", 
            data=json.dumps(init_payload).encode("utf-8"), 
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10.0)
        session_id = resp.getheader("Mcp-Session-Id")
        resp_body = resp.read().decode("utf-8")
        
        print(f"Initialize Response: {resp_body}")
        print(f"Session ID: {session_id}")
        
        if not session_id:
            print("No session ID returned!")
            return

        notif_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        
        req_notif = urllib.request.Request(
            "http://127.0.0.1:8000/mcp", 
            data=json.dumps(notif_payload).encode("utf-8"), 
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id
            },
            method="POST"
        )
        urllib.request.urlopen(req_notif, timeout=10.0)

        list_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        
        req_list = urllib.request.Request(
            "http://127.0.0.1:8000/mcp", 
            data=json.dumps(list_payload).encode("utf-8"), 
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id
            },
            method="POST"
        )
        list_resp = urllib.request.urlopen(req_list, timeout=10.0)
        list_body = list_resp.read().decode("utf-8")
        print("\n--- Tools ---")
        tools_data = json.loads(list_body)
        tools = tools_data.get("result", {}).get("tools", [])
        for t in tools:
            print(f" - {t['name']}: {t['description']}")
            
        print("\n--- Testing list_toolsets ---")
        call_payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "list_toolsets",
                "arguments": {}
            }
        }
        req_call = urllib.request.Request(
            "http://127.0.0.1:8000/mcp", 
            data=json.dumps(call_payload).encode("utf-8"), 
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id
            },
            method="POST"
        )
        
        call_resp = urllib.request.urlopen(req_call, timeout=10.0)
        call_body = call_resp.read().decode("utf-8")
        
        # NOTE: Epic MCP responds with SSE to tools/call, so call_body will be SSE text
        print(f"Raw Output:\n{call_body}")

    except urllib.error.URLError as e:
        print(f"Failed to connect to Unreal Engine MCP. Is it running? {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
