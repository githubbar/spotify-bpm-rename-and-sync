<#
.SYNOPSIS
    Windows convenience wrapper around sync_playlist.py.

.DESCRIPTION
    Forwards to sync_playlist.py, which does the actual work and runs on
    Windows, macOS and Linux alike. This wrapper exists so Windows users
    can keep using PowerShell switches; it adds no behaviour of its own.

    See sync_playlist.py --help, or the README, for what the options do.

.EXAMPLE
    .\sync_playlist.ps1 "https://open.spotify.com/playlist/<playlist-id>"

.EXAMPLE
    .\sync_playlist.ps1 "https://open.spotify.com/playlist/<playlist-id>" -AddBpm -BpmTargetRoot "D:\Music"
#>

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$PlaylistUrl,

    [switch]$PruneRemoved,

    [switch]$AddBpm,

    [string]$BpmTargetRoot,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

# Prefer the project venv so this works without activating it.
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$forwarded = @($PlaylistUrl)
if ($AddBpm) { $forwarded += "--add-bpm" }
if ($BpmTargetRoot) { $forwarded += @("--bpm-target", $BpmTargetRoot) }
if ($PruneRemoved) { $forwarded += "--prune-removed" }
if ($DryRun) { $forwarded += "--dry-run" }

& $python (Join-Path $PSScriptRoot "sync_playlist.py") @forwarded
exit $LASTEXITCODE
