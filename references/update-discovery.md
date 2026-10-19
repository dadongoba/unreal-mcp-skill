# Discovering updates

There is one shared package per local user, not separate core versions per AI
client. Core scripts and published knowledge ship together. Plugins and engines
have independent versions; this check does not upgrade them.

## When and what is checked

ue_status automatically checks the original repository's stable GitHub Release,
then shares update-check.json across clients for 24 hours. Failed checks are
cached for one hour. Concurrent hosts do not run duplicate checks. Requests use
a five-second timeout each (release API and, when available, release.json); no
background daemon, recurring job, asset scan or telemetry upload is created.
Only public release metadata is requested; project paths, UE tools and experience
records are not sent. A plain Skill cannot check while no host is executing it.

Use ue_check_update(force=true) for an immediate fresh check, or
ue_check_update(offline=true) to read the cache without networking. CLI:

~~~text
python <SHARED_HOME>/launch.py check
python <SHARED_HOME>/launch.py check --force
python <SHARED_HOME>/launch.py check --offline
~~~

Set UNREAL_MCP_UPDATE_CHECK=off in the runtime environment to disable automatic
network checks. An explicit force check remains available. doctor reads the
cache only. Check failure does not block UE work or alter contribution consent.

| status | Meaning |
|---|---|
| update_available | Valid published portable stable version is newer than the active package |
| current | Same stable version number; this does not certify a modified development snapshot |
| ahead | Local active version is newer than the published stable version; never automatically downgrade |
| unpublished | No stable Release, or latest Release predates portable ZIP/release.json artifacts |
| unknown | Offline without fresh evidence, failed/rate-limited check, invalid metadata or stale cached success |

checked_at is a Unix UTC timestamp. stale/cached describe the evidence, not the
installation. Stale successful comparisons become unknown with last_known_status.
running_version and active identify the current process and the package selected
for the next launch. reconnect_required compares actual package paths, including
same-version package replacements; version-number equality alone is insufficient.
Existing MCP processes keep their loaded package until reconnected.

## Upgrade and publication

The only source is dadongoba/unreal-mcp-skill Releases with a vMAJOR.MINOR.PATCH
tag, draft=false and prerelease=false, canonical release.json and matching ZIP.
master changes, open/merged PRs, third-party forks and prerelease tags do not
establish an available stable upgrade. release.json binds the version, contract,
source commit, archive and SHA256; installation verifies the archive and all
manifest files. A checksum is not independent publisher authentication.

After authorization and finishing active tasks:

~~~text
python <SHARED_HOME>/launch.py update
python <SHARED_HOME>/launch.py doctor
~~~

Reconnect clients, then use ue_status and verify relevant operations. Activation
is blocked during active tasks; rollback remains available. The checker never
downloads a plugin, executes release notes or installs/activates a package.

Maintainers must merge reviewed code, then publish a matching version tag through
the portable release workflow. A historical source-only Release is insufficient.
Until the first portable stable artifacts exist, users receive unpublished and
must install a reviewed source checkout/archive explicitly. Never claim a PR
branch or an installed development build is the published latest stable release.
