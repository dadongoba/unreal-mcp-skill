import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ue_mcp import VERSION, runtime, updates
from ue_mcp.backends import discover, dispatch, inventory, select
from ue_mcp.bridge import Session
from ue_mcp.instances import InstanceError, Store
from ue_mcp.packages import Manager, NoStableRelease, atomic_json, latest
from ue_mcp.transport import Client, ToolError
from test_universal import initialized, rpc


def definition(name, properties):
    return {"name": name, "inputSchema": {"type": "object", "properties": properties}}


EPIC = definition("call_tool", {"tool_name": {"type": "string"}, "arguments": {"type": "object"}})
AVATAR = {"name": "unreal", "inputSchema": {"type": "object", "oneOf": [
    {"properties": {"action": {"const": action}}, "required": ["action"], "additionalProperties": False}
    for action in ("health", "discover", "execute", "task")]}}


class NativeServer:
    def __init__(self, tools):
        self.tools, self.calls = tools, []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = value["method"]
                if "id" not in value:
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    result = {"protocolVersion": "2025-03-26", "serverInfo": {"name": "test", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": parent.tools}
                else:
                    parent.calls.append(value["params"])
                    result = {"content": [{"type": "text", "text": "observed"}]}
                raw = json.dumps({"jsonrpc": "2.0", "id": value["id"], "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = "http://127.0.0.1:{}/mcp".format(self.server.server_port)

    def __enter__(self):
        self.worker.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()


class BackendTests(unittest.TestCase):
    def test_auto_detection_requires_a_unique_live_schema(self):
        self.assertEqual(select([EPIC], "auto"), "epic-toolsets")
        self.assertEqual(select([AVATAR], "auto"), "avatar-unreal")
        flat = definition("unreal", {"action": {"enum": ["health", "discover", "execute", "task"]}})
        self.assertEqual(select([flat], "auto"), "avatar-unreal")
        for items in ([], [EPIC, AVATAR], [definition("unreal", {})]):
            with self.assertRaises(ToolError):
                select(items, "auto")
        with self.assertRaises(ToolError):
            select([AVATAR], "epic-toolsets")

    def test_inventory_pagination_and_repeated_cursor_are_bounded(self):
        client = mock.Mock()
        client.request.side_effect = [{"tools": [EPIC], "nextCursor": "next"}, {"tools": [AVATAR]}]
        self.assertEqual(len(inventory(client)), 2)
        client.request.return_value = {"tools": [], "nextCursor": "loop"}
        client.request.side_effect = None
        with self.assertRaises(ToolError):
            inventory(client)
        self.assertEqual(client.request.call_count, 4)

    def test_malformed_schema_fails_without_sending_any_tool(self):
        for schema in ({"properties": []}, {"properties": {"action": None}},
                       {"properties": {"action": {"enum": None}}}):
            with self.assertRaises(ToolError):
                select([{"name": "unreal", "inputSchema": schema}], "auto")

    def test_two_http_backends_use_their_own_wire_contracts(self):
        with NativeServer([EPIC]) as epic, NativeServer([AVATAR]) as avatar:
            with Client(epic.url) as a, Client(avatar.url) as b:
                self.assertEqual(discover(a)["backend"], "epic-toolsets")
                self.assertFalse(discover(b)["epic_domain_guidance_applicable"])
                dispatch(a, "auto", "list_toolsets")
                dispatch(b, "auto", "unreal", {"action": "health"})
            self.assertEqual(epic.calls[0], {"name": "call_tool", "arguments": {"tool_name": "list_toolsets", "arguments": {}}})
            self.assertEqual(avatar.calls[0], {"name": "unreal", "arguments": {"action": "health"}})

    def test_native_backend_rejects_wrong_toolset_or_absent_tools_without_call(self):
        with NativeServer([AVATAR]) as endpoint, Client(endpoint.url) as client:
            for tool, toolset in (("unreal", "Epic.Toolset"), ("list_toolsets", None), ("invented", None)):
                with self.assertRaises(ToolError):
                    dispatch(client, "avatar-unreal", tool, {}, toolset)
            self.assertFalse(endpoint.calls)

    def test_managed_native_write_requires_identity_task_and_post_discovery_recheck(self):
        with tempfile.TemporaryDirectory() as root, NativeServer([AVATAR]) as endpoint:
            project = Path(root) / "Example.uproject"
            project.write_text("{}")
            store = Store(root)
            try:
                profile = store.register("a", project, endpoint.url, backend="auto")
                identity = {"pid": 1, "started": "one"}
                store.begin(profile, "task", identity)
                with mock.patch("ue_mcp.instances.process_identity", return_value=identity), \
                     mock.patch("ue_mcp.runtime.process_identity", return_value={"pid": 2}):
                    with self.assertRaises(InstanceError):
                        runtime.call(store, "unreal", {"action": "execute"}, "a", "task")
                    self.assertFalse(endpoint.calls)
                with mock.patch("ue_mcp.instances.process_identity", return_value=identity), \
                     mock.patch("ue_mcp.runtime.process_identity", return_value=identity):
                    with self.assertRaises(InstanceError):
                        runtime.call(store, "unreal", {"action": "health"}, "a")
                    runtime.call(store, "unreal", {"action": "health"}, "a", "task")
                    self.assertEqual(len(endpoint.calls), 1)
            finally:
                store.close()

    def test_toolset_named_like_discovery_cannot_bypass_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "Example.uproject"
            project.write_text("{}")
            store = Store(root)
            session = initialized(root)
            try:
                store.register("a", project)
                with self.assertRaises(InstanceError):
                    session.invoke("ue_call", {"instance": "a", "tool": "list_toolsets", "toolset": "Custom.Mutating"})
                with self.assertRaises(InstanceError):
                    runtime.call(store, "list_toolsets", instance="a", toolset="Custom.Mutating")
            finally:
                session.close()
                store.close()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {"UNREAL_MCP_UPDATE_CHECK": "on"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def release(self, version="99.0.0"):
        return ({"version": version, "repository": updates.REPOSITORY}, "https://github.com/test")

    def test_automatic_check_is_shared_cached_and_never_installs(self):
        with mock.patch.object(updates, "latest", return_value=self.release()) as network, \
             mock.patch.object(Manager, "install") as install:
            first = updates.check(self.home, now=100)
            second = updates.check(self.home, now=200)
            self.assertEqual(first["status"], "update_available")
            self.assertTrue(second["cached"])
            network.assert_called_once_with(timeout=5)
            install.assert_not_called()

    def test_force_refresh_and_24_hour_expiry(self):
        with mock.patch.object(updates, "latest", return_value=self.release()) as network:
            updates.check(self.home, now=100)
            updates.check(self.home, force=True, now=200)
            updates.check(self.home, now=200 + updates.TTL)
            self.assertEqual(network.call_count, 3)

    def test_concurrent_host_check_does_not_duplicate_network_request(self):
        store = Store(self.home)
        try:
            with store.file_lock("update-check"), mock.patch.object(updates, "latest") as network:
                self.assertEqual(updates.check(self.home)["status"], "unknown")
                network.assert_not_called()
        finally:
            store.close()

    def test_numeric_semver_current_ahead_and_update_are_distinct(self):
        atomic_json(self.home / "active.json", {"version": "3.9.0", "package": "3.9.0-aaaaaaaaaaaa"})
        with mock.patch.object(updates, "latest", return_value=self.release("3.10.0")):
            self.assertEqual(updates.check(self.home, force=True)["status"], "update_available")
        atomic_json(self.home / "active.json", {"version": "3.10.0", "package": "3.10.0-bbbbbbbbbbbb"})
        self.assertEqual(updates.check(self.home, offline=True)["status"], "current")
        atomic_json(self.home / "active.json", {"version": "3.11.0", "package": "3.11.0-cccccccccccc"})
        self.assertEqual(updates.check(self.home, offline=True)["status"], "ahead")

    def test_no_release_is_not_up_to_date_and_network_failure_is_unknown(self):
        with mock.patch.object(updates, "latest", side_effect=NoStableRelease("none")):
            self.assertEqual(updates.check(self.home)["status"], "unpublished")
        with mock.patch.object(updates, "latest", side_effect=OSError("offline")) as network:
            self.assertEqual(updates.check(self.home, force=True)["status"], "unknown")
            updates.check(self.home)
            self.assertEqual(network.call_count, 1)

    def test_stale_cache_cannot_claim_current_and_disabled_checks_do_not_network(self):
        with mock.patch.object(updates, "latest", return_value=self.release(VERSION)) as network:
            updates.check(self.home, now=100)
            result = updates.check(self.home, offline=True, now=100 + updates.TTL)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["last_known_status"], "current")
            with mock.patch.dict(os.environ, {"UNREAL_MCP_UPDATE_CHECK": "off"}):
                updates.check(self.home, now=100 + updates.TTL)
            network.assert_called_once()

    def test_running_process_detects_same_version_package_switch(self):
        atomic_json(self.home / "active.json", {"version": VERSION, "package": VERSION + "-aaaaaaaaaaaa"})
        value = updates.local(Manager(self.home), running_root=self.home / "packages" / (VERSION + "-bbbbbbbbbbbb"))
        self.assertTrue(value["reconnect_required"])
        self.assertFalse(updates.local(Manager(self.home), running_root=self.home / "packages" / (VERSION + "-aaaaaaaaaaaa"))["reconnect_required"])

    def test_mcp_status_and_explicit_check_expose_same_version_contract(self):
        session = initialized(self.home)
        try:
            with mock.patch.object(updates, "latest", return_value=self.release()):
                status = session.invoke("ue_status", {})
                explicit = session.invoke("ue_check_update", {"offline": True})
            self.assertEqual(status["update"]["status"], explicit["status"])
            self.assertIn("ue_capabilities", {t["name"] for t in rpc(session, "tools/list")["result"]["tools"]})
        finally:
            session.close()

    def test_release_archive_must_match_published_version(self):
        tag = "v3.19.0"
        base = "https://github.com/" + updates.REPOSITORY + "/releases/download/" + tag + "/"
        release = {"tag_name": tag, "assets": [{"name": "release.json", "browser_download_url": base + "release.json"},
                    {"name": "unreal-mcp-3.18.0.zip", "browser_download_url": base + "unreal-mcp-3.18.0.zip"}]}
        metadata = {"repository": updates.REPOSITORY, "version": "3.19.0", "contract_version": 1,
                    "archive": "unreal-mcp-3.18.0.zip", "sha256": "a" * 64}
        with mock.patch("ue_mcp.packages.download", side_effect=[json.dumps(release).encode(), json.dumps(metadata).encode()]):
            with self.assertRaises(ValueError):
                latest()


if __name__ == "__main__":
    unittest.main()
