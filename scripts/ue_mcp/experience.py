"""Allowlisted experience records and a durable, opt-in original-repository outbox."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

from .instances import canonical

REPOSITORY = "dadongoba/unreal-mcp-skill"
MARKER = "unreal-mcp-experience/v1"
MAX_BYTES = 24000
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "experience.v1.json"


class ExperienceError(ValueError):
    pass


def _validate(value, rule, path="record"):
    kinds = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    kind = rule.get("type")
    if kind and (not isinstance(value, kinds[kind]) or kind == "integer" and isinstance(value, bool)):
        raise ExperienceError(path + ": invalid type")
    if "enum" in rule and value not in rule["enum"]:
        raise ExperienceError(path + ": value is not allowed")
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        if set(rule.get("required", [])) - set(value):
            raise ExperienceError(path + ": required fields are missing")
        if rule.get("additionalProperties") is False and set(value) - set(properties):
            raise ExperienceError(path + ": unknown fields are refused")
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], path + "." + key)
    elif isinstance(value, list):
        if not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", 100):
            raise ExperienceError(path + ": invalid list length")
        for item in value:
            _validate(item, rule.get("items", {}), path + "[]")
    elif isinstance(value, str):
        if not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 2000):
            raise ExperienceError(path + ": invalid text length")
        if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
            raise ExperienceError(path + ": invalid text format")


def validate(record):
    _validate(record, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise ExperienceError("Record exceeds the byte limit")
    return record


SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{15,}|github_pat_[A-Za-z0-9_]{15,}|"
    r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:authorization\s*:\s*(?:bearer|token)\s+\S+)|"
    r"(?i:(?:password|api[_ -]?key|access[_ -]?token)\s*[:=]\s*[^\s,;]+))"
)
PATHS = re.compile(r"(?i:\b[a-z]:[\\/][^\n\"<>]+)|"
                   r"(?<!\w)/(?:Users|home|mnt|Volumes|tmp|var|srv|opt)/[^\n\"<>]+")
ASSETS = re.compile(r"/Game/[A-Za-z0-9_./-]+|\b(?:BP|WBP|SK|SM|T|M|MI)_[A-Za-z0-9_]+\b")
CONTACT = re.compile(r"https?://[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
                     r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def sanitize(record, private_terms=()):
    flags = set()
    terms = sorted({str(x) for x in private_terms if str(x)}, key=len, reverse=True)

    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, str):
            return value
        if SECRET.search(value):
            flags.add("secret_detected")
            value = SECRET.sub("<REDACTED_SECRET>", value)
        if CONTROLS.search(value):
            flags.add("control_characters")
            value = CONTROLS.sub("", value)
        value = PATHS.sub("<LOCAL_PATH>", value)
        value = ASSETS.sub("<ASSET>", value)
        value = CONTACT.sub("<CONTACT_OR_URL>", value)
        for term in terms:
            pattern = re.escape(term) if len(term) >= 4 else r"(?<!\w)" + re.escape(term) + r"(?!\w)"
            value = re.sub(pattern, "<PRIVATE>", value, flags=re.I)
        return value

    return clean(record), sorted(flags)


def public_check(record):
    """Server validation rejects rather than silently reinterprets submitted evidence."""
    validate(record)
    clean, flags = sanitize(record)
    if flags or clean != record:
        raise ExperienceError("Record still contains disallowed sensitive patterns")
    return record


def issue_body(record):
    public_check(record)
    fence = chr(96) * 3
    return MARKER + "\n\n" + fence + "json\n" + json.dumps(record, ensure_ascii=False, indent=2) + "\n" + fence + "\n"


def parse_issue(body):
    if len(body.encode("utf-8")) > MAX_BYTES + 1000:
        raise ExperienceError("Issue body exceeds the byte limit")
    match = re.fullmatch(re.escape(MARKER) + r"\s+\x60{3}json\n(.*)\n\x60{3}\s*", body, re.S)
    if not match:
        raise ExperienceError("Not a structured experience submission")
    try:
        record = json.loads(match[1])
    except ValueError as error:
        raise ExperienceError("Invalid submission JSON") from error
    return public_check(record)


class Queue:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS contribution_config(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS contributions(
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL, issue_url TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, error TEXT, source_project TEXT);
            CREATE TABLE IF NOT EXISTS finalizations(task TEXT PRIMARY KEY, record TEXT NOT NULL);
        """)
        self.db.commit()

    def config(self):
        rows = dict(self.db.execute("SELECT key,value FROM contribution_config"))
        return {"mode": rows.get("mode", "local"),
                "denied_projects": json.loads(rows.get("denied_projects", "[]")),
                "repository": REPOSITORY}

    def configure(self, mode, accept_public=False, deny_project=None):
        if mode not in {"off", "local", "auto"}:
            raise ExperienceError("Invalid contribution mode")
        if mode == "auto" and not accept_public:
            raise ExperienceError("Auto mode requires --accept-public-upload after reviewing the policy")
        denied = self.config()["denied_projects"]
        if deny_project and canonical(deny_project) not in denied:
            denied.append(canonical(deny_project))
        with self.db:
            for key, value in (("mode", mode), ("denied_projects", json.dumps(denied))):
                self.db.execute("INSERT OR REPLACE INTO contribution_config VALUES(?,?)", (key, value))

    def finalize(self, task_id, record, private_terms=(), project=None):
        from . import VERSION
        from .instances import valid_id
        valid_id(task_id)
        config = self.config()
        if config["mode"] == "off":
            return {"status": "disabled"}
        if config["denied_projects"] and not project:
            raise ExperienceError("Project context is required to enforce the project privacy policy")
        if project and canonical(project) in config["denied_projects"]:
            return {"status": "disabled"}
        record = json.loads(json.dumps(record))
        if not isinstance(record, dict) or not isinstance(record.get("environment", {}), dict):
            raise ExperienceError("Experience and environment must be JSON objects")
        record.setdefault("schema_version", 1)
        record.setdefault("record_id", str(uuid.uuid4()))
        record.setdefault("environment", {}).setdefault("skill_version", VERSION)
        validate(record)
        metadata = {key: record[key] for key in ("schema_version", "record_id", "environment", "kind", "domain")}
        clean, flags = sanitize({key: value for key, value in record.items() if key not in metadata}, private_terms)
        clean.update(metadata)
        validate(clean)
        stable = {key: value for key, value in clean.items() if key != "record_id"}
        fingerprint = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.store.transaction():
            existing = self.db.execute("SELECT record FROM finalizations WHERE task=?", (task_id,)).fetchone()
            if existing:
                saved = self.db.execute("SELECT * FROM contributions WHERE id=?", (existing["record"],)).fetchone()
                if saved["fingerprint"] != fingerprint:
                    raise ExperienceError("Task was finalized with different content; use a new revision task ID")
                return dict(saved)
            duplicate = self.db.execute("SELECT * FROM contributions WHERE fingerprint=?", (fingerprint,)).fetchone()
            if duplicate:
                record_id = duplicate["id"]
            else:
                record_id = clean["record_id"]
                self.db.execute(
                    "INSERT INTO contributions(id,payload,fingerprint,status,error,source_project) VALUES(?,?,?,?,?,?)",
                    (record_id, json.dumps(clean, ensure_ascii=False), fingerprint,
                     "needs_review" if flags else "queued", ",".join(flags) or None,
                     canonical(project) if project else None))
            self.db.execute("INSERT INTO finalizations VALUES(?,?)", (task_id, record_id))
        return dict(self.db.execute("SELECT * FROM contributions WHERE id=?", (record_id,)).fetchone())

    @staticmethod
    def gh(argv):
        try:
            return subprocess.run(["gh", *argv], check=True, capture_output=True,
                                  text=True, encoding="utf-8", timeout=45).stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise ExperienceError("GitHub command failed: " + type(error).__name__) from error

    def publish(self, record_id, runner=None):
        if self.config()["mode"] != "auto":
            raise ExperienceError("Remote publishing requires opt-in auto mode")
        runner = runner or self.gh
        with self.store.file_lock("publish:" + record_id):
            row = self.db.execute("SELECT * FROM contributions WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise ExperienceError("Unknown experience ID")
            denied = self.config()["denied_projects"]
            if denied and (not row["source_project"] or row["source_project"] in denied):
                raise ExperienceError("Current project policy blocks publishing this record")
            if row["status"] in {"submitted", "needs_review", "auth_required", "failed"}:
                return dict(row)
            if row["next_attempt"] > time.time():
                return dict(row)
            record = public_check(json.loads(row["payload"]))
            try:
                candidates = json.loads(runner([
                    "issue", "list", "--repo", REPOSITORY, "--state", "all", "--limit", "100",
                    "--search", record_id + " in:title", "--json", "title,url,body"]))
                match = next((item for item in candidates
                              if item["title"] == "[unreal-mcp-experience] " + record_id), None)
                if match:
                    if parse_issue(match["body"]) != record:
                        raise ExperienceError("Existing submission ID has different content")
                    url = match["url"]
                elif row["status"] in {"submitting", "unknown"}:
                    with self.db:
                        self.db.execute("UPDATE contributions SET status='unknown',error=? WHERE id=?",
                                        ("Awaiting remote reconciliation; no duplicate was created", record_id))
                    return dict(self.db.execute("SELECT * FROM contributions WHERE id=?", (record_id,)).fetchone())
                else:
                    with self.db:
                        self.db.execute("UPDATE contributions SET status='submitting' WHERE id=?", (record_id,))
                    with tempfile.TemporaryDirectory(prefix="ue-experience-") as folder:
                        body = Path(folder) / "submission.md"
                        body.write_text(issue_body(record), encoding="utf-8")
                        url = runner(["issue", "create", "--repo", REPOSITORY, "--title",
                                      "[unreal-mcp-experience] " + record_id, "--body-file", str(body)]).strip()
                if not re.fullmatch(r"https://github\.com/" + re.escape(REPOSITORY) + r"/issues/\d+", url):
                    raise ExperienceError("GitHub did not return the expected original-repository issue URL")
                with self.db:
                    self.db.execute("UPDATE contributions SET status='submitted',issue_url=?,error=NULL WHERE id=?",
                                    (url, record_id))
            except (ExperienceError, ValueError, KeyError, TypeError):
                current = self.db.execute("SELECT status FROM contributions WHERE id=?", (record_id,)).fetchone()[0]
                attempts = row["attempts"] + 1
                status = "unknown" if current in {"submitting", "unknown"} else "failed" if attempts >= 5 else "retry_wait"
                with self.db:
                    self.db.execute("UPDATE contributions SET status=?,attempts=?,next_attempt=?,error=? WHERE id=?",
                                    (status, attempts, time.time() + min(3600, 30 * 2 ** attempts),
                                     "Publishing did not complete; inspect gh auth status and reconcile", record_id))
            return dict(self.db.execute("SELECT * FROM contributions WHERE id=?", (record_id,)).fetchone())
