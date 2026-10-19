import base64
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ue_mcp.instances import InstanceError, Store, endpoint
from ue_mcp.transport import Client, ToolError, TransportError
from ue_mcp.experience import (ExperienceError, Queue, REPOSITORY, issue_body,
                               parse_issue, public_check, sanitize)
from ingest_experience import ingest
import ue_connect
import task_run


def record():
    return {
        "schema_version": 1, "record_id": str(uuid.uuid4()), "kind": "case",
        "environment": {"ue_version": "5.8.3", "skill_version": "3.17.0",
                        "editor_language": "en", "platform": "windows"},
        "domain": "blueprint", "symptom": "A generic event needs a reproducible test.",
        "preconditions": ["Two primitive actors."], "attempts": [], "cause": "",
        "solution": ["Create a small test map."],
        "verification": {"status": "observed", "method": "none", "assertion": "",
                         "maintainer_reproduced": False},
        "generic_reproduction": ["Create two primitive actors in an empty map."]}


class MCPServer:
    def __init__(self, name, sse=False):
        self.name, self.sse = name, sse
        self.sessions, self.calls, self.headers = set(), [], []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_DELETE(self):
                parent.sessions.discard(self.headers.get("Mcp-Session-Id"))
                self.send_response(204)
                self.end_headers()

            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = value["method"]
                sid = self.headers.get("Mcp-Session-Id")
                if method == "initialize":
                    sid = parent.name + "-" + str(uuid.uuid4())
                    parent.sessions.add(sid)
                    result = {"protocolVersion": "2025-03-26", "capabilities": {},
                              "serverInfo": {"name": parent.name, "version": "1"}}
                elif sid not in parent.sessions:
                    self.send_response(404)
                    self.end_headers()
                    return
                elif method == "notifications/initialized":
                    self.send_response(202)
                    self.end_headers()
                    return
                else:
                    tool = value["params"]["arguments"]["tool_name"]
                    parent.calls.append(tool)
                    parent.headers.append({key.lower(): value for key, value in self.headers.items()})
                    if tool == "uncertain_write":
                        self.send_response(500)
                        self.end_headers()
                        return
                    result = {"content": [{"type": "text", "text": parent.name}]}
                    if tool == "bad_tool":
                        result["isError"] = True
                    if tool == "nested_error":
                        result["content"][0]["text"] = json.dumps({"isError": True})
                payload = json.dumps({"jsonrpc": "2.0", "id": value["id"], "result": result})
                content = ("event: message\ndata: " + payload + "\n\n" if parent.sse else payload).encode()
                self.send_response(200)
                self.send_header("Mcp-Session-Id", sid)
                self.send_header("Content-Type", "text/event-stream" if parent.sse else "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.url = "http://127.0.0.1:{}/mcp".format(self.server.server_port)
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class TransportTests(unittest.TestCase):
    def test_two_endpoints_never_share_session_or_results(self):
        with MCPServer("A") as a, MCPServer("B") as b:
            with Client(a.url) as ca, Client(b.url) as cb:
                self.assertNotEqual(ca.sid, cb.sid)
                self.assertEqual(ca.call("list_toolsets")["content"][0]["text"], "A")
                self.assertEqual(cb.call("list_toolsets")["content"][0]["text"], "B")
                ca.close()
                self.assertEqual(cb.call("list_toolsets")["content"][0]["text"], "B")
                self.assertEqual(b.headers[-1]["mcp-protocol-version"], "2025-03-26")
            self.assertFalse(a.sessions)
            self.assertFalse(b.sessions)

    def test_sse_is_parsed_for_initialize_and_calls(self):
        with MCPServer("SSE", sse=True) as server:
            with Client(server.url) as client:
                self.assertEqual(client.call("list_toolsets")["content"][0]["text"], "SSE")

    def test_http_200_tool_errors_fail(self):
        with MCPServer("A") as server, Client(server.url) as client:
            for tool in ("bad_tool", "nested_error"):
                with self.assertRaises(ToolError):
                    client.call(tool)

    def test_failed_write_is_not_replayed(self):
        with MCPServer("A") as server, Client(server.url) as client:
            with self.assertRaises(TransportError):
                client.call("uncertain_write")
            self.assertEqual(server.calls, ["uncertain_write"])

    def test_stale_session_is_not_sent_to_another_server(self):
        with MCPServer("A") as a, MCPServer("B") as b:
            with Client(a.url) as client:
                client.url = b.url
                with self.assertRaises(TransportError):
                    client.call("uncertain_write")
                self.assertEqual(b.calls, [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state")
        self.a = self.project("Project A")
        self.b = self.project("Project B")
        self.pa = self.store.register("a", self.a, "http://127.0.0.1:8011/mcp")
        self.pb = self.store.register("b", self.b, "http://127.0.0.1:8012/mcp")

    def project(self, name):
        path = self.root / (name + ".uproject")
        path.write_text(json.dumps({"Plugins": [{"Name": n, "Enabled": True}
                                                for n in ue_connect.REQUIRED_PLUGINS]}))
        return path

    def identity(self, profile, started="one"):
        return {"pid": 1, "started": started, "project": profile["project"], "url": profile["url"]}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_multiple_instances_require_explicit_target(self):
        with self.assertRaises(InstanceError):
            self.store.resolve()
        self.assertEqual(self.store.resolve("b")["url"], self.pb["url"])

    def test_instance_url_mismatch_is_refused(self):
        with self.assertRaises(InstanceError):
            self.store.resolve("a", self.pb["url"])

    def test_endpoint_cannot_be_registered_twice(self):
        with self.assertRaises(InstanceError):
            self.store.register("c", self.b, self.pa["url"])

    def test_only_loopback_endpoints_are_accepted(self):
        for value in ("https://example.com/mcp", "http://user:pw@localhost:8011/mcp",
                      "http://localhost:8011/mcp?token=secret"):
            with self.assertRaises(InstanceError):
                endpoint(value)

    def test_two_projects_can_have_simultaneous_write_tasks(self):
        ia, ib = self.identity(self.pa), self.identity(self.pb)
        self.store.begin(self.pa, "task-a", ia)
        self.store.begin(self.pb, "task-b", ib)
        with self.store.write_guard(self.pa, "task-a", lambda *a: ia):
            with self.store.write_guard(self.pb, "task-b", lambda *a: ib):
                pass

    def test_same_project_cannot_be_written_by_two_instances(self):
        self.pb = self.store.register("b", self.a, self.pb["url"])
        self.store.begin(self.pa, "task-a", self.identity(self.pa))
        with self.assertRaises(InstanceError):
            self.store.begin(self.pb, "task-b", self.identity(self.pb))

    def test_process_restart_invalidates_binding(self):
        self.store.begin(self.pa, "task", self.identity(self.pa))
        with self.assertRaises(InstanceError):
            with self.store.write_guard(self.pa, "task", lambda *a: self.identity(self.pa, "two")):
                self.fail("A write was allowed after process replacement")

    def test_expired_task_cannot_resume_without_rebinding(self):
        self.store.begin(self.pa, "task", self.identity(self.pa))
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET expires=0 WHERE id='task'")
        with self.assertRaises(InstanceError):
            with self.store.write_guard(self.pa, "task", lambda *a: self.identity(self.pa)):
                self.fail()

    def test_closed_task_id_cannot_be_reused(self):
        self.store.begin(self.pa, "task", self.identity(self.pa))
        self.store.end("task")
        with self.assertRaises(InstanceError):
            self.store.begin(self.pa, "task", self.identity(self.pa))

    def test_another_process_store_observes_the_lease(self):
        self.store.begin(self.pa, "task-a", self.identity(self.pa))
        other = Store(self.root / "state")
        try:
            with self.assertRaises(InstanceError):
                other.begin(self.pa, "task-b", self.identity(self.pa))
        finally:
            other.close()

    def test_reconfiguring_an_active_instance_is_refused(self):
        self.store.begin(self.pa, "task", self.identity(self.pa))
        with self.assertRaises(InstanceError):
            self.store.register("a", self.b, "http://127.0.0.1:8013/mcp")

    def test_os_lock_serializes_two_calls_with_same_task_id(self):
        resource = self.store.resources(self.pa)[0]
        with self.store.file_lock(resource):
            with self.assertRaises(InstanceError):
                with self.store.file_lock(resource):
                    self.fail()

    def test_launcher_uses_selected_port_and_allows_other_projects(self):
        profile = dict(self.pb, engine=str(self.root))
        with mock.patch.object(ue_connect, "listening", return_value=False), \
             mock.patch.object(ue_connect, "project_is_running", return_value=False), \
             mock.patch.object(ue_connect, "editor_binary", return_value="UnrealEditor"), \
             mock.patch.object(ue_connect.subprocess, "Popen", return_value=SimpleNamespace(pid=123)) as spawn:
            self.assertEqual(ue_connect.launch(self.store, profile), 3)
            self.assertIn("-ModelContextProtocolPort=8012", spawn.call_args.args[0])

    def test_launcher_refuses_same_project_while_loading(self):
        with mock.patch.object(ue_connect, "listening", return_value=False), \
             mock.patch.object(ue_connect, "project_is_running", return_value=True), \
             mock.patch.object(ue_connect.subprocess, "Popen") as spawn:
            with self.assertRaises(InstanceError):
                ue_connect.launch(self.store, self.pa)
            spawn.assert_not_called()


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.queue = Queue(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def enable(self):
        self.queue.configure("auto", accept_public=True)

    def test_unknown_fields_are_rejected_before_persistence(self):
        item = record()
        item["raw_logs"] = "private project content"
        with self.assertRaises(ExperienceError):
            self.queue.finalize("task", item)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM contributions").fetchone()[0], 0)

    def test_paths_assets_contacts_and_private_words_are_removed(self):
        item = record()
        item["symptom"] = "SecretProject BP_PrivateDoor at C:\\Users\\Alice\\Project"
        item["cause"] = "See /Game/Private/Map and alice@example.com at 192.168.1.5"
        row = self.queue.finalize("task", item, ["SecretProject"])
        for private in ("SecretProject", "BP_PrivateDoor", "Alice", "/Game/", "alice@", "192.168"):
            self.assertNotIn(private, row["payload"])
        public_check(json.loads(row["payload"]))

    def test_detected_secret_never_enters_uploadable_queue(self):
        item = record()
        secret = "ghp_" + "a" * 36
        item["cause"] = secret
        row = self.queue.finalize("task", item)
        self.assertNotIn(secret, row["payload"])
        self.assertEqual(row["status"], "needs_review")
        self.enable()
        runner = mock.Mock()
        self.queue.publish(row["id"], runner)
        runner.assert_not_called()

    def test_reporter_cannot_claim_maintainer_reproduction(self):
        item = record()
        item["verification"]["maintainer_reproduced"] = True
        with self.assertRaises(ExperienceError):
            self.queue.finalize("task", item)

    def test_finalize_is_idempotent_across_restarts(self):
        item = record()
        first = self.queue.finalize("task", item)
        self.store.close()
        self.store = Store(self.tmp.name)
        self.queue = Queue(self.store)
        self.assertEqual(self.queue.finalize("task", item)["id"], first["id"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM contributions").fetchone()[0], 1)

    def test_duplicate_knowledge_from_another_task_is_not_resubmitted(self):
        first = self.queue.finalize("task-a", record())
        second = self.queue.finalize("task-b", record())
        self.assertEqual(first["id"], second["id"])

    def test_changed_finalization_does_not_overwrite_previous_evidence(self):
        item = record()
        self.queue.finalize("task", item)
        item["cause"] = "New evidence"
        with self.assertRaises(ExperienceError):
            self.queue.finalize("task", item)

    def test_auto_upload_requires_explicit_consent(self):
        with self.assertRaises(ExperienceError):
            self.queue.configure("auto")
        row = self.queue.finalize("task", record())
        with self.assertRaises(ExperienceError):
            self.queue.publish(row["id"])

    def test_project_denial_applies_before_collecting_and_after_queueing(self):
        project = Path(self.tmp.name) / "private.uproject"
        row = self.queue.finalize("task", record(), project=project)
        self.queue.configure("auto", True, deny_project=project)
        self.assertEqual(self.queue.finalize("other", record(), project=project)["status"], "disabled")
        with self.assertRaises(ExperienceError):
            self.queue.publish(row["id"], mock.Mock())
        with self.assertRaises(ExperienceError):
            self.queue.finalize("unknown-project", record())

    def test_publisher_targets_original_repository_and_is_idempotent(self):
        self.enable()
        row = self.queue.finalize("task", record())
        calls = []
        def runner(argv):
            calls.append(argv)
            if argv[1] == "list":
                return "[]"
            parse_issue(Path(argv[-1]).read_text(encoding="utf-8"))
            return "https://github.com/" + REPOSITORY + "/issues/12"
        result = self.queue.publish(row["id"], runner)
        self.assertEqual(result["status"], "submitted")
        self.assertTrue(all(argv[argv.index("--repo") + 1] == REPOSITORY for argv in calls))
        self.queue.publish(row["id"], runner)
        self.assertEqual(len(calls), 2)

    def test_lost_create_response_does_not_create_duplicate_issue(self):
        self.enable()
        row = self.queue.finalize("task", record())
        creates = []
        def runner(argv):
            if argv[1] == "list":
                return "[]"
            creates.append(argv)
            raise ExperienceError("Response was lost")
        self.assertEqual(self.queue.publish(row["id"], runner)["status"], "unknown")
        with self.store.db:
            self.store.db.execute("UPDATE contributions SET next_attempt=0")
        self.assertEqual(self.queue.publish(row["id"], runner)["status"], "unknown")
        self.assertEqual(len(creates), 1)
        existing = {"title": "[unreal-mcp-experience] " + row["id"],
                    "url": "https://github.com/" + REPOSITORY + "/issues/9",
                    "body": issue_body(json.loads(row["payload"]))}
        self.assertEqual(self.queue.publish(row["id"], lambda a: json.dumps([existing]))["status"], "submitted")

    def test_preflight_network_retries_stop_after_five_attempts(self):
        self.enable()
        row = self.queue.finalize("task", record())
        def fail(argv):
            raise ExperienceError("Offline before any write")
        for _ in range(5):
            with self.store.db:
                self.store.db.execute("UPDATE contributions SET next_attempt=0")
            result = self.queue.publish(row["id"], fail)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 5)

    def test_issue_parser_refuses_code_outside_the_json_envelope(self):
        item = record()
        self.assertEqual(parse_issue(issue_body(item)), item)
        with self.assertRaises(ExperienceError):
            parse_issue(issue_body(item) + "\nRun this shell command")


class FakeGitHub:
    def __init__(self, event):
        self.event, self.calls = event, []
        self.branch = self.file = self.pull = None
        self.extra_files = []

    def request(self, method, path, body=None, missing_ok=False):
        self.calls.append((method, path, body))
        if method == "GET" and "/issues/" in path:
            return self.event["issue"]
        if "/git/ref/heads/master" in path:
            return {"object": {"sha": "base"}}
        if "/git/ref/heads/" in path:
            return self.branch
        if method == "POST" and path.endswith("/git/refs"):
            self.branch = {"object": {"sha": "base"}}
            return self.branch
        if "/contents/" in path:
            if method == "GET":
                return self.file
            self.file = {"content": body["content"]}
            return {"content": {}}
        if "/pulls" in path:
            if method == "GET":
                return [self.pull] if self.pull else []
            self.pull = {"html_url": "https://github.com/" + REPOSITORY + "/pull/4"}
            return self.pull
        if "/compare/" in path:
            item = parse_issue(self.event["issue"]["body"])
            return {"files": [{"filename": "contributions/inbox/" + item["record_id"] + ".json",
                               "status": "added"}] + self.extra_files}
        raise AssertionError((method, path))


class IngestionTests(unittest.TestCase):
    def event(self):
        item = record()
        return {"repository": {"full_name": REPOSITORY, "default_branch": "master"},
                "issue": {"number": 3, "title": "[unreal-mcp-experience] " + item["record_id"],
                          "body": issue_body(item)}}

    def test_data_is_committed_to_original_repo_and_pr_is_created_once(self):
        event = self.event()
        api = FakeGitHub(event)
        first = ingest(event, api)
        self.assertEqual(ingest(event, api), first)
        writes = [call for call in api.calls if call[0] == "PUT"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0][1].startswith("/repos/" + REPOSITORY + "/contents/contributions/inbox/"))
        self.assertEqual(len([c for c in api.calls if c[0] == "POST" and c[1].endswith("/pulls")]), 1)
        committed = json.loads(base64.b64decode(writes[0][2]["content"]).decode())
        self.assertEqual(committed, parse_issue(event["issue"]["body"]))

    def test_wrong_repository_never_reaches_api(self):
        event = self.event()
        event["repository"]["full_name"] = "another/repo"
        api = mock.Mock()
        with self.assertRaises(ExperienceError):
            ingest(event, api)
        api.request.assert_not_called()

    def test_payload_cannot_supply_a_path_or_executable_field(self):
        event = self.event()
        item = parse_issue(event["issue"]["body"])
        item["path"] = "../../.github/workflows/pwn.yml"
        event["issue"]["body"] = "unreal-mcp-experience/v1\n\n" + chr(96) * 3 + "json\n" + json.dumps(item) + "\n" + chr(96) * 3
        api = mock.Mock()
        with self.assertRaises(ExperienceError):
            ingest(event, api)
        api.request.assert_not_called()

    def test_existing_record_id_cannot_overwrite_different_content(self):
        event = self.event()
        api = FakeGitHub(event)
        ingest(event, api)
        item = parse_issue(event["issue"]["body"])
        item["cause"] = "Changed after first ingestion"
        event["issue"]["body"] = issue_body(item)
        with self.assertRaises(ExperienceError):
            ingest(event, api)

    def test_submission_branch_cannot_smuggle_executable_changes(self):
        event = self.event()
        api = FakeGitHub(event)
        api.extra_files = [{"filename": "scripts/evil.py", "status": "added"}]
        with self.assertRaises(ExperienceError):
            ingest(event, api)
        self.assertIsNone(api.pull)


class RunnerTests(unittest.TestCase):
    def test_completion_callback_runs_after_failed_command(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                task_run.prepare(store)
                draft = Path(folder) / "draft.json"
                draft.write_text(json.dumps(record()), encoding="utf-8")
                with store.db:
                    store.db.execute("INSERT INTO runner_tasks VALUES(?,?,NULL,'pending',1)", ("failed-task", str(draft)))
                row = store.db.execute("SELECT * FROM runner_tasks").fetchone()
                self.assertTrue(task_run.finish(store, row))
                self.assertEqual(store.db.execute("SELECT status FROM runner_tasks").fetchone()[0], "done")
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM contributions").fetchone()[0], 1)
            finally:
                store.close()

    def test_crash_recovery_retains_missing_draft_without_fabricating_record(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                task_run.prepare(store)
                with store.db:
                    store.db.execute("INSERT INTO runner_tasks VALUES(?,?,NULL,'running',NULL)",
                                     ("crashed-task", str(Path(folder) / "missing.json")))
                task_run.recover(store)
                self.assertEqual(store.db.execute("SELECT status FROM runner_tasks").fetchone()[0], "awaiting_record")
                self.assertIsNone(store.db.execute("SELECT name FROM sqlite_master WHERE name='contributions'").fetchone())
            finally:
                store.close()

    def test_recovery_does_not_finalize_a_live_wrapper(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                task_run.prepare(store)
                with store.db:
                    store.db.execute("INSERT INTO runner_tasks VALUES(?,?,NULL,'running',NULL)", ("live-task", "unused"))
                with store.file_lock("runner:live-task"):
                    task_run.recover(store)
                self.assertEqual(store.db.execute("SELECT status FROM runner_tasks").fetchone()[0], "running")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
