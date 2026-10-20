"""Discover maintained upstream releases and install matching project plugins.

Providers are reviewed code, release metadata is data. Never execute installers.
"""
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
import time
import uuid
import zipfile

from .instances import InstanceError, canonical, project_is_running
from .packages import atomic_json, digest, download, safe_name

PROVIDER = "AvatarGanymede/ue5.7-mcp"
BACKEND = "avatar-unreal"
PLUGIN = "ModelContextProtocol"
RECEIPT = ".unreal-mcp-install.json"
MAX_ZIP = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
TTL = 86400


def host_platform():
    return "Win64" if sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"} else sys.platform


def resolve_engine(store, project, engine=None):
    if engine:
        return str(Path(engine).expanduser().resolve())
    known = {p["engine"] for p in store.profiles().values()
             if p["project"] == canonical(project) and p.get("engine")}
    if len(known) == 1:
        return next(iter(known))
    if len(known) > 1:
        raise ValueError("Project has multiple registered engines; select one explicitly")
    if sys.platform == "win32":
        import winreg
        data = json.loads(Path(project).read_text(encoding="utf-8-sig"))
        association = str(data.get("EngineAssociation", ""))
        if re.fullmatch(r"\d+\.\d+", association):
            key, value_name = r"SOFTWARE\EpicGames\Unreal Engine" + "\\" + association, "InstalledDirectory"
            roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        elif re.fullmatch(r"\{?[A-Fa-f0-9-]{36}\}?", association):
            key, value_name = r"SOFTWARE\Epic Games\Unreal Engine\Builds", association
            roots = (winreg.HKEY_CURRENT_USER,)
        else:
            return None
        for root in roots:
            try:
                with winreg.OpenKey(root, key) as handle:
                    candidate, _ = winreg.QueryValueEx(handle, value_name)
                if (Path(candidate) / "Engine/Build/Build.version").is_file():
                    return str(Path(candidate).resolve())
            except OSError:
                continue
    return None


def detect(project, engine=None):
    project = Path(project).expanduser().resolve()
    if project.suffix.lower() != ".uproject" or not project.is_file():
        raise ValueError("Select an existing .uproject")
    data = json.loads(project.read_text(encoding="utf-8-sig"))
    association = str(data.get("EngineAssociation", ""))
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", association)
    associated = tuple(map(int, match.groups()[:2])) if match else None
    version = associated
    if engine:
        build = json.loads((Path(engine) / "Engine/Build/Build.version").read_text(encoding="utf-8-sig"))
        version = (build["MajorVersion"], build["MinorVersion"])
        if any(isinstance(v, bool) or not isinstance(v, int) for v in version):
            raise ValueError("Invalid engine Build.version")
        if associated and associated != version:
            raise ValueError("Selected engine disagrees with the project's EngineAssociation")
    if not version:
        raise ValueError("Custom/unknown EngineAssociation requires an explicit engine root with Build.version")
    return project, data, version


def releases(store, force=False):
    cache = store.root / "plugin-releases.json"
    with store.file_lock("plugin-release-check"):
        if not force:
            try:
                value = json.loads(cache.read_text(encoding="utf-8"))
                if (value.get("provider") == PROVIDER and 0 <= time.time() - value["checked_at"] < TTL
                        and isinstance(value.get("releases"), list)):
                    return value["releases"]
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass
        # Match version-specific assets across recent stable releases, not just
        # /latest: a new UE 5.6 build may be separate from the UE 5.7 release.
        value = json.loads(download("https://api.github.com/repos/" + PROVIDER + "/releases?per_page=30", 4000000, 10))
        if not isinstance(value, list):
            raise ValueError("Invalid upstream release catalog")
        atomic_json(cache, {"provider": PROVIDER, "checked_at": time.time(), "releases": value})
        return value


def choose(items, engine_version, host=None):
    host = host or host_platform()
    major, minor = engine_version
    candidates = []
    for release in items:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag) if isinstance(tag, str) else None
        if not match:
            continue
        plugin_version = tag[1:]
        name = f"UnrealMCP-{plugin_version}-UE{major}.{minor}-{host}-GitHub.zip"
        expected_url = f"https://github.com/{PROVIDER}/releases/download/{tag}/{name}"
        for asset in release.get("assets", []):
            if not isinstance(asset, dict) or asset.get("name") != name:
                continue
            checksum = asset.get("digest", "")
            if (not isinstance(checksum, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", checksum)
                    or asset.get("browser_download_url") != expected_url
                    or not isinstance(asset.get("size"), int) or not 0 < asset["size"] <= MAX_ZIP):
                continue
            candidates.append({"provider": PROVIDER, "backend": BACKEND, "version": plugin_version,
                               "engine": f"{major}.{minor}", "platform": host, "url": expected_url,
                               "sha256": checksum[7:], "size": asset["size"], "asset": name})
    return max(candidates, key=lambda c: tuple(map(int, c["version"].split(".")))) if candidates else None


def installed(target):
    if not target.exists():
        return None
    if target.resolve() != target.absolute():
        raise ValueError("Refusing linked plugin directory")
    try:
        receipt = json.loads((target / RECEIPT).read_text(encoding="utf-8"))
        if receipt.get("provider") != PROVIDER or not isinstance(receipt.get("files"), dict):
            raise ValueError("Unrecognized plugin receipt")
        if any(p.is_symlink() or p.resolve() != p.absolute() for p in target.rglob("*")):
            raise ValueError("Refusing links in managed plugin")
        actual = {p.relative_to(target).as_posix(): digest(p.read_bytes()) for p in target.rglob("*")
                  if p.is_file() and p.name != RECEIPT and "__pycache__" not in p.parts
                  and p.suffix not in {".pyc", ".pyo"}
                  and p.parts[len(target.parts)] not in {"Intermediate", "Saved"}}
        # Generated binaries are relevant too: changed files need review rather
        # than silently overwriting a developer's build.
        if actual != receipt["files"]:
            raise ValueError("Managed plugin has changed; preserve local edits before upgrading")
        return receipt
    except (OSError, KeyError, TypeError) as error:
        raise ValueError("Existing plugin is not managed by this installer; inspect it without overwriting") from error


def plan(store, project, engine=None, force=False):
    engine = resolve_engine(store, project, engine)
    project, data, version = detect(project, engine)
    result = {"project": str(project), "engine_version": ".".join(map(str, version)),
              "provider": PROVIDER, "engine_root": engine, "verification": "not_live_ue_verified"}
    if version >= (5, 8):
        return dict(result, status="builtin_epic", backend="epic-toolsets")
    if host_platform() != "Win64":
        return dict(result, status="unsupported_platform", reason="Reviewed provider currently has Win64 packaging only")
    selected = choose(releases(store, force), version)
    if not selected:
        return dict(result, status="no_compatible_release", reason="No matching stable asset with a GitHub SHA256 digest; no plugin will be downloaded")
    return dict(result, status="available", backend=BACKEND, release=selected)


def unpack(raw, selected, staging):
    if len(raw) > MAX_ZIP or len(raw) != selected["size"] or digest(raw) != selected["sha256"]:
        raise ValueError("Plugin archive size/SHA256 mismatch")
    prefix = "Plugins/" + PLUGIN + "/"
    names = set()
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > 3000 or sum(i.file_size for i in infos) > MAX_EXPANDED:
            raise ValueError("Plugin ZIP exceeds extraction limits")
        for item in infos:
            safe_name(item.filename.rstrip("/"))
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Plugin ZIP links are refused")
            if item.is_dir():
                continue
            if not item.filename.startswith(prefix):
                raise ValueError("Unexpected file outside the plugin")
            relative = item.filename[len(prefix):]
            safe_name(relative)
            if relative.casefold() in names or relative == RECEIPT:
                raise ValueError("Duplicate/reserved plugin ZIP path")
            names.add(relative.casefold())
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = archive.read(item)
            path.write_bytes(content)
            files[relative] = digest(content)
    descriptor = json.loads((staging / (PLUGIN + ".uplugin")).read_text(encoding="utf-8-sig"))
    pinned_engine = descriptor.get("EngineVersion")
    if (descriptor.get("VersionName") != selected["version"]
            or "Win64" not in descriptor.get("SupportedTargetPlatforms", [])
            or pinned_engine and not pinned_engine.startswith(selected["engine"] + ".")
            or not (staging / "Binaries/Win64/UnrealEditor-ModelContextProtocol.dll").is_file()):
        raise ValueError("Plugin descriptor/binaries disagree with the selected release")
    binary = staging / "Binaries/Win64"
    provenance = json.loads((binary / "ReleaseProvenance.json").read_text(encoding="utf-8-sig"))
    modules = json.loads((binary / "UnrealEditor.modules").read_text(encoding="utf-8-sig"))
    if (provenance.get("version") != selected["version"]
            or not str(provenance.get("engine_version", "")).startswith(selected["engine"] + ".")
            or provenance.get("dll_sha256") != files["Binaries/Win64/UnrealEditor-ModelContextProtocol.dll"]
            or provenance.get("modules_sha256") != files["Binaries/Win64/UnrealEditor.modules"]
            or modules.get("BuildId") != selected.get("engine_build_id")
            or modules.get("Modules", {}).get(PLUGIN) != "UnrealEditor-ModelContextProtocol.dll"):
        raise ValueError("Plugin engine build/provenance mismatch; obtain a matching build or compile from source")
    atomic_json(staging / RECEIPT, {**selected, "files": files})


def setup(store, instance, project, engine=None, port=None, force=False):
    from .instances import endpoint, valid_id
    from ue_connect import listening
    valid_id(instance)
    engine = resolve_engine(store, project, engine)
    project, data, version = detect(project, engine)
    project_snapshot = project.read_bytes()
    data = json.loads(project_snapshot.decode("utf-8-sig"))
    selection = plan(store, project, engine, force)
    if selection["status"] not in {"builtin_epic", "available"}:
        return selection
    backend = selection["backend"]
    existing_profile = store.profiles().get(instance)
    if existing_profile and existing_profile["project"] != canonical(project):
        raise ValueError("Instance already belongs to a different project; choose another instance ID")
    if port is None:
        if existing_profile:
            from urllib.parse import urlsplit
            port = urlsplit(existing_profile["url"]).port
        else:
            port = 8000 if backend == "epic-toolsets" else 18777
            used = {p["url"] for p in store.profiles().values()}
            for _ in range(200):
                url = f"http://127.0.0.1:{port}/mcp"
                if url not in used and not listening(url):
                    break
                port += 1
            else:
                raise ValueError("No available project port in the setup range")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be 1-65535")
    url = endpoint(f"http://127.0.0.1:{port}/mcp")
    for name, item in store.profiles().items():
        if name != instance and item["url"] == url:
            raise ValueError("Port belongs to another registered instance")
    if backend == "epic-toolsets":
        return dict(selection, profile=store.register(instance, project, url, engine, backend))
    if not engine:
        return dict(selection, status="engine_required", reason="Supply the target engine root to verify the plugin's exact binary BuildId")
    engine_modules = json.loads((Path(engine) / "Engine/Binaries/Win64/UnrealEditor.modules").read_text(encoding="utf-8-sig"))
    engine_build_id = engine_modules.get("BuildId")
    if not isinstance(engine_build_id, str) or not engine_build_id:
        raise ValueError("Target engine has no verifiable binary BuildId")
    target = project.parent / "Plugins" / PLUGIN
    if target.parent.resolve() != target.parent.absolute():
        raise ValueError("Refusing linked Plugins directory")
    # No second plugin with the same module, including engine installations and
    # the old Avatar directory. Do not silently replace a user's Epic backport.
    conflicts = [project.parent / "Plugins/UnrealMCP"]
    if engine:
        conflicts.extend((Path(engine) / "Engine/Plugins").rglob(PLUGIN + ".uplugin"))
    conflicts.extend(p for p in target.parent.rglob(PLUGIN + ".uplugin") if p.parent != target)
    if any(p.exists() for p in conflicts):
        raise ValueError("Existing MCP plugin conflicts with automatic installation; preserve and inspect it first")
    with store.file_lock("package-activation"), store.file_lock("project:" + canonical(project)):
        if store.db.execute("SELECT 1 FROM leases l JOIN tasks t ON t.id=l.task WHERE l.resource=? AND t.status='active' AND t.expires>?",
                            ("project:" + canonical(project), time.time())).fetchone():
            raise InstanceError("Finish the project's active task before plugin setup")
        receipt = installed(target)
        selected = dict(selection["release"], engine_build_id=engine_build_id)
        if receipt and receipt.get("engine_build_id") != engine_build_id:
            raise ValueError("Installed managed plugin belongs to a different engine build")
        current = receipt and tuple(map(int, receipt["version"].split(".")))
        desired = tuple(map(int, selected["version"].split(".")))
        needs_install = not receipt or current < desired
        plugins = data.setdefault("Plugins", [])
        by_name = {p["Name"]: p for p in plugins}
        needs_enable = (any(not by_name.get(name, {}).get("Enabled") for name in (PLUGIN, "PythonScriptPlugin"))
                        or by_name.get(PLUGIN, {}).get("SupportedTargetPlatforms") != ["Win64"])
        if (needs_install or needs_enable) and project_is_running(project):
            return dict(selection, status="close_editor_required", reason="Close this project's editor to install/update; no editor was stopped")
        if needs_install and listening(url):
            raise ValueError("Selected port is occupied; no process will be stopped")
        backup = None
        if needs_install or needs_enable:
            backup = project.parent / "Saved/UnrealMCPBackups" / uuid.uuid4().hex
            if backup.parent.resolve() != backup.parent.absolute():
                raise ValueError("Refusing linked backup directory")
            backup.mkdir(parents=True)
            shutil.copy2(project, backup / project.name)
            for name in (PLUGIN, "PythonScriptPlugin"):
                entry = by_name.get(name)
                if entry is None:
                    entry = {"Name": name}
                    plugins.append(entry)
                entry["Enabled"] = True
                if name == PLUGIN:
                    entry["SupportedTargetPlatforms"] = ["Win64"]
            with tempfile.TemporaryDirectory(prefix=".ue-mcp-setup-", dir=project.parent) as folder:
                staged = Path(folder) / PLUGIN
                staged.mkdir()
                moved_old, activated = False, False
                if needs_install:
                    unpack(download(selected["url"], MAX_ZIP), selected, staged)
                    if project_is_running(project):
                        raise InstanceError("Editor started during download; no plugin was activated")
                try:
                    if project.read_bytes() != project_snapshot:
                        raise InstanceError("Project settings changed during setup; no activation was performed")
                    if needs_install:
                        target.parent.mkdir(exist_ok=True)
                        if target.exists():
                            os.replace(target, backup / PLUGIN)
                            moved_old = True
                        os.replace(staged, target)
                        activated = True
                    atomic_json(project, data)
                except OSError:
                    if activated:
                        os.replace(target, Path(folder) / "failed-install")
                    if moved_old:
                        os.replace(backup / PLUGIN, target)
                    raise
        profile = store.register(instance, project, url, engine, backend)
        return dict(selection, status="installed" if needs_install else "already_installed",
                    profile=profile, backup=str(backup) if backup else None,
                    restart_required=bool(needs_install or needs_enable),
                    installed_version=selected["version"] if needs_install else receipt["version"],
                    note="Launch/restart this project, then verify ue_capabilities and health; no live UE certification implied")
