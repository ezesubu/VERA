import json
import logging
import http.client
from urllib.parse import urlparse
import threading
from typing import List, Any
from vera.agent.tool import Tool, ToolResult

logger = logging.getLogger(__name__)

class EpicMCPClient:
    """
    Custom HTTP Middleware for Epic Games' Experimental MCP Server.
    Bypasses standard MCP SSE transport in favor of stateless JSON-RPC POST requests
    as mandated by Unreal Engine 5.8's implementation.
    """
    def __init__(self, repo_root: str):
        self.url = "http://127.0.0.1:8000/mcp" # Fallback default
        self._connected = False
        self._session_id = None
        self._next_id = 1
        self._lock = threading.Lock()

    def _get_id(self) -> int:
        with self._lock:
            curr = self._next_id
            self._next_id += 1
            return curr

    @staticmethod
    def _extract_jsonrpc(body: str):
        """Epic answers with either plain JSON or an SSE frame
        ('event: message\\ndata: {...}'). Pull the JSON-RPC object out of either."""
        if not body:
            return None
        body = body.strip()
        if body.startswith("{"):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                pass
        result = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                    if "result" in obj or "error" in obj or "id" in obj:
                        result = obj
                except json.JSONDecodeError:
                    pass
        return result

    def _post(self, payload: dict, stream: bool = False) -> Any:
        # Unreal 5.8's MCP answers tools/call with an SSE frame that carries NO
        # Content-Length and keeps the socket alive; urllib.urlopen reads that as
        # 0 bytes. http.client reads the buffered body correctly, so use it.
        parsed = urlparse(self.url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8000
        path = parsed.path or "/mcp"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        conn = http.client.HTTPConnection(host, port, timeout=300.0)
        try:
            conn.request("POST", path, json.dumps(payload).encode("utf-8"), headers)
            resp = conn.getresponse()
            status = resp.status
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            body = resp.read().decode("utf-8")
        except Exception as e:
            logger.error(f"Epic MCP Network Error: {e}")
            raise RuntimeError(f"Network Error: {e}")
        finally:
            conn.close()

        new_session_id = resp_headers.get("mcp-session-id")
        if new_session_id and not self._session_id:
            self._session_id = new_session_id

        if status >= 400:
            logger.error(f"Epic MCP HTTP Error {status}: {body}")
            raise RuntimeError(f"HTTP {status}: {body}")

        # 'stream' callers parse the SSE body themselves; hand back the raw text.
        if stream:
            return body
        return self._extract_jsonrpc(body)

    def connect(self, probe_settings: bool = True) -> bool:
        """Initializes the connection with Unreal Engine's MCP server.

        probe_settings reads the port/path from Unreal's CDO — that touches the
        `unreal` API and is ONLY safe on the game thread. Callers on a worker
        thread must pass probe_settings=False and set `self.url` beforehand."""
        if self._connected:
            return True

        if probe_settings:
            try:
                import unreal
                cls = unreal.load_class(None, "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings")
                if not cls:
                    # Plugin not installed (e.g. UE 5.7) or not enabled. Abort cleanly.
                    return False

                settings = unreal.get_default_object(cls)
                port = settings.get_editor_property("ServerPortNumber")
                url_path = settings.get_editor_property("ServerUrlPath")
                self.url = f"http://127.0.0.1:{port}{url_path}"
            except Exception as e:
                logger.warning(f"Could not read dynamic MCP settings, using fallback: {e}")

        # Perform JSON-RPC Initialize Handshake
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._get_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "VERA",
                    "version": "1.0.0"
                }
            }
        }

        try:
            init_result = self._post(init_payload)
            if not self._session_id:
                logger.error("Epic MCP server did not return an Mcp-Session-Id header.")
                return False

            # Send initialized notification
            notif_payload = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {}
            }
            self._post(notif_payload)
            self._connected = True
            logger.info(f"Connected to Epic MCP server dynamically at {self.url} with Session ID: {self._session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Epic MCP: {e}")
            return False

    def discover_tools(self) -> List[Tool]:
        """Discovers tools from Epic's MCP server via HTTP and wraps them."""
        if not self._connected:
            return []
        
        payload = {
            "jsonrpc": "2.0",
            "id": self._get_id(),
            "method": "tools/list",
            "params": {}
        }

        try:
            result = self._post(payload)
            if "error" in result:
                logger.error(f"Error fetching tools: {result['error']}")
                return []
                
            mcp_tools = result.get("result", {}).get("tools", [])
        except Exception as e:
            logger.error(f"Failed to list Epic MCP tools: {e}")
            return []
            
        tools = []
        for t in mcp_tools:
            tool_name = t.get("name")
            if not tool_name: continue

            class DynamicEpicTool(Tool):
                name = tool_name
                description = t.get("description", "Epic Native MCP Tool")
                input_schema = t.get("inputSchema", {})
                destructive = False
                
                _tool_name = tool_name
                _client = self

                def execute(self, args: dict, ctx: Any) -> ToolResult:
                    call_payload = {
                        "jsonrpc": "2.0",
                        "id": self._client._get_id(),
                        "method": "tools/call",
                        "params": {
                            "name": self._tool_name,
                            "arguments": args
                        }
                    }
                    try:
                        # tools/call returns an SSE frame; _post hands back the raw text.
                        resp_body = self._client._post(call_payload, stream=True)
                        final_json = self._client._extract_jsonrpc(resp_body)

                        if not final_json:
                            return ToolResult(content=f"Epic MCP tool executed but returned no valid result. Raw: {resp_body[:500] if resp_body else 'empty'}", is_error=True)

                        if "error" in final_json:
                            err_msg = final_json["error"].get("message", str(final_json["error"]))
                            return ToolResult(content=f"Epic MCP Error: {err_msg}", is_error=True)

                        result_obj = final_json.get("result", {})
                        if "content" in result_obj:
                            content_arr = result_obj["content"]
                            output = []
                            for item in content_arr:
                                if item.get("type") == "text":
                                    output.append(item.get("text", ""))
                                else:
                                    output.append(f"[{item.get('type')} content]")
                            final_text = "\n".join(output) if output else "Success (no output)"
                        else:
                            final_text = json.dumps(result_obj)
                            
                        return ToolResult(content=final_text)
                    except Exception as e:
                        return ToolResult(content=f"Epic MCP Execution Error: {e}", is_error=True)

            tools.append(DynamicEpicTool())
        return tools
