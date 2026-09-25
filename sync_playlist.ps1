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
$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pythonPre = @()

if (-not (Test-Path -LiteralPath $pythonExe)) {
    # No venv yet. Fall back to a system Python, preferring the py
    # launcher, because the bare "python" on a stock Windows PATH is a
    # zero-byte App Execution Alias stub that only advertises the
    # Microsoft Store. It prints "Python was not found" and fails, which
    # is confusing if you assume it means something is wrong with this
    # script. So each candidate is probed with --version first.
    $pythonExe = $null
    foreach ($candidate in @(
            @{ Exe = "py";     Pre = @("-3") },
            @{ Exe = "python"; Pre = @() })) {

        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }

        $version = & $candidate.Exe @($candidate.Pre + @("--version")) 2>&1
        if ($LASTEXITCODE -eq 0 -and "$version" -match "Python 3") {
            $pythonExe = $candidate.Exe
            $pythonPre = $candidate.Pre
            break
        }
    }

    if (-not $pythonExe) {
        Write-Host "No working Python 3 found, and there is no .venv in this folder." -ForegroundColor Red
        Write-Host ""
        Write-Host "Windows does not ship Python. Install it with:"
        Write-Host "    winget install Python.Python.3.12"
        Write-Host ""
        Write-Host "then create the environment (see the README):"
        Write-Host "    py -m venv .venv"
        Write-Host "    .venv\Scripts\python.exe -m pip install -r requirements.txt"
        exit 1
    }
}

$forwarded = @($PlaylistUrl)
if ($AddBpm) { $forwarded += "--add-bpm" }
if ($BpmTargetRoot) { $forwarded += @("--bpm-target", $BpmTargetRoot) }
if ($PruneRemoved) { $forwarded += "--prune-removed" }
if ($DryRun) { $forwarded += "--dry-run" }

& $pythonExe @($pythonPre + @((Join-Path $PSScriptRoot "sync_playlist.py")) + $forwarded)
exit $LASTEXITCODE
