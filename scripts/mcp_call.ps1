#Requires -Version 5.1
<# Thin wrapper: Python owns sessions and target routing, never a shared PS session ID. #>
param(
    [string]$ToolName,
    [string]$ToolsetName,
    [string]$ScriptPath,
    [string]$ArgumentsJson = "{}",
    [string]$ArgumentsFile,
    [string]$ResultFile,
    [string]$McpUrl,
    [string]$Instance,
    [string]$TaskId,
    [string]$StateDir
)
$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction Stop
$pythonArgs = @("-X", "utf8", (Join-Path $PSScriptRoot "mcp_call.py"))
$tempArgs = $null
try {
    if ($ScriptPath) {
        $pythonArgs += @("--script", $ScriptPath)
    } else {
        $pythonArgs += @("--tool", $ToolName)
        if ($ArgumentsFile) {
            $pythonArgs += @("--args-file", $ArgumentsFile)
        } else {
            $tempArgs = [System.IO.Path]::GetTempFileName()
            [System.IO.File]::WriteAllText($tempArgs, $ArgumentsJson, [System.Text.UTF8Encoding]::new($false))
            $pythonArgs += @("--args-file", $tempArgs)
        }
    }
    foreach ($pair in @(
        @("--toolset", $ToolsetName), @("--out", $ResultFile), @("--url", $McpUrl),
        @("--instance", $Instance), @("--task-id", $TaskId), @("--state-dir", $StateDir)
    )) {
        if ($pair[1]) { $pythonArgs += $pair }
    }
    & $python.Source @pythonArgs
    if ($LASTEXITCODE -ne 0) { throw "MCP caller failed with exit code $LASTEXITCODE" }
} finally {
    if ($tempArgs) { Remove-Item -LiteralPath $tempArgs -Force }
}
