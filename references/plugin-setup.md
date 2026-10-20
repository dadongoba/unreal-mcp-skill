# Version-aware upstream plugin setup

Core/knowledge updates and upstream UE plugins are independent channels. A core
version check does not install third-party plugins. For a user-authorized project
setup/connect workflow, ue_setup_project automatically selects and installs a
matching upstream plugin; ordinary status/inspection never installs it.

## Discovery and selection

The reviewed native-HTTP provider is
[AvatarGanymede/ue5.7-mcp](https://github.com/AvatarGanymede/ue5.7-mcp).
The provider repository name is not a fixed engine-version restriction. The
installer checks its 30 most recent Releases, cached for 24 hours. force=true
refreshes immediately. Stable tags must be vMAJOR.MINOR.PATCH. Assets must be
named UnrealMCP-VERSION-UEMAJOR.MINOR-Win64-GitHub.zip, with a canonical upstream
download URL and a GitHub SHA256 digest. Drafts, prereleases, source archives,
other hosts/platforms and missing-digest assets are not automatic candidates.

If this same provider later publishes compatible 5.6 or earlier artifacts using
the reviewed format, selection can discover them without a hardcoded 5.7 pin.
No compatible asset means no install and no claim of support. A completely new
repository/protocol requires an explicit provider adapter review; public release
text is never executed or converted into skill instructions.

Use .uproject EngineAssociation and the selected engine's Engine/Build/Build.version.
The root can come from an existing project registration or Windows Epic engine
registrations; ambiguous/missing roots require the caller to select one.
Disagreements fail; custom/GUID associations require the actual engine root.
Installation requires the actual engine root to compare its
Engine/Binaries/Win64/UnrealEditor.modules BuildId with the plugin. The real
v0.6.1 asset targets 5.7.4 (BuildId 47537391), not every possible 5.7 build.
Package provenance, DLL/modules digests and descriptor platform/version are also
checked. A mismatching/custom engine needs a matching build or manual source
compilation; the installer never edits BuildId to bypass compatibility.

## MCP and CLI

ue_plugin_status(project, engine?, force?) only inspects available versions.
ue_setup_project(instance, project, engine, port?, force?) performs setup for
that selected project, including registering its native backend and isolated port.
ue_launch_instance(instance) can launch the registered managed editor through MCP;
it does not print into the protocol stream or stop another process. Poll
ue_capabilities after startup, then begin ownership for native health/readback.

~~~text
python scripts/ue_connect.py plugin-status --project <PROJECT.uproject> --engine <UE_ROOT>
python scripts/ue_connect.py setup --instance ue57 --project <PROJECT.uproject> --engine <UE_ROOT>
python scripts/ue_connect.py launch --instance ue57
python scripts/ue_connect.py check --instance ue57
~~~

UE 5.8+ selects the existing Epic path and does not download the 5.7 plugin.
For earlier versions with an eligible asset, setup selects the newest matching
stable plugin; it does not downgrade a newer managed installation. It enables
ModelContextProtocol and PythonScriptPlugin only in the selected .uproject and
preserves other settings. It assigns a free port unless explicitly chosen;
Avatar launch passes UE_MCP_PORT in that child process's environment. No machine
global port setting is changed. Each instance still needs its own task and
verified listener/project identity.

An existing unmanaged MCP plugin, duplicate engine/project plugin, local edits,
active task or occupied explicit port blocks replacement. A running selected
editor returns close_editor_required when an install/update is necessary. It is
never killed or automatically restarted. Already-current installations are
idempotent and avoid redownloading. Review the returned status rather than
treating any successful JSON response as successful installation.

## Installation, upgrades and verification

ZIP extraction is size/count bounded and rejects unsafe paths, links and files
outside Plugins/ModelContextProtocol. The archive is verified before staging.
Only the project plugin directory is activated, with a receipt of exact files.
Before a managed upgrade, the prior plugin and .uproject are backed up beneath
Saved/UnrealMCPBackups/<unique-id>/, outside UE plugin discovery. Activation and
task creation coordinate through the shared lock. A failed .uproject save
restores the previous plugin. Do not manually delete backups while troubleshooting.

Launch/restart the selected project, then inspect ue_capabilities, native health,
and perform relevant compile/readback/PIE verification before claiming behavior.
If a new upstream version changes its contract, report the mismatch and retain
the backup; a new ZIP does not prove new capabilities work. Source/hash checks,
simulated tests and actual UE execution are distinct evidence.

Maintainers extend provider adapters when new repositories or incompatible
formats emerge. Upstream catalog checks alone cannot port C++ between engines,
build missing binaries, update authoring guidance or certify every engine patch.
