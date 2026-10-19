"""Independent MCP sessions, JSON/SSE responses, and explicit failures.

Requests are never automatically replayed: a failed write may have executed.
"""
import json
import urllib.error
import urllib.request

from . import VERSION

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
READ_TOOLS = frozenset({"list_toolsets", "describe_toolset"})
MAX_RESPONSE = 16 * 1024 * 1024


class MCPError(RuntimeError):
    pass


class TransportError(MCPError):
    pass


class ToolError(MCPError):
    def __init__(self, message, result=None):
        self.result = result
        super().__init__(message)


def tool_error(message, value):
    details = "\n".join(item.get("text", "") for item in value.get("content", [])
                        if isinstance(item, dict) and item.get("type") == "text")
    return ToolError(message + (": " + details[:2000] if details else ""), value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError("MCP redirects are refused; verify the configured endpoint")


def check_result(value):
    if isinstance(value, dict):
        if value.get("isError") is True:
            raise tool_error("UE reported isError=true", value)
        for item in value.get("content", []):
            if item.get("type") == "text":
                try:
                    nested = json.loads(item.get("text", ""))
                except (ValueError, TypeError):
                    continue
                if isinstance(nested, dict) and nested.get("isError") is True:
                    raise tool_error("UE returned a nested tool error", value)
    return value


class Client:
    def __init__(self, url=DEFAULT_URL, timeout=120):
        self.url = url
        self.timeout = timeout
        self.sid = None
        self.protocol = None
        self.sequence = 0
        self.opener = urllib.request.build_opener(NoRedirect())

    def _exchange(self, payload, timeout=None):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as response:
                sid = response.headers.get("Mcp-Session-Id")
                if sid and payload.get("method") == "initialize":
                    self.sid = sid
                if "id" not in payload:
                    if response.status not in (200, 202, 204):
                        raise TransportError("Notification was not accepted")
                    return None
                if response.headers.get_content_type() == "text/event-stream":
                    message = self._sse(response, payload["id"])
                else:
                    data = response.read(MAX_RESPONSE + 1)
                    if len(data) > MAX_RESPONSE:
                        raise TransportError("MCP response exceeds the size limit")
                    message = json.loads(data.decode("utf-8-sig"))
        except MCPError:
            raise
        except (OSError, ValueError) as error:
            raise TransportError("MCP transport failed ({}); request was not replayed".format(
                type(error).__name__)) from error
        if not isinstance(message, dict) or message.get("id") != payload["id"]:
            raise TransportError("MCP response has an unexpected request ID")
        if "error" in message:
            raise ToolError("JSON-RPC error {}".format(message["error"].get("code", "unknown")))
        if "result" not in message:
            raise TransportError("MCP response has no result")
        return check_result(message["result"])

    @staticmethod
    def _sse(response, request_id):
        parts, total = [], 0
        for raw in response:
            total += len(raw)
            if total > MAX_RESPONSE:
                raise TransportError("SSE response exceeds the size limit")
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                parts.append(line[5:].lstrip(" "))
            elif not line and parts:
                data, parts = "\n".join(parts), []
                if not data.strip():
                    continue
                message = json.loads(data)
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
        if parts:
            message = json.loads("\n".join(parts))
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
        raise TransportError("SSE ended without the requested response")

    def request(self, method, params=None, timeout=None):
        self.sequence += 1
        return self._exchange({"jsonrpc": "2.0", "id": self.sequence,
                               "method": method, "params": params or {}}, timeout)

    def connect(self):
        self.sid, self.protocol = None, None
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "unreal-mcp-skill", "version": VERSION}}, timeout=10)
        if not isinstance(result, dict) or not isinstance(result.get("protocolVersion"), str):
            raise TransportError("Endpoint did not return an MCP initialize result")
        self.protocol = result["protocolVersion"]
        self._exchange({"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=5)
        return self

    def call(self, tool, arguments=None, toolset=None):
        inner = {"tool_name": tool, "arguments": arguments or {}}
        if toolset:
            inner["toolset_name"] = toolset
        return self.request("tools/call", {"name": "call_tool", "arguments": inner})

    def close(self):
        if not self.sid:
            return
        req = urllib.request.Request(self.url, method="DELETE", headers={
            "Mcp-Session-Id": self.sid, "MCP-Protocol-Version": self.protocol})
        try:
            with self.opener.open(req, timeout=2):
                pass
        except (OSError, MCPError):
            pass
        self.sid = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *args):
        self.close()
