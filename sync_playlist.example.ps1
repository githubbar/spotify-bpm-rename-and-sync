# Template for your own playlist wrapper.
#
# Copy this to something like "sync_my_playlist.local.ps1", drop in your
# playlist URL and your music library path, and run it. Files matching
# *.local.ps1 are gitignored, so your personal playlists stay out of git.
#
#   -AddBpm                 also run the BPM step after downloading
#   -BpmTargetRoot <path>   where BPM-prefixed copies are written;
#                           each playlist gets its own subfolder
#   -PruneRemoved           allow deleting local files for tracks that
#                           have left the playlist (off by default)
#   -DryRun                 print what would run, without running it

& "$PSScriptRoot\sync_playlist.ps1" `
    "https://open.spotify.com/playlist/REPLACE_WITH_YOUR_PLAYLIST_ID" `
    -AddBpm -BpmTargetRoot "D:\Music"
