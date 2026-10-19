"""Host-independent operations shared by MCP and command-line entrypoints."""
import getpass
from pathlib import Path

from .experience import ExperienceError, Queue
from .instances import InstanceError, process_identity
from .transport import Client, is_discovery
from .backends import dispatch, discover


def capabilities(store, instance):
    profile = store.resolve(instance)
    identity = process_identity(profile["url"], profile["project"])
    with Client(profile["url"], timeout=15) as client:
        result = discover(client, profile.get("backend", "epic-toolsets"))
        if process_identity(profile["url"], profile["project"]) != identity:
            raise InstanceError("Editor changed during capability discovery")
    return dict(result, instance=instance, identity_verified=True)


def call(store, tool, arguments=None, instance=None, task_id=None, toolset=None,
         url=None, timeout=120):
    if not isinstance(tool, str) or not tool or arguments is not None and not isinstance(arguments, dict):
        raise ValueError("Supply a tool name and an arguments object")
    if isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise ValueError("Timeout must be 1-120 seconds")
    profile = store.resolve(instance, url)
    backend = profile.get("backend", "epic-toolsets")
    if is_discovery(tool, toolset) and not task_id:
        if backend not in {"epic-toolsets", "auto"}:
            raise ValueError("Use ue_capabilities for backend-neutral discovery")
        with Client(profile["url"], timeout=timeout) as client:
            return dispatch(client, backend, tool, arguments, toolset)
    with store.write_guard(profile, task_id) as identity:
        with Client(profile["url"], timeout=timeout) as client:
            def verify_before_send():
                if process_identity(profile["url"], profile["project"]) != identity:
                    raise InstanceError("Editor changed during initialize/discovery; no write was sent")
            return dispatch(client, backend, tool, arguments, toolset, verify_before_send)


def finalize(store, task_id, record, instance=None, private_terms=()):
    """End ownership even on validation failure; never collect tool results."""
    try:
        task = store.db.execute("SELECT instance FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task and instance and task["instance"] != instance:
            raise ExperienceError("Privacy instance disagrees with the task binding")
        selected = instance or (task["instance"] if task else None)
        profile = store.resolve(selected) if selected or store.profiles() else None
        if record is None:
            return {"status": "no_experience"}
        terms = [str(Path.home()), getpass.getuser(), *private_terms]
        for registered in store.profiles().values():
            terms += [registered["project"], Path(registered["project"]).stem]
            if registered.get("engine"):
                terms.append(registered["engine"])
        queue = Queue(store)
        row = queue.finalize(task_id, record, terms, profile["project"] if profile else None)
        if queue.config()["mode"] == "auto" and row["status"] == "queued":
            row = queue.publish(row["id"])
        return {key: value for key, value in row.items()
                if key not in {"payload", "source_project", "fingerprint"}}
    finally:
        store.end(task_id)
