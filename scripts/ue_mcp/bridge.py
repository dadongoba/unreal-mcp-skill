"""Client-neutral MCP tools. A session owns its tasks, not other clients' tasks."""
import json
import sqlite3
import uuid

from . import VERSION
from .experience import ExperienceError, Queue, _validate
from .instances import InstanceError, Store, process_identity
from . import knowledge, runtime
from .backends import BACKENDS
from .updates import check as check_update
from .transport import MCPError, is_discovery, TransportError

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
INSTRUCTIONS = (
    "Start with ue_status for runtime/update status, then read ue_knowledge_read(path='SKILL.md'). "
    "Check ue_capabilities for a new backend; tool schemas are not behavior certification. Select/register the intended "
    "UE instance, begin a task, use ue_call with that task_id, verify the UE result, then "
    "ue_finish_task even on failure. Supply only a generic experience record when useful. "
    "Public contributions require the user's local opt-in. Unknown write outcomes must be "
    "read back before retrying. Client permissions and user authorization still apply.")


def text_rule(maximum=200):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def tool(name, description, properties=None, required=(), readonly=True):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties or {},
                            "required": list(required), "additionalProperties": False},
            "annotations": {"readOnlyHint": readonly, "destructiveHint": not readonly,
                            "openWorldHint": True}}


TOOLS = [
    tool("ue_status", "Runtime version, registered instances and contribution mode; no UE mutation."),
    tool("ue_register_instance", "Register an explicitly chosen local UE project and MCP port. Does not launch UE.",
         {"instance": text_rule(80), "project": text_rule(4096), "url": text_rule(2048),
          "engine": text_rule(4096), "backend": {"type": "string", "enum": list(BACKENDS)}},
         ("instance", "project", "url"), False),
    tool("ue_capabilities", "Inspect live backend schemas for a registered editor. Does not certify tool behavior or UE-version support.",
         {"instance": text_rule(80)}, ("instance",)),
    tool("ue_check_update", "Check the original repository's stable release, or read the shared cache. Never installs or activates updates.",
         {"force": {"type": "boolean"}, "offline": {"type": "boolean"}}),
    tool("ue_begin_task", "Verify the editor process and acquire exclusive instance/project ownership. Returns a new task_id.",
         {"instance": text_rule(80)}, ("instance",), False),
    tool("ue_call", "Call a UE tool by discovered name/toolset. All non-discovery tools require this session's task_id. Never blindly retry UNKNOWN writes.",
         {"instance": text_rule(80), "task_id": text_rule(80), "tool": text_rule(300),
          "toolset": text_rule(400), "arguments": {"type": "object"},
          "timeout": {"type": "integer"}}, ("instance", "tool"), False),
    tool("ue_finish_task", "Complete a task and release its locks. Optionally retain a generic experience.v1 record; upload only under saved user consent. Omit record when no useful lesson exists.",
         {"task_id": text_rule(80), "record": {"type": "object"}}, ("task_id",), False),
    tool("ue_knowledge_search", "Search published UE guidance; incoming unreviewed submissions are excluded.",
         {"query": text_rule(200), "limit": {"type": "integer"}}, ("query",)),
    tool("ue_knowledge_read", "Read SKILL.md, a published reference, template or experience schema. Paginated text; paths come from search.",
         {"path": text_rule(400), "offset": {"type": "integer"}, "limit": {"type": "integer"}}),
    tool("ue_experience_status", "Contribution mode and local queue counts; never enables public uploading."),
]


class RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Session:
    def __init__(self, state_dir=None):
        self.state_dir = state_dir
        self.owner = str(uuid.uuid4())
        self.protocol = None
        self.initialized = False

    def store(self):
        store = Store(self.state_dir)
        store.db.execute("CREATE TABLE IF NOT EXISTS bridge_tasks(task TEXT PRIMARY KEY, owner TEXT NOT NULL)")
        store.db.commit()
        return store

    def owned(self, store, task_id):
        row = store.db.execute("SELECT owner FROM bridge_tasks WHERE task=?", (task_id,)).fetchone()
        if not row or row["owner"] != self.owner:
            raise InstanceError("Task does not belong to this MCP session; begin a task in this session")

    def close(self):
        store = self.store()
        try:
            for row in store.db.execute("SELECT task FROM bridge_tasks WHERE owner=?", (self.owner,)):
                store.end(row["task"])
            with store.db:
                store.db.execute("DELETE FROM bridge_tasks WHERE owner=?", (self.owner,))
        finally:
            store.close()

    def invoke(self, name, args):
        definition = next((t for t in TOOLS if t["name"] == name), None)
        if definition is None:
            raise RPCError(-32602, "Unknown tool")
        try:
            _validate(args, definition["inputSchema"], "arguments")
        except ExperienceError as error:
            raise RPCError(-32602, str(error)) from error
        if name == "ue_knowledge_read":
            return knowledge.read(**args)
        if name == "ue_knowledge_search":
            return knowledge.search(**args)
        store = self.store()
        try:
            if name == "ue_status":
                return {"version": VERSION, "contract_version": 1,
                        "instances": list(store.profiles().values()),
                        "experience": Queue(store).config(), "instructions": INSTRUCTIONS,
                        "update": check_update(store.root)}
            if name == "ue_check_update":
                return check_update(store.root, **args)
            if name == "ue_capabilities":
                return runtime.capabilities(store, args["instance"])
            if name == "ue_experience_status":
                queue = Queue(store)
                return {"config": queue.config(), "counts": {
                    row["status"]: row["count"] for row in store.db.execute(
                        "SELECT status,COUNT(*) AS count FROM contributions GROUP BY status")}}
            if name == "ue_register_instance":
                return store.register(args["instance"], args["project"], args["url"], args.get("engine"),
                                      args.get("backend", "epic-toolsets"))
            if name == "ue_begin_task":
                profile = store.resolve(args["instance"])
                task_id = str(uuid.uuid4())
                store.begin(profile, task_id, process_identity(profile["url"], profile["project"]))
                try:
                    with store.db:
                        store.db.execute("INSERT INTO bridge_tasks VALUES(?,?)", (task_id, self.owner))
                except BaseException:
                    store.end(task_id)
                    raise
                return {"task_id": task_id, "instance": profile["name"], "lease_seconds": 900}
            if name == "ue_call":
                task_id = args.get("task_id")
                if task_id or not is_discovery(args["tool"], args.get("toolset")):
                    self.owned(store, task_id)
                return {"result": runtime.call(store, **args)}
            if name == "ue_finish_task":
                self.owned(store, args["task_id"])
                return runtime.finalize(store, args["task_id"], args.get("record"))
            raise RPCError(-32602, "Unknown tool")
        finally:
            store.close()

    def handle(self, message):
        request_id = message.get("id") if isinstance(message, dict) else None
        try:
            if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
                    or not isinstance(message.get("method"), str)
                    or "id" in message and (isinstance(request_id, bool)
                        or not isinstance(request_id, (str, int)))):
                raise RPCError(-32600, "Invalid JSON-RPC request")
            method, params = message["method"], message.get("params", {})
            if not isinstance(params, dict):
                raise RPCError(-32602, "Params must be an object")
            if "id" not in message:
                if method == "notifications/initialized" and self.protocol:
                    self.initialized = True
                return None
            if method == "initialize":
                if self.protocol:
                    raise RPCError(-32600, "Session already initialized")
                requested = params.get("protocolVersion")
                if not isinstance(requested, str) or not isinstance(params.get("clientInfo"), dict):
                    raise RPCError(-32602, "Initialize requires protocolVersion and clientInfo")
                self.protocol = requested if requested in PROTOCOLS else PROTOCOLS[-1]
                result = {"protocolVersion": self.protocol, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "unreal-mcp", "version": VERSION},
                          "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif not self.initialized:
                raise RPCError(-32000, "Initialize the MCP session before using tools")
            elif method == "tools/list":
                if params.get("cursor"):
                    raise RPCError(-32602, "No further tool pages")
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    value = self.invoke(params.get("name"), params.get("arguments", {}))
                    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                              "isError": False}
                    if self.protocol >= "2025-06-18":
                        result["structuredContent"] = value
                except (MCPError, InstanceError, ExperienceError, ValueError, OSError, sqlite3.Error) as error:
                    result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
                    if (isinstance(error, TransportError) and params.get("name") == "ue_call"
                            and not is_discovery(params.get("arguments", {}).get("tool"),
                                                 params.get("arguments", {}).get("toolset"))):
                        result["content"][0]["text"] += "; outcome may be UNKNOWN; read back before retrying a write"
            else:
                raise RPCError(-32601, "Method not found")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RPCError as error:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": error.code, "message": error.message}}
