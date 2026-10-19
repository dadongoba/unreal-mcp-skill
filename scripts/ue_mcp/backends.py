"""Backend dispatch is based on live schemas, never on the engine version alone."""
from .transport import ToolError

BACKENDS = ("epic-toolsets", "avatar-unreal", "native-mcp", "auto")


def properties(schema):
    value = schema.get("properties", {})
    if not isinstance(value, dict):
        raise ToolError("Invalid schema properties")
    return value


def action_values(schema):
    """Recognize both enum properties and discriminated oneOf/anyOf actions."""
    pending, result = [schema], set()
    for _ in range(100):
        if not pending:
            return result
        item = pending.pop()
        if not isinstance(item, dict):
            continue
        action = properties(item).get("action", {})
        if not isinstance(action, dict) or not isinstance(action.get("enum", []), list):
            raise ToolError("Invalid action schema")
        if isinstance(action.get("const"), str):
            result.add(action["const"])
        result.update(v for v in action.get("enum", []) if isinstance(v, str))
        for keyword in ("oneOf", "anyOf"):
            branches = item.get(keyword, [])
            if isinstance(branches, list):
                pending.extend(branches)
    raise ToolError("Action schema is too complex for automatic backend detection")


def inventory(client):
    tools, cursors = [], set()
    cursor = None
    for _ in range(20):
        page = client.request("tools/list", {"cursor": cursor} if cursor else {})
        if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
            raise ToolError("Invalid MCP tool inventory")
        for item in page["tools"]:
            if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                    or not isinstance(item.get("inputSchema"), dict)):
                raise ToolError("Invalid MCP tool definition")
            tools.append(item)
        if len(tools) > 2000:
            raise ToolError("MCP inventory exceeds 2000 tools")
        cursor = page.get("nextCursor")
        if not cursor:
            if len({t["name"] for t in tools}) != len(tools):
                raise ToolError("Duplicate MCP tool names")
            return tools
        if not isinstance(cursor, str) or cursor in cursors:
            raise ToolError("Invalid or repeated MCP inventory cursor")
        cursors.add(cursor)
    raise ToolError("MCP inventory exceeds 20 pages")


def select(tools, configured):
    if configured not in BACKENDS:
        raise ValueError("Unknown backend")
    by_name = {t["name"]: t for t in tools}
    matches = []
    epic = properties(by_name.get("call_tool", {}).get("inputSchema", {}))
    if {"tool_name", "arguments"}.issubset(epic):
        matches.append("epic-toolsets")
    avatar = by_name.get("unreal", {}).get("inputSchema", {})
    if {"health", "discover", "execute", "task"}.issubset(action_values(avatar)):
        matches.append("avatar-unreal")
    if configured == "auto":
        if len(matches) != 1:
            raise ToolError("Backend is unknown or ambiguous; choose an explicit supported backend after inspecting schemas")
        return matches[0]
    if configured != "native-mcp" and configured not in matches:
        raise ToolError("Configured backend disagrees with the live MCP schema; no UE call was sent")
    return configured


def discover(client, configured="auto"):
    tools = inventory(client)
    selected = select(tools, configured)
    return {"backend": selected, "tools": tools,
            "epic_domain_guidance_applicable": selected == "epic-toolsets",
            "verification": "live_schema_only",
            "note": "Tool presence is not engine-version or behavior certification. Inspect schemas before use."}


def dispatch(client, configured, tool, arguments=None, toolset=None, before_send=None):
    capabilities = discover(client, configured)
    backend = capabilities["backend"]
    if backend == "epic-toolsets":
        if before_send:
            before_send()
        return client.call(tool, arguments, toolset)
    if toolset:
        raise ToolError("This backend has no Epic Toolset namespace; use its discovered tool schema")
    if tool not in {t["name"] for t in capabilities["tools"]}:
        raise ToolError("Tool is absent from the selected endpoint's live inventory")
    if backend == "avatar-unreal" and tool != "unreal":
        raise ToolError("Avatar backend expects the unreal tool and its action arguments")
    if before_send:
        before_send()
    return client.request("tools/call", {"name": tool, "arguments": arguments or {}})
