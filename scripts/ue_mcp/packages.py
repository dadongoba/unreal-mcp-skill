"""Versioned local packages, verified release downloads and stable host adapters."""
import hashlib
import contextlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
import zipfile

from . import VERSION
from .experience import REPOSITORY
from .instances import Store

ROOT = Path(__file__).resolve().parents[2]
MAX_PACKAGE = 48 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in {"", ".", ".."} or part.rstrip(" .") != part
                   or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                   for part in name.split("/"))
            or any(ord(c) < 32 for c in name)):
        raise ValueError("Unsafe package path")
    return path


def atomic_json(path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def package_files(root):
    root = Path(root).resolve()
    selected = []
    for name in ("SKILL.md", "README.md", "README.zh-CN.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md"):
        if (root / name).is_file():
            selected.append(root / name)
    for name in ("scripts", "references", "schemas", "knowledge/published"):
        selected += [p for p in (root / name).rglob("*") if p.is_file()
                     and p.suffix in {".py", ".ps1", ".md", ".json", ".txt"}
                     and "__pycache__" not in p.parts]
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Package source contains a link outside its root")
    return sorted(selected)


def build(root, archive):
    root, archive = Path(root).resolve(), Path(archive).resolve()
    data = {p.relative_to(root).as_posix(): p.read_bytes() for p in package_files(root)}
    version_text = data["scripts/ue_mcp/__init__.py"].decode("utf-8-sig")
    version = re.search(r'VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"', version_text).group(1)
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                         stderr=subprocess.DEVNULL, text=True).strip()
        if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"],
                                   stderr=subprocess.DEVNULL, text=True).strip():
            commit = None  # A development snapshot is not the clean HEAD tree.
    except (OSError, subprocess.CalledProcessError):
        commit = None
    manifest = {"format": 1, "repository": REPOSITORY, "version": version,
                "contract_version": 1, "source_commit": commit,
                "files": {name: digest(raw) for name, raw in data.items()}}
    if sum(map(len, data.values())) > MAX_PACKAGE:
        raise ValueError("Package is too large")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name, raw in data.items():
            output.writestr(name, raw)
        output.writestr("package.json", json.dumps(manifest, indent=2))
    release = {key: manifest[key] for key in ("repository", "version", "contract_version", "source_commit")}
    release.update(archive=archive.name, sha256=digest(archive.read_bytes()))
    atomic_json(archive.parent / "release.json", release)
    return release


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    if (manifest.get("format") != 1 or manifest.get("repository") != REPOSITORY
            or manifest.get("contract_version") != 1
            or not re.fullmatch(r"\d+\.\d+\.\d+", manifest.get("version", ""))
            or not isinstance(manifest.get("files"), dict) or len(manifest["files"]) > 1000):
        raise ValueError("Unsupported package manifest")
    for name, expected in manifest["files"].items():
        path = root.joinpath(*safe_name(name).parts)
        if (not path.resolve().is_relative_to(root) or path.is_symlink()
                or not path.is_file() or digest(path.read_bytes()) != expected):
            raise ValueError("Package integrity check failed: " + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    if actual != set(manifest["files"]) | {"package.json"}:
        raise ValueError("Package has unmanifested files")
    for required in ("SKILL.md", "scripts/mcp_server.py", "scripts/unreal_mcp.py", "scripts/ue_mcp/__init__.py"):
        if required not in manifest["files"]:
            raise ValueError("Package is incomplete")
    version_text = (root / "scripts/ue_mcp/__init__.py").read_text(encoding="utf-8-sig")
    if 'VERSION = "' + manifest["version"] + '"' not in version_text:
        raise ValueError("Package version disagrees with runtime")
    return manifest


LAUNCHER = r'''# Generated stable entrypoint. Reconnect clients after activation.
import hashlib, json, pathlib, re, runpy, sys
home = pathlib.Path(__file__).resolve().parent
active = json.loads((home / "active.json").read_text(encoding="utf-8"))
package = active["package"]
if not re.fullmatch(r"\d+\.\d+\.\d+-[a-f0-9]{12}", package):
    raise SystemExit("Invalid active package")
root = home / "packages" / package
manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
if hashlib.sha256((root / "package.json").read_bytes()).hexdigest()[:12] != package.rsplit("-", 1)[1]:
    raise SystemExit("Package manifest changed; reinstall or roll back")
for name, expected in manifest["files"].items():
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("Installed package changed; reinstall or roll back")
sys.path.insert(0, str(root / "scripts"))
sys.argv = [str(root / "scripts/unreal_mcp.py"), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


class Manager:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("UNREAL_MCP_HOME") or Path.home() / ".unreal-mcp").expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True)

    def active(self):
        path = self.home / "active.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def idle(self):
        state = self.home / "runtime.sqlite"
        if state.exists():
            with contextlib.closing(sqlite3.connect(str(state))) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
                    if db.execute("SELECT 1 FROM tasks WHERE status='active' AND expires>?", (time.time(),)).fetchone():
                        raise ValueError("Finish active tasks before changing runtime versions")

    def install(self, archive, expected):
        raw = Path(archive).read_bytes()
        if len(raw) > MAX_PACKAGE or digest(raw) != expected:
            raise ValueError("Archive checksum or size check failed")
        store = Store(self.home)
        try:
            with store.file_lock("package-activation"):
                self.idle()
                with tempfile.TemporaryDirectory(prefix="ue-package-", dir=self.home) as folder:
                    staging = Path(folder) / "payload"
                    staging.mkdir()
                    with zipfile.ZipFile(archive) as source:
                        infos = source.infolist()
                        if (len(infos) > 1001 or sum(i.file_size for i in infos) > MAX_PACKAGE
                                or len({i.filename.casefold() for i in infos}) != len(infos)):
                            raise ValueError("Archive exceeds limits or has duplicate names")
                        for info in infos:
                            name = safe_name(info.filename)
                            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                                raise ValueError("Only regular package files are allowed")
                            path = staging.joinpath(*name.parts)
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(source.read(info))
                    manifest = verify(staging)
                    package_id = manifest["version"] + "-" + digest((staging / "package.json").read_bytes())[:12]
                    target = self.home / "packages" / package_id
                    target.parent.mkdir(exist_ok=True)
                    if target.exists():
                        verify(target)
                    else:
                        os.replace(staging, target)
                    previous = self.active()
                    active = {"package": package_id, "version": manifest["version"],
                              "previous": previous["package"] if previous and previous["package"] != package_id
                              else previous.get("previous") if previous else None}
                    (self.home / "launch.py").write_text(LAUNCHER, encoding="utf-8")
                    atomic_json(self.home / "active.json", active)
                    return active
        finally:
            store.close()

    def rollback(self):
        store = Store(self.home)
        try:
            with store.file_lock("package-activation"):
                self.idle()
                current = self.active()
                if not current or not current.get("previous"):
                    raise ValueError("No previous package is available")
                previous = current["previous"]
                if not re.fullmatch(r"\d+\.\d+\.\d+-[a-f0-9]{12}", previous):
                    raise ValueError("Invalid previous package")
                manifest = verify(self.home / "packages" / previous)
                value = {"package": previous, "version": manifest["version"], "previous": current["package"]}
                atomic_json(self.home / "active.json", value)
                return value
        finally:
            store.close()

    def config(self):
        return {"mcpServers": {"unreal-mcp": {"command": sys.executable,
                "args": [str(self.home / "launch.py"), "serve"],
                "env": {"UNREAL_MCP_HOME": str(self.home)}}}}

    def adapter(self, target):
        if not self.active():
            raise ValueError("Install a shared runtime first")
        target = Path(target).expanduser().absolute()
        parent = target.parent.resolve()
        if target.name != "unreal-mcp" or target.is_symlink() or target.resolve().parent != parent:
            raise ValueError("Adapter destination must be a regular unreal-mcp folder under its skills directory")
        body = ("---\nname: unreal-mcp\ndescription: Operate Unreal Engine through MCP; "
                "author and verify Blueprints, scenes, materials, animation, physics and UI.\n---\n\n"
                "# Unreal MCP shared runtime\n\n"
                "Use the connected Unreal MCP tools. First call ue_status for shared version/update status, "
                "then ue_knowledge_read with path SKILL.md; "
                "load relevant domain references through the knowledge tools. Begin an explicitly "
                "selected instance task, execute and verify, then call ue_finish_task. "
                "Preserve user authorization and local contribution preferences.\n\n"
                "If MCP is unavailable, use this host-neutral launcher:\n\n"
                "    python \"" + str(self.home / "launch.py") + "\" knowledge read SKILL.md\n\n"
                "It returns the current shared instructions. Their relative script/reference paths "
                "resolve against the returned package_root. Command-line helpers remain available there.\n"
                "Generate the client's MCP configuration with:\n\n"
                "    python \"" + str(self.home / "launch.py") + "\" config\n\n"
                "Core and knowledge versions come from the shared runtime; reconnect MCP after updating.\n")
        marker = target / "shared-adapter.json"
        if marker.exists() and (target / "SKILL.md").read_text(encoding="utf-8") == body:
            return {"path": str(target), "status": "current"}
        backup = None
        if target.exists():
            if not target.is_dir():
                raise ValueError("Adapter destination is not a directory")
            # Skill loaders can recurse into _backup and discover duplicate skills.
            # Keep complete backups outside every client's skill discovery directory.
            backup = (self.home / "backups" / "adapters" / digest(str(parent).encode())[:12]
                      / ("unreal-mcp-before-shared-" + uuid.uuid4().hex))
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.resolve().is_relative_to(self.home) or target.resolve().parent != parent:
                raise ValueError("Backup must remain inside the shared home's backup directory")
            shutil.move(str(target), str(backup))
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(body, encoding="utf-8")
        atomic_json(marker, {"format": 1, "shared_home": str(self.home)})
        return {"path": str(target), "backup": str(backup) if backup else None, "status": "installed"}


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url):
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in
            {"api.github.com", "github.com", "release-assets.githubusercontent.com"}
            or parts.username or parts.password or parts.port not in {None, 443}):
        raise ValueError("Unexpected release download host")


def download(url, maximum=MAX_PACKAGE, timeout=30):
    validate_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "unreal-mcp/" + VERSION})
    with urllib.request.build_opener(ReleaseRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Release response exceeds size limit")
    return raw


class NoStableRelease(ValueError):
    pass


def latest(timeout=30):
    try:
        release = json.loads(download("https://api.github.com/repos/" + REPOSITORY + "/releases/latest", 512000, timeout))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NoStableRelease("No stable portable release is published yet; install from a trusted checkout") from error
        raise
    if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
        raise ValueError("Invalid stable release response")
    tag = release.get("tag_name", "")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or release.get("draft") or release.get("prerelease"):
        raise ValueError("Latest release is not a stable semantic version")
    base = "https://github.com/" + REPOSITORY + "/releases/download/" + tag + "/"
    if any(not isinstance(a, dict) or not isinstance(a.get("name"), str)
           or not isinstance(a.get("browser_download_url"), str) for a in release["assets"]):
        raise ValueError("Invalid stable release asset")
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    if "release.json" not in assets:
        raise NoStableRelease("Latest stable release has no portable package; publish ZIP and release.json before automatic upgrades")
    if assets.get("release.json") != base + "release.json":
        raise ValueError("Stable release has no canonical release.json")
    metadata = json.loads(download(assets["release.json"], 16000, timeout))
    if not isinstance(metadata, dict):
        raise ValueError("Invalid stable release metadata")
    archive = metadata.get("archive", "")
    if (metadata.get("repository") != REPOSITORY or metadata.get("version") != tag[1:]
            or metadata.get("contract_version") != 1
            or not re.fullmatch(r"unreal-mcp-\d+\.\d+\.\d+\.zip", archive)
            or archive != "unreal-mcp-" + tag[1:] + ".zip"
            or not re.fullmatch(r"[a-f0-9]{64}", metadata.get("sha256", ""))
            or assets.get(archive) != base + archive):
        raise ValueError("Invalid stable release metadata")
    return metadata, assets[archive]
