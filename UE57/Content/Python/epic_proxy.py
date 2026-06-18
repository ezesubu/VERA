import sys
import json
import logging
import os

# Añadimos el path de VERA (este mismo directorio Content/Python) para poder importar
# su cliente MCP que maneja el protocolo custom de Epic. Relativo a __file__ para que
# sea portable (NO hardcodear la ruta de un proyecto/máquina concreta).
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from vera.mcp_client import EpicMCPClient

logging.basicConfig(filename=os.path.join(os.environ.get('TEMP', ''), 'epic_proxy.log'), level=logging.DEBUG)

def main():
    client = EpicMCPClient(None)
    # Sobrescribimos la URL dinámicamente si no encuentra el engine
    client.url = "http://127.0.0.1:8000/mcp"
    # Forzamos un handshake inicial con Epic para obtener el Mcp-Session-Id
    try:
        client.connect()
    except Exception as e:
        logging.error(f"Fallo al conectar con Epic MCP: {e}")

    while True:
        line = sys.stdin.readline()
        if not line:
            break
            
        try:
            req = json.loads(line)
            method = req.get("method")
            msg_id = req.get("id")
            
            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "EpicProxy", "version": "1.0"}
                    }
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
                
            elif method == "notifications/initialized":
                pass # Ignoramos
                
            elif method == "tools/list":
                tools = client.discover_tools()
                mcp_tools = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": getattr(t, 'input_schema', {"type": "object", "properties": {}})
                    } for t in tools
                ]
                res = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": mcp_tools}}
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
                
            elif method == "tools/call":
                name = req["params"]["name"]
                args = req["params"]["arguments"]
                tools = client.discover_tools()
                tool = next((t for t in tools if t.name == name), None)
                
                if tool:
                    result = tool.execute(args, None)
                    # ToolResult de VERA
                    is_err = getattr(result, 'is_error', False)
                    content = getattr(result, 'content', str(result))
                    res = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": content}],
                            "isError": is_err
                        }
                    }
                else:
                    res = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32601, "message": "Tool not found in Epic MCP"}
                    }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
                
        except Exception as e:
            logging.error(f"Error procesando: {e}")
            if "msg_id" in locals() and msg_id:
                res = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}}
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

if __name__ == '__main__':
    main()
