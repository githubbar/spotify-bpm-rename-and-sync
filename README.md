# spotify-bpm-rename-and-sync

Keep a local folder in sync with a Spotify playlist, then produce a
BPM-prefixed copy of every track for DJ software that sorts by filename.

```
Spotify playlist  ->  Playlist Name/Artist - Title.mp3  ->  Music/Playlist Name/182 Artist - Title.mp3
```

It wraps [spotdl](https://github.com/spotDL/spotify-downloader) rather than
replacing it, and adds two things on top:

1. **A BPM step** that tags each file and writes a copy whose filename starts
   with the tempo, so a plain alphabetical file listing becomes tempo-ordered.
2. **Three fixes to spotdl's YouTube Music matching**, which between them
   recovered 8 tracks in a 117-track library that spotdl gave up on with
   `LookupError: No results found for song`.

The matching fixes are applied by monkey-patching at runtime, so `spotdl`
itself is never edited and can be upgraded normally. If you only care about
those, see **[docs/matching-fixes.md](docs/matching-fixes.md)** — they are
independent of the BPM half and work on their own.

## Requirements

- Windows with PowerShell (the wrappers are `.ps1`; the Python is portable)
- Python 3.9+
- `ffmpeg` on your `PATH`, or let spotdl fetch it with `spotdl --download-ffmpeg`

## Setup

```powershell
git clone https://github.com/githubbar/spotify-bpm-rename-and-sync.git
cd spotify-bpm-rename-and-sync
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

One script does everything, for any playlist, on the first run and every run
after it:

```powershell
.\sync_playlist.ps1 "https://open.spotify.com/playlist/<playlist-id>"
```

The download folder is named after the playlist — nothing is hardcoded. On the
first run it creates `<Playlist Name>.spotdl` next to the script; later runs
sync against that file and pick up additions.

To also produce the BPM-prefixed copies:

```powershell
.\sync_playlist.ps1 "https://open.spotify.com/playlist/<id>" -AddBpm -BpmTargetRoot "D:\Music"
```

### Options

| Option | Default | What it does |
| --- | --- | --- |
| `-AddBpm` | off | Run the BPM step after downloading |
| `-BpmTargetRoot <path>` | `.\output` | Where BPM-prefixed copies go; each playlist gets a subfolder |
| `-PruneRemoved` | off | Allow deleting local files for tracks that left the playlist |

### Saving a playlist as its own command

Copy [`sync_playlist.example.ps1`](sync_playlist.example.ps1) to
`sync_<something>.local.ps1`, fill in your URL and library path, and run that
instead. `*.local.ps1` is gitignored, so your playlists stay private.

## Why `-PruneRemoved` is off by default

spotdl's `sync` deletes local files for tracks no longer in the playlist. That
is reasonable until Spotify's API intermittently fails to return a track's
artist: spotdl then drops that track from the sync file, and the delete pass
removes a file for a song that is *still in the playlist*.

That is not hypothetical — it happened during development and cost a file that
had to be re-downloaded. Deleting is therefore opt-in. The same transient
error also just silently omits tracks, so **if a sync looks short, run it
again** before concluding anything is wrong.

## The BPM step

`add_bpm_to_title.py` takes a source folder and an optional target folder:

```powershell
python add_bpm_to_title.py "My Playlist" "D:\Music\My Playlist"   # tag + copy
python add_bpm_to_title.py "My Playlist"                          # tag in place
```

For each MP3 it looks the tempo up on songbpm.com by artist and title, falls
back to local analysis with `librosa` if that lookup fails, writes the ID3
`bpm` tag, appends `(<n> BPM)` to the title, and copies the file to the target
prefixed with the tempo. Files already present in the target are skipped, so
re-runs are cheap.

Two things to know about the numbers:

- Tempos under 120 are **doubled**, on the assumption they were detected at
  half time. That is right for salsa and most Latin dance music and wrong for
  genuinely slow tracks.
- The `librosa` fallback is noticeably less reliable than the online lookup.
  One track in testing came back 234 BPM against a library that otherwise sat
  in the 167–210 range.

The musical key is scraped and printed but not currently stored anywhere.

## Known limitations

- The wrappers are PowerShell, so the orchestration is Windows-only. The
  Python (`spotdl_patched.py`, `add_bpm_to_title.py`, `playlist_name.py`)
  is cross-platform.
- Tracks credited to many artists can still fail. A five-artist credit builds
  a 130-character search query that matches nothing on YouTube Music.
- BPM lookup depends on songbpm.com's page structure and will need updating if
  that changes.

## Disclaimer

This tool downloads audio from YouTube using metadata from Spotify. Doing so
may violate the terms of service of either platform, and redistributing what
you download is very likely copyright infringement. It is provided for
personal use with content you have the right to access. You are responsible
for how you use it.

Not affiliated with Spotify, YouTube, or spotdl.

## License

MIT — see [LICENSE](LICENSE).
