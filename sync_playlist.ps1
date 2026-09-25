<#
.SYNOPSIS
    Download or update a Spotify playlist into a folder named after it.

.DESCRIPTION
    Works on the first run and on every run after it. The first run creates
    "<Playlist Name>.spotdl" next to this script and downloads everything;
    later runs sync against that file, picking up additions and removing
    tracks that left the playlist.

    The download folder is named after the playlist. spotdl fills that in
    itself through its {list-name} output variable, so nothing is hardcoded
    and this script works for any playlist.

    Downloads go through spotdl_patched.py rather than spotdl directly, so
    the improved artist matching applies here too.

.PARAMETER PlaylistUrl
    The Spotify playlist URL.

.PARAMETER PruneRemoved
    Let spotdl delete local files for tracks that are no longer in the
    playlist. Off by default, and deliberately so: Spotify's API
    intermittently fails to return a track's artist, spotdl silently drops
    that track from the sync file, and the delete pass then removes a file
    for a song that is still in the playlist. That has already happened
    here once. Leave this off unless you are deliberately pruning, and
    check what it is about to remove.

.PARAMETER AddBpm
    Also run add_bpm_to_title.py afterwards, copying tagged files into
    <BpmTargetRoot>\<Playlist Name>.

.PARAMETER BpmTargetRoot
    Where -AddBpm copies finished files; each playlist gets its own
    subfolder. Defaults to an "output" folder next to this script. Point
    it at your music library, e.g. -BpmTargetRoot "D:\Music".

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

    [string]$BpmTargetRoot = (Join-Path $PSScriptRoot "output")
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
.venv\Scripts\Activate.ps1

$ytDlpArgs = "--extractor-args youtube:player_client=default,-android_sdkless"
$outputTemplate = "{list-name}/{artists} - {title}.{output-ext}"

# See -PruneRemoved: deleting is opt-in because a transient Spotify
# metadata failure otherwise costs you a file you still want.
$syncArgs = @()
if (-not $PruneRemoved) { $syncArgs += "--sync-without-deleting" }

# Ask Spotify what the playlist is called so the sync file matches the
# folder that {list-name} will create.
$playlistName = (python playlist_name.py $PlaylistUrl | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($playlistName)) {
    throw "Could not read the playlist name from Spotify for $PlaylistUrl"
}
$playlistName = $playlistName.Trim()

$syncFile = "$playlistName.spotdl"

if (Test-Path -LiteralPath $syncFile) {
    Write-Host "Updating '$playlistName' from $syncFile ..."
    python spotdl_patched.py sync $syncFile --yt-dlp-args $ytDlpArgs --output $outputTemplate @syncArgs
}
else {
    Write-Host "First run for '$playlistName', creating $syncFile ..."
    python spotdl_patched.py sync $PlaylistUrl --save-file $syncFile --yt-dlp-args $ytDlpArgs --output $outputTemplate @syncArgs
}

if ($LASTEXITCODE -ne 0) {
    throw "spotdl failed with exit code $LASTEXITCODE"
}

if ($AddBpm) {
    $bpmTarget = Join-Path $BpmTargetRoot $playlistName
    Write-Host "Adding BPM, copying to '$bpmTarget' ..."
    python add_bpm_to_title.py $playlistName $bpmTarget
}

Write-Host "Done: '$playlistName'"
