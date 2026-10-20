"""Read-only stable-release checks, shared across hosts; never auto-activate."""
import json
import os
import re
from pathlib import Path
import time

from . import VERSION
from .experience import REPOSITORY
from .instances import InstanceError, Store
from .packages import Manager, NoStableRelease, ROOT, atomic_json, latest

TTL = 24 * 60 * 60
FAILURE_TTL = 60 * 60


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Invalid semantic version")
    return tuple(map(int, value.split(".")))


def local(manager, running_root=ROOT, running_version=VERSION):
    active = manager.active()
    target = manager.home / "packages" / active["package"] if active else None
    reconnect = bool(target and Path(running_root).resolve() != target.resolve())
    return {"running_version": running_version, "active": active,
            "reconnect_required": reconnect}


def check(home=None, force=False, offline=False, now=None):
    manager = Manager(home)
    path = manager.home / "update-check.json"
    now = time.time() if now is None else now
    cached = None
    try:
        if path.stat().st_size <= 32000:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(cached, dict) or cached.get("repository") != REPOSITORY
                    or not isinstance(cached.get("checked_at"), (int, float))
                    or cached.get("state") not in {"ok", "unpublished", "unknown"}):
                cached = None
    except (OSError, ValueError):
        pass
    disabled = os.environ.get("UNREAL_MCP_UPDATE_CHECK", "").lower() in {"off", "0", "false"}
    ttl = TTL if cached and cached["state"] != "unknown" else FAILURE_TTL
    fresh = bool(cached and 0 <= now - cached["checked_at"] < ttl)
    did_check = False
    if not offline and (force or not disabled and not fresh):
        store = Store(manager.home)
        try:
            with store.file_lock("update-check"):
                # Another host may have refreshed the cache while we were waiting.
                if not force and path.exists():
                    try:
                        other = json.loads(path.read_text(encoding="utf-8"))
                        if (isinstance(other, dict) and other.get("repository") == REPOSITORY
                                and isinstance(other.get("checked_at"), (int, float))
                                and other["checked_at"] > (cached or {}).get("checked_at", 0)):
                            return check(manager.home, offline=True, now=now)
                    except (OSError, ValueError, TypeError):
                        pass
                checked = {"repository": REPOSITORY, "checked_at": now}
                try:
                    metadata, url = latest(timeout=5)
                    checked.update(state="ok", available=metadata, download_url=url)
                except NoStableRelease as error:
                    checked.update(state="unpublished", reason=str(error))
                except (OSError, ValueError, KeyError, TypeError):
                    checked.update(state="unknown", reason="Release service unavailable or metadata invalid; retry later")
                    if cached and cached.get("available"):
                        checked["last_known_available"] = cached["available"]
                atomic_json(path, checked)
                cached, did_check = checked, True
        except InstanceError:
            pass  # Another host is checking; do not block UE work.
        finally:
            store.close()
    state = local(manager)
    result = {**state, "repository": REPOSITORY, "channel": "stable",
              "checked_at": cached.get("checked_at") if cached else None,
              "cached": not did_check, "automatic_checks": not disabled,
              "release_url": "https://github.com/" + REPOSITORY + "/releases",
              "status": "unknown", "stale": True}
    if not cached:
        result["reason"] = "No cached check; automatic checks disabled or another host is checking"
        return result
    ttl = FAILURE_TTL if cached["state"] == "unknown" else TTL
    result["stale"] = not 0 <= now - cached["checked_at"] < ttl
    if cached["state"] != "ok":
        result["status"] = cached["state"] if not result["stale"] else "unknown"
        result["reason"] = cached.get("reason", "No stable portable release has been published")
        if cached.get("last_known_available"):
            result["last_known_available"] = cached["last_known_available"]
        return result
    try:
        available = cached["available"]
        current = state["active"]["version"] if state["active"] else VERSION
        comparison = (version(available["version"]) > version(current)) - (version(available["version"]) < version(current))
        result["available"] = available
        result["status"] = ("update_available" if comparison > 0 else "ahead" if comparison < 0 else "current")
        if result["stale"]:
            result["last_known_status"], result["status"] = result["status"], "unknown"
        result["comparison_scope"] = "Published stable version numbers; development snapshots are not certified release contents"
    except (KeyError, ValueError, TypeError, AttributeError):
        result["status"], result["reason"] = "unknown", "Invalid cached release information; force a new check"
    return result
