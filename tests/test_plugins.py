import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ue_mcp import plugins
from ue_mcp.instances import InstanceError, Store
from ue_mcp.packages import digest, atomic_json
import ue_connect


def bundle(version="0.6.1", engine="5.7", build_id="test-build", extra=None):
    modules = json.dumps({"BuildId": build_id, "Modules": {"ModelContextProtocol": "UnrealEditor-ModelContextProtocol.dll"}}).encode()
    dll = b"test fixture, not executable"
    files = {"ModelContextProtocol.uplugin": json.dumps({"VersionName": version, "SupportedTargetPlatforms": ["Win64"]}).encode(),
             "Binaries/Win64/UnrealEditor-ModelContextProtocol.dll": dll,
             "Binaries/Win64/UnrealEditor.modules": modules,
             "Binaries/Win64/ReleaseProvenance.json": json.dumps({"version": version, "engine_version": engine + ".4",
                "dll_sha256": digest(dll), "modules_sha256": digest(modules)}).encode()}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, raw in files.items():
            archive.writestr("Plugins/ModelContextProtocol/" + name, raw)
        if extra:
            archive.writestr(extra, "bad")
    raw = out.getvalue()
    name = f"UnrealMCP-{version}-UE{engine}-Win64-GitHub.zip"
    release = {"tag_name": "v" + version, "assets": [{"name": name, "size": len(raw), "digest": "sha256:" + digest(raw),
        "browser_download_url": f"https://github.com/{plugins.PROVIDER}/releases/download/v{version}/{name}"}]}
    return raw, release


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "Project/Example.uproject"
        self.project.parent.mkdir()
        self.project.write_text('{"EngineAssociation":"5.7","Description":"keep me"}')
        self.engine = self.root / "EngineRoot"
        (self.engine / "Engine/Build").mkdir(parents=True)
        atomic_json(self.engine / "Engine/Build/Build.version", {"MajorVersion": 5, "MinorVersion": 7})
        (self.engine / "Engine/Binaries/Win64").mkdir(parents=True)
        atomic_json(self.engine / "Engine/Binaries/Win64/UnrealEditor.modules", {"BuildId": "test-build"})
        self.store = Store(self.root / "state")
        self.raw, self.release = bundle()
        self.patches = [mock.patch.object(plugins, "host_platform", return_value="Win64"),
            mock.patch.object(plugins, "releases", return_value=[self.release]),
            mock.patch.object(plugins, "download", return_value=self.raw),
            mock.patch.object(plugins, "project_is_running", return_value=False),
            mock.patch.object(ue_connect, "listening", return_value=False)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.store.close()
        self.temp.cleanup()

    def setup(self, **kwargs):
        return plugins.setup(self.store, "a", self.project, self.engine, **kwargs)

    def test_auto_install_enables_plugins_backs_up_and_registers_backend(self):
        before = self.project.read_bytes()
        result = self.setup()
        self.assertEqual(result["status"], "installed")
        self.assertEqual(result["profile"]["backend"], "avatar-unreal")
        self.assertEqual((Path(result["backup"]) / self.project.name).read_bytes(), before)
        data = json.loads(self.project.read_text())
        self.assertEqual(data["Description"], "keep me")
        self.assertTrue(all(p["Enabled"] for p in data["Plugins"]))
        self.assertEqual(self.setup()["status"], "already_installed")
        self.assertEqual(plugins.download.call_count, 1)

    def test_existing_registration_supplies_the_engine_root_automatically(self):
        self.setup()
        value = plugins.setup(self.store, "a", self.project)
        self.assertEqual(value["status"], "already_installed")
        self.assertEqual(Path(value["engine_root"]), self.engine)

    def test_matching_future_56_asset_is_discovered_without_claiming_support_today(self):
        _, release = bundle(engine="5.6")
        self.assertIsNone(plugins.choose([self.release], (5, 6), "Win64"))
        self.assertEqual(plugins.choose([self.release, release], (5, 6), "Win64")["engine"], "5.6")
        self.assertIsNone(plugins.choose([release], (5, 7), "Win64"))

    def test_upstream_newer_stable_is_upgraded_with_old_plugin_backup(self):
        self.setup()
        raw, release = bundle("0.7.0")
        with mock.patch.object(plugins, "releases", return_value=[self.release, release]), \
             mock.patch.object(plugins, "download", return_value=raw):
            result = self.setup()
        self.assertEqual(result["installed_version"], "0.7.0")
        self.assertEqual(plugins.installed(Path(result["backup"]) / "ModelContextProtocol")["version"], "0.6.1")

    def test_prerelease_or_missing_checksum_is_not_automatically_selected(self):
        self.release["prerelease"] = True
        self.assertIsNone(plugins.choose([self.release], (5, 7), "Win64"))
        self.release["prerelease"] = False
        self.release["assets"][0]["digest"] = None
        self.assertIsNone(plugins.choose([self.release], (5, 7), "Win64"))

    def test_running_editor_is_not_stopped_or_modified(self):
        before = self.project.read_bytes()
        with mock.patch.object(plugins, "project_is_running", return_value=True):
            self.assertEqual(self.setup()["status"], "close_editor_required")
        self.assertEqual(self.project.read_bytes(), before)
        plugins.download.assert_not_called()

    def test_engine_mismatch_existing_plugin_and_local_edits_are_refused(self):
        atomic_json(self.engine / "Engine/Build/Build.version", {"MajorVersion": 5, "MinorVersion": 6})
        with self.assertRaises(ValueError):
            self.setup()
        atomic_json(self.engine / "Engine/Build/Build.version", {"MajorVersion": 5, "MinorVersion": 7})
        self.setup()
        dll = self.project.parent / "Plugins/ModelContextProtocol/Binaries/Win64/UnrealEditor-ModelContextProtocol.dll"
        dll.write_bytes(b"local modifications")
        with self.assertRaises(ValueError):
            self.setup()
        self.assertEqual(dll.read_bytes(), b"local modifications")

    def test_unknown_plugin_is_never_overwritten(self):
        target = self.project.parent / "Plugins/ModelContextProtocol"
        target.mkdir(parents=True)
        (target / "custom.txt").write_text("keep")
        with self.assertRaises(ValueError):
            self.setup()
        self.assertEqual((target / "custom.txt").read_text(), "keep")

    def test_wrong_binary_build_digest_and_zip_traversal_never_activate(self):
        for raw in (b"tampered", bundle(build_id="different-build")[0], bundle(extra="../escape.txt")[0]):
            release = bundle()[1]
            if raw != b"tampered":
                release["assets"][0].update(size=len(raw), digest="sha256:" + digest(raw))
            with mock.patch.object(plugins, "releases", return_value=[release]), \
                 mock.patch.object(plugins, "download", return_value=raw):
                with self.assertRaises(ValueError):
                    self.setup()
            self.assertFalse((self.project.parent / "Plugins/ModelContextProtocol").exists())

    def test_active_task_blocks_plugin_changes(self):
        profile = self.store.register("a", self.project)
        self.store.begin(profile, "task", {"pid": 1})
        with self.assertRaises(InstanceError):
            self.setup()
        plugins.download.assert_not_called()

    def test_port_allocation_does_not_reuse_another_project_port(self):
        other = self.root / "Other.uproject"
        other.write_text("{}")
        self.store.register("other", other, "http://127.0.0.1:18777/mcp")
        self.assertIn(":18778/", self.setup()["profile"]["url"])

    def test_failed_project_save_restores_the_previous_plugin(self):
        self.setup()
        raw, release = bundle("0.7.0")
        original = plugins.atomic_json
        def fail(path, value):
            if path == self.project:
                raise OSError("simulated failure")
            return original(path, value)
        with mock.patch.object(plugins, "releases", return_value=[release]), \
             mock.patch.object(plugins, "download", return_value=raw), \
             mock.patch.object(plugins, "atomic_json", side_effect=fail):
            with self.assertRaises(OSError):
                self.setup()
        self.assertEqual(plugins.installed(self.project.parent / "Plugins/ModelContextProtocol")["version"], "0.6.1")

    def test_project_edits_during_download_are_preserved(self):
        def concurrent_edit(*args):
            self.project.write_text('{"EngineAssociation":"5.7","Description":"concurrent user edit"}')
            return self.raw
        with mock.patch.object(plugins, "download", side_effect=concurrent_edit):
            with self.assertRaises(InstanceError):
                self.setup()
        self.assertEqual(json.loads(self.project.read_text())["Description"], "concurrent user edit")
        self.assertFalse((self.project.parent / "Plugins/ModelContextProtocol").exists())

    def test_newer_local_plugin_is_not_downgraded(self):
        raw, release = bundle("0.7.0")
        with mock.patch.object(plugins, "releases", return_value=[release]), mock.patch.object(plugins, "download", return_value=raw):
            self.setup()
        self.assertEqual(self.setup()["installed_version"], "0.7.0")

    def test_avatar_launch_uses_child_only_port_and_no_epic_start_flags(self):
        result = self.setup(port=18888)
        with mock.patch.object(ue_connect, "editor_binary", return_value="UnrealEditor"), \
             mock.patch.object(ue_connect, "project_is_running", return_value=False), \
             mock.patch.object(ue_connect.subprocess, "Popen", return_value=SimpleNamespace(pid=123)) as spawn:
            messages = []
            self.assertEqual(ue_connect.launch(self.store, result["profile"], report=messages.append), 3)
            self.assertEqual(spawn.call_args.kwargs["env"]["UE_MCP_PORT"], "18888")
            self.assertEqual(len(spawn.call_args.args[0]), 2)
            self.assertEqual(len(messages), 1)


class CatalogTests(unittest.TestCase):
    def test_upstream_catalog_is_cached_and_force_refresh_finds_new_engine_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                _, first = bundle()
                _, next_release = bundle("0.7.0", "5.6")
                with mock.patch.object(plugins, "download", side_effect=[json.dumps([first]).encode(), json.dumps([next_release, first]).encode()]) as network:
                    self.assertEqual(len(plugins.releases(store)), 1)
                    self.assertEqual(len(plugins.releases(store)), 1)
                    self.assertEqual(len(plugins.releases(store, force=True)), 2)
                    self.assertEqual(network.call_count, 2)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
