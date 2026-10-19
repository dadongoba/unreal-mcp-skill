"""Local instance registry, process identity, and cross-process write ownership."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit

from .transport import DEFAULT_URL


class InstanceError(RuntimeError):
    pass


def canonical(path):
    return os.path.normcase(os.path.realpath(os.path.expanduser(str(path))))


def endpoint(url):
    parts = urlsplit(url)
    if (parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parts.username or parts.password or parts.query or parts.fragment):
        raise InstanceError("Only local HTTP MCP endpoints without credentials/query are supported")
    try:
        port = parts.port or 80
    except ValueError as error:
        raise InstanceError("Invalid MCP port") from error
    host = "[::1]" if parts.hostname == "::1" else "127.0.0.1"
    return urlunsplit(("http", "{}:{}".format(host, port), parts.path or "/mcp", "", ""))


def valid_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise InstanceError("IDs must contain 1-80 letters, digits, dots, underscores or hyphens")
    return value


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise InstanceError("Cannot inspect editor identity: {}".format(type(error).__name__)) from error


def windows_argv(command):
    import ctypes
    from ctypes import wintypes
    argc = ctypes.c_int()
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(wintypes.LPWSTR)
    ptr = split(command, ctypes.byref(argc))
    if not ptr:
        raise InstanceError("Cannot parse editor command line")
    try:
        return [ptr[i] for i in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ptr)


def posix_argv(pid):
    proc = Path("/proc") / str(pid)
    if proc.exists():
        return (proc / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
    if sys.platform == "darwin":
        # ps command output is ambiguous for paths with spaces. KERN_PROCARGS2
        # preserves the actual NUL-delimited argv; do not split display strings.
        import ctypes
        import struct
        libc = ctypes.CDLL(None, use_errno=True)
        mib, size = (ctypes.c_int * 3)(1, 49, pid), ctypes.c_size_t()
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            raise InstanceError("Cannot inspect macOS editor arguments")
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            raise InstanceError("Cannot inspect macOS editor arguments")
        raw = buffer.raw[:size.value]
        argc = struct.unpack_from("i", raw)[0]
        parts = raw[4:].split(b"\0", 1)[1].lstrip(b"\0").split(b"\0")
        return [part.decode("utf-8") for part in parts[:argc]]
    raise InstanceError("This platform has no verified editor argument inspector")


def project_is_running(project):
    if sys.platform == "win32":
        script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding="
                  "[System.Text.UTF8Encoding]::new(); ConvertTo-Json -Compress -InputObject "
                  "@(Get-CimInstance Win32_Process -Filter \"Name='UnrealEditor.exe'\" "
                  "| Select-Object -ExpandProperty CommandLine)")
        commands = json.loads(_run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]))
        arguments = [windows_argv(command) for command in commands if command]
    else:
        output = _run(["ps", "-axo", "pid=,comm="])
        arguments = []
        for line in output.splitlines():
            fields = line.strip().split(maxsplit=1)
            if len(fields) == 2 and Path(fields[1]).name == "UnrealEditor":
                arguments.append(posix_argv(int(fields[0])))
    return any(canonical(arg) == canonical(project) for argv in arguments
               for arg in argv if arg.lower().endswith(".uproject"))


def process_identity(url, project):
    """Verify the listening process, its generation and its exact .uproject argument."""
    port = urlsplit(endpoint(url)).port
    if sys.platform == "win32":
        script = (
            "$ErrorActionPreference='Stop'; [Console]::OutputEncoding="
            "[System.Text.UTF8Encoding]::new(); "
            "$ids=@(Get-NetTCPConnection -State Listen -LocalPort " + str(port) +
            " | Select-Object -ExpandProperty OwningProcess -Unique); "
            "if($ids.Count -ne 1){throw 'Expected one listener'}; "
            "$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ids[0]); "
            "@{pid=$p.ProcessId; started=$p.CreationDate.ToUniversalTime().ToString('o'); "
            "command=$p.CommandLine; executable=$p.ExecutablePath} | ConvertTo-Json -Compress"
        )
        data = json.loads(_run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]))
        argv = windows_argv(data["command"])
    else:
        pids = set(re.findall(r"^p(\d+)$", _run(
            ["lsof", "-nP", "-iTCP:{}".format(port), "-sTCP:LISTEN", "-Fp"]), re.M))
        if len(pids) != 1:
            raise InstanceError("Expected exactly one listening process")
        pid = int(next(iter(pids)))
        proc = Path("/proc") / str(pid)
        argv = posix_argv(pid)
        if proc.exists():
            started = (proc / "stat").read_text().rsplit(")", 1)[1].split()[19]
        else:
            started = _run(["ps", "-p", str(pid), "-o", "lstart="])
        data = {"pid": pid, "started": started, "executable": argv[0]}
    executable = Path(data.get("executable") or argv[0]).name.lower()
    if executable not in {"unrealeditor", "unrealeditor.exe"}:
        raise InstanceError("The listener is not an UnrealEditor process")
    projects = [canonical(arg) for arg in argv if arg.lower().endswith(".uproject")]
    if canonical(project) not in projects or not data.get("started"):
        raise InstanceError("The listener does not match the registered project")
    return {"pid": int(data["pid"]), "started": str(data["started"]),
            "project": canonical(project), "url": endpoint(url)}


class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("UNREAL_MCP_HOME") or Path.home() / ".unreal-mcp")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.root / "runtime.sqlite"), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS instances(name TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY, instance TEXT NOT NULL, binding TEXT NOT NULL,
                expires REAL NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS leases(resource TEXT PRIMARY KEY, task TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def profiles(self):
        return {row["name"]: json.loads(row["data"]) for row in self.db.execute(
            "SELECT name,data FROM instances ORDER BY name")}

    def register(self, name, project, url=DEFAULT_URL, engine=None):
        valid_id(name)
        path = Path(project).expanduser().resolve()
        if path.suffix.lower() != ".uproject" or not path.is_file():
            raise InstanceError("Registration requires an existing .uproject file")
        profile = {"name": name, "project": canonical(path), "url": endpoint(url),
                   "engine": canonical(engine) if engine else None}
        with self.transaction():
            if self.db.execute("SELECT 1 FROM tasks WHERE instance=? AND status='active' AND expires>?",
                               (name, time.time())).fetchone():
                raise InstanceError("End the instance's active task before changing its registration")
            for other, item in self.profiles().items():
                if other != name and item["url"] == profile["url"]:
                    raise InstanceError("This endpoint already belongs to another instance")
            self.db.execute("INSERT OR REPLACE INTO instances VALUES(?,?)",
                            (name, json.dumps(profile)))
        return profile

    def resolve(self, name=None, url=None):
        profiles = self.profiles()
        if name:
            if name not in profiles:
                raise InstanceError("Unknown instance; run ue_connect.py register first")
            result = profiles[name]
            if url and endpoint(url) != result["url"]:
                raise InstanceError("--url disagrees with the selected instance")
            return result
        if url:
            normalized = endpoint(url)
            matches = [p for p in profiles.values() if p["url"] == normalized]
            return matches[0] if matches else {"name": None, "url": normalized, "project": None}
        if len(profiles) == 1:
            return next(iter(profiles.values()))
        if len(profiles) > 1:
            raise InstanceError("Multiple instances registered; specify --instance or --url")
        return {"name": None, "url": DEFAULT_URL, "project": None}

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    @staticmethod
    def resources(profile):
        return ["instance:" + profile["name"], "project:" + canonical(profile["project"])]

    def begin(self, profile, task_id, identity, seconds=900):
        valid_id(task_id)
        if not 180 <= seconds <= 86400:
            raise InstanceError("Task leases must be between 180 and 86400 seconds")
        binding = json.dumps(identity, sort_keys=True)
        with self.file_lock("package-activation"), self.transaction():
            old = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if old and (old["status"] != "active" or old["expires"] <= time.time()
                        or old["instance"] != profile["name"] or old["binding"] != binding):
                raise InstanceError("Task ID is closed, expired or bound to a different editor")
            for resource in self.resources(profile):
                owner = self.db.execute(
                    "SELECT t.id FROM leases l JOIN tasks t ON l.task=t.id "
                    "WHERE l.resource=? AND t.status='active' AND t.expires>?",
                    (resource, time.time())).fetchone()
                if owner and owner["id"] != task_id:
                    raise InstanceError("Instance or project is leased by another task")
            self.db.execute("INSERT OR REPLACE INTO tasks VALUES(?,?,?,?,?)",
                            (task_id, profile["name"], binding, time.time() + seconds, "active"))
            for resource in self.resources(profile):
                self.db.execute("INSERT OR REPLACE INTO leases VALUES(?,?)", (resource, task_id))

    def verify_task(self, profile, task_id, identity):
        with self.transaction():
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if (not row or row["status"] != "active" or row["expires"] <= time.time()
                    or row["instance"] != profile["name"]
                    or row["binding"] != json.dumps(identity, sort_keys=True)):
                raise InstanceError("Task binding expired or editor identity changed; begin a new task")
            for resource in self.resources(profile):
                owner = self.db.execute("SELECT task FROM leases WHERE resource=?", (resource,)).fetchone()
                if not owner or owner["task"] != task_id:
                    raise InstanceError("Task no longer owns the instance/project")
            self.db.execute("UPDATE tasks SET expires=? WHERE id=?", (time.time() + 900, task_id))

    def end(self, task_id):
        with self.transaction():
            self.db.execute("UPDATE tasks SET status='closed' WHERE id=?", (task_id,))
            self.db.execute("DELETE FROM leases WHERE task=?", (task_id,))

    @contextlib.contextmanager
    def write_guard(self, profile, task_id, inspector=None):
        if not profile.get("name") or not task_id:
            raise InstanceError("Writes require a registered instance and --task-id (run begin first)")
        inspector = inspector or process_identity
        # OS file locks also serialize two callers using the SAME task ID, and release on crash.
        with contextlib.ExitStack() as stack:
            for resource in sorted(self.resources(profile)):
                stack.enter_context(self.file_lock(resource))
            identity = inspector(profile["url"], profile["project"])
            self.verify_task(profile, task_id, identity)
            yield identity

    @contextlib.contextmanager
    def file_lock(self, resource):
        folder = self.root / "locks"
        folder.mkdir(exist_ok=True)
        path = folder / (hashlib.sha256(resource.encode()).hexdigest() + ".lock")
        with path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise InstanceError("Another call is modifying this instance/project; retry later") from error
            try:
                yield
            finally:
                handle.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
