#!/usr/bin/env python3
"""Trusted default-branch workflow: validated Issue data -> original-repository branch/PR."""
import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

from ue_mcp.experience import ExperienceError, REPOSITORY, parse_issue
from ue_mcp.transport import NoRedirect, TransportError


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, body=None, missing_ok=False):
        if not path.startswith("/repos/" + REPOSITORY + "/"):
            raise ExperienceError("GitHub request escaped the original repository")
        req = urllib.request.Request("https://api.github.com" + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            method=method, headers={"Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "unreal-mcp-experience"})
        try:
            with self.opener.open(req, timeout=30) as response:
                return json.load(response)
        except TransportError:
            raise ExperienceError("GitHub API redirects are refused") from None
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise ExperienceError("GitHub API returned HTTP {}".format(error.code)) from None


def ingest(event, api):
    if event.get("repository", {}).get("full_name") != REPOSITORY:
        raise ExperienceError("This workflow only accepts the configured original repository")
    issue = event.get("issue", {})
    number = issue.get("number")
    if type(number) is not int or number < 1 or "pull_request" in issue:
        raise ExperienceError("Invalid Issue event")
    record = parse_issue(issue.get("body") or "")
    record_id = record["record_id"]
    if issue.get("title") != "[unreal-mcp-experience] " + record_id:
        raise ExperienceError("Issue title must contain the validated record ID")
    prefix = "/repos/" + REPOSITORY
    branch = "submissions/experience-" + record_id
    path = "contributions/inbox/" + record_id + ".json"
    base = event["repository"].get("default_branch")
    if base != "master":
        raise ExperienceError("Default branch changed; review the ingestion target")
    # Always read the current Issue, not an outdated edited-event body.
    current = api.request("GET", prefix + "/issues/" + str(number))
    if (current.get("body") != issue.get("body") or current.get("title") != issue.get("title")):
        raise ExperienceError("Issue changed since this run started; process the newest event")
    reference = api.request("GET", prefix + "/git/ref/heads/" + urllib.parse.quote(branch, safe=""),
                            missing_ok=True)
    if reference is None:
        base_ref = api.request("GET", prefix + "/git/ref/heads/" + base)
        reference = api.request("POST", prefix + "/git/refs",
                                {"ref": "refs/heads/" + branch, "sha": base_ref["object"]["sha"]})
    contents_path = prefix + "/contents/" + path
    existing = api.request("GET", contents_path + "?ref=" + urllib.parse.quote(branch, safe=""),
                           missing_ok=True)
    payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if existing:
        saved = json.loads(base64.b64decode(existing["content"]).decode("utf-8"))
        if saved != record:
            raise ExperienceError("Submission ID already contains different data; use a new record ID")
    else:
        api.request("PUT", contents_path, {
            "message": "experience: receive " + record_id,
            "branch": branch, "content": base64.b64encode(payload.encode("utf-8")).decode("ascii")})
    pulls = api.request("GET", prefix + "/pulls?state=all&head=" +
                        urllib.parse.quote("dadongoba:" + branch, safe=""))
    if pulls:
        return pulls[0]["html_url"]
    comparison = api.request("GET", prefix + "/compare/" + base + "..." +
                             urllib.parse.quote(branch, safe=""))
    files = comparison.get("files", [])
    if len(files) != 1 or files[0].get("filename") != path or files[0].get("status") != "added":
        raise ExperienceError("Submission branch contains changes outside its one new inbox record")
    pull = api.request("POST", prefix + "/pulls", {
        "head": branch, "base": base, "draft": True,
        "title": "experience: review " + record_id,
        "body": "Receive structured, locally redacted experience from #" + str(number) +
                ".\n\nOnly the inbox JSON is added. Reporter verification is self-reported; "
                "this submission does not modify executable skill instructions.\n\n"
                "Validation ran in the ingestion workflow before this PR was created. "
                "PR workflows are not assumed to run for GITHUB_TOKEN-created PRs."})
    return pull["html_url"]


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise ExperienceError("Missing workflow token")
        url = ingest(event, GitHub(token))
        print("Submission PR: " + url)
        return 0
    except (ExperienceError, OSError, ValueError, KeyError, TypeError):
        # Do not echo untrusted bodies, API error bodies or credentials to privileged logs.
        print("Submission was not ingested. Check its schema, privacy patterns, "
              "event freshness and repository Actions PR permissions.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
