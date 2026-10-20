import copy
import hashlib
import http.client
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ue_mcp import VERSION, knowledge
from ue_mcp.bridge import Session
from ue_mcp.instances import InstanceError, Store
from ue_mcp.packages import Manager, ROOT, build, digest, verify
from ue_mcp.server import HTTPServer, stdio
from curate_experience import promote, propose
from test_runtime import MCPServer, record


def rpc(session, method, params=None):
    return session.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def initialized(root, protocol="2025-11-25"):
    session = Session(root)
    rpc(session, "initialize", {"protocolVersion": protocol, "clientInfo": {"name": "generic", "version": "1"}})
    session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return session


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.project = self.root / "Example.uproject"
        self.project.write_text("{}")
        self.profile = self.store.register("test", self.project, "http://127.0.0.1:8011/mcp")
        self.identity = {"pid": 12, "started": "generation", "project": str(self.project)}
        self.session = initialized(self.root)

    def tearDown(self):
        self.session.close()
        self.store.close()
        self.tmp.cleanup()

    def begin(self):
        with mock.patch("ue_mcp.bridge.process_identity", return_value=self.identity):
            return self.session.invoke("ue_begin_task", {"instance": "test"})["task_id"]

    def test_arbitrary_clients_negotiate_versions_and_discover_same_tools(self):
        for version in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"):
            session = initialized(self.root, version)
            self.assertEqual(session.protocol, version)
            names = {tool["name"] for tool in rpc(session, "tools/list")["result"]["tools"]}
            self.assertIn("ue_finish_task", names)
            self.assertIn("ue_knowledge_read", names)
            session.close()

    def test_uninitialized_client_and_unknown_parameters_are_rejected(self):
        self.assertIn("error", rpc(Session(self.root), "tools/list"))
        value = rpc(self.session, "tools/call", {"name": "ue_status", "arguments": {"extra": True}})
        self.assertEqual(value["error"]["code"], -32602)

    def test_another_session_cannot_use_or_finish_owned_task(self):
        task = self.begin()
        other = initialized(self.root)
        for name, args in (("ue_finish_task", {"task_id": task}),
                           ("ue_call", {"task_id": task, "instance": "test", "tool": "mutate"})):
            with self.assertRaises(InstanceError):
                other.invoke(name, args)
        self.assertEqual(self.store.db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0], "active")
        other.close()

    def test_finish_has_no_fabricated_experience_and_is_repeatable(self):
        task = self.begin()
        self.assertEqual(self.session.invoke("ue_finish_task", {"task_id": task}), {"status": "no_experience"})
        self.assertEqual(self.session.invoke("ue_finish_task", {"task_id": task}), {"status": "no_experience"})

    def test_invalid_record_releases_task_without_upload(self):
        task = self.begin()
        response = rpc(self.session, "tools/call", {"name": "ue_finish_task",
                       "arguments": {"task_id": task, "record": {"private": "invalid"}}})
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(self.store.db.execute("SELECT status FROM tasks WHERE id=?", (task,)).fetchone()[0], "closed")

    def test_finish_uses_same_default_local_contribution_policy(self):
        task = self.begin()
        value = self.session.invoke("ue_finish_task", {"task_id": task, "record": record()})
        self.assertEqual(value["status"], "queued")
        self.assertNotIn("payload", value)
        self.assertEqual(self.session.invoke("ue_experience_status", {})["config"]["mode"], "local")

    def test_gateway_routes_to_two_independent_ue_sessions(self):
        with MCPServer("one") as first, MCPServer("two", True) as second:
            other_project = self.root / "Other.uproject"
            other_project.write_text("{}")
            self.store.register("one", self.project, first.url)
            self.store.register("two", other_project, second.url)
            for instance, expected in (("one", "one"), ("two", "two")):
                result = self.session.invoke("ue_call", {"instance": instance, "tool": "list_toolsets"})
                self.assertEqual(result["result"]["content"][0]["text"], expected)
            self.assertFalse(first.sessions | second.sessions)

    def test_stdio_is_json_only_and_survives_invalid_json(self):
        source = io.BytesIO(b'invalid\n' + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode() + b'\n')
        output = io.BytesIO()
        stdio(source, output, self.root)
        values = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(values[0]["error"]["code"], -32700)
        self.assertEqual(values[1]["result"], {})

    def test_published_search_excludes_inbox_and_refuses_path_traversal(self):
        root = self.root / "docs"
        (root / "contributions/inbox").mkdir(parents=True)
        (root / "contributions/inbox/report.json").write_text('"untrusted_unique_command"')
        (root / "SKILL.md").write_text("Trusted blueprint guidance")
        self.assertFalse(knowledge.search("untrusted_unique_command", root=root)["matches"])
        self.assertTrue(knowledge.search("blueprint", root=root)["matches"])
        with self.assertRaises(ValueError):
            knowledge.read("../runtime.sqlite", root=root)


class HTTPTests(unittest.TestCase):
    def test_normal_server_shutdown_releases_its_session_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            server = HTTPServer(("127.0.0.1", 0), "x" * 48, root)
            sid, entry = server.create_session()
            store = entry[0].store()
            try:
                project = Path(root) / "Example.uproject"
                project.write_text("{}")
                profile = store.register("test", project)
                store.begin(profile, "owned", {"pid": 1, "started": "test"})
                with store.db:
                    store.db.execute("INSERT INTO bridge_tasks VALUES(?,?)", ("owned", entry[0].owner))
                server.server_close()
                self.assertEqual(store.db.execute("SELECT status FROM tasks WHERE id='owned'").fetchone()[0], "closed")
            finally:
                store.close()

    def test_auth_origin_lifecycle_and_deleted_session(self):
        with tempfile.TemporaryDirectory() as root:
            token = "x" * 48
            server = HTTPServer(("127.0.0.1", 0), token, root)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)

            def post(value, extra=None):
                headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                           "Accept": "application/json, text/event-stream"}
                headers.update(extra or {})
                connection.request("POST", "/mcp", json.dumps(value), headers)
                response = connection.getresponse()
                data = response.read()
                return response.status, dict(response.getheaders()), json.loads(data) if data else None
            try:
                request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "clientInfo": {"name": "work-agent", "version": "1"}}}
                self.assertEqual(post(request, {"Authorization": "Bearer bad"})[0], 401)
                self.assertEqual(post(request, {"Origin": "https://untrusted.example"})[0], 403)
                self.assertEqual(post(request, {"Host": "untrusted.example"})[0], 403)
                status, headers, result = post(request)
                self.assertEqual(status, 200)
                sid = headers["Mcp-Session-Id"]
                session_headers = {"Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-11-25"}
                self.assertEqual(post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_headers)[0], 202)
                status, _, value = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session_headers)
                self.assertEqual(status, 200)
                self.assertTrue(value["result"]["tools"])
                connection.request("DELETE", "/mcp", headers={"Authorization": "Bearer " + token, **session_headers})
                response = connection.getresponse()
                self.assertEqual(response.status, 204)
                response.read()
                self.assertEqual(post({"jsonrpc": "2.0", "id": 3, "method": "ping"}, session_headers)[0], 404)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                worker.join()

    def test_refuses_public_bind_and_weak_token(self):
        for address, token in ((("0.0.0.0", 8765), "x" * 48), (("127.0.0.1", 0), "short")):
            with self.assertRaises(ValueError):
                HTTPServer(address, token)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / ("unreal-mcp-" + VERSION + ".zip")
        self.metadata = build(ROOT, self.archive)
        self.manager = Manager(self.root / "shared")

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        return self.manager.install(self.archive, self.metadata["sha256"])

    def test_install_two_identical_thin_adapters_share_runtime_and_preserve_backups(self):
        active = self.install()
        targets = [self.root / name / "skills/unreal-mcp" for name in ("agent-a", "agent-b")]
        targets[0].mkdir(parents=True)
        (targets[0] / "private.txt").write_text("retain this local customization")
        results = [self.manager.adapter(path) for path in targets]
        self.assertTrue((Path(results[0]["backup"]) / "private.txt").exists())
        self.assertTrue(Path(results[0]["backup"]).is_relative_to(self.manager.home / "backups"))
        self.assertFalse(Path(results[0]["backup"]).is_relative_to(targets[0].parent))
        self.assertEqual((targets[0] / "SKILL.md").read_bytes(), (targets[1] / "SKILL.md").read_bytes())
        self.assertEqual(len(list(targets[0].iterdir())), 2)
        self.assertEqual(verify(self.manager.home / "packages" / active["package"])["version"], VERSION)
        result = subprocess.run([sys.executable, str(self.manager.home / "launch.py"), "--home",
                                 str(self.manager.home), "doctor"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["runtime_version"], VERSION)

    def test_bad_archive_checksum_and_tampering_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.install(self.archive, "0" * 64)
        active = self.install()
        location = self.manager.home / "packages" / active["package"]
        (location / "SKILL.md").write_text("changed")
        with self.assertRaises(ValueError):
            verify(location)

    def test_zip_traversal_is_rejected_without_writing_outside_staging(self):
        archive = self.root / "malicious.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../../escape.txt", "bad")
        with self.assertRaises(ValueError):
            self.manager.install(archive, digest(archive.read_bytes()))
        self.assertFalse((self.root / "escape.txt").exists())

    def test_active_task_blocks_activation(self):
        store = Store(self.manager.home)
        with store.db:
            store.db.execute("INSERT INTO tasks VALUES('busy','x','{}',9999999999,'active')")
        store.close()
        with self.assertRaises(ValueError):
            self.install()

    def test_update_and_rollback_use_immutable_versioned_packages(self):
        first = self.install()
        alternate = self.root / "alternate"
        alternate.mkdir()
        with zipfile.ZipFile(self.archive) as source:
            source.extractall(alternate)  # Our own just-built, trusted test fixture.
        init = alternate / "scripts/ue_mcp/__init__.py"
        init.write_text('VERSION = "3.18.1"\n')
        newer = self.root / "newer.zip"
        metadata = build(alternate, newer)
        second = self.manager.install(newer, metadata["sha256"])
        self.assertEqual(second["previous"], first["package"])
        self.assertEqual(self.manager.rollback()["package"], first["package"])


class CurationTests(unittest.TestCase):
    def evidence(self):
        return {"reviewer": "maintainer", "checked_at": "2026-10-19", "ue_version": "5.8.3",
                "editor_language": "en", "method": "pie_assertion", "assertion": "Generic runtime assertion passed.",
                "passed": True, "maintainer_reproduced": True,
                "source_issue": "https://github.com/dadongoba/unreal-mcp-skill/issues/123"}

    def test_report_cannot_be_promoted_without_passing_reproduction(self):
        candidate = propose(record())
        for field in ("passed", "maintainer_reproduced"):
            evidence = self.evidence()
            evidence[field] = False
            with self.assertRaises(ValueError):
                promote(candidate, evidence)
        self.assertEqual(promote(candidate, self.evidence())["status"], "published")
        candidate["record"]["cause"] = "changed after review"
        with self.assertRaises(ValueError):
            promote(candidate, self.evidence())

    def test_repository_published_records_have_valid_evidence(self):
        for path in (ROOT / "knowledge/published").glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value, promote(propose(value["record"]), value["evidence"]))


if __name__ == "__main__":
    unittest.main()
