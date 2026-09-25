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

- Python 3.9 or newer
- `ffmpeg`

Install ffmpeg whichever way suits your platform:

| Platform | Command |
| --- | --- |
| Windows | `winget install ffmpeg` |
| macOS | `brew install ffmpeg` |
| Debian / Ubuntu | `sudo apt install ffmpeg` |
| Any | `spotdl --download-ffmpeg` (fetches a private copy) |

## Setup

### Windows

Open **PowerShell**, then:

```powershell
git clone https://github.com/githubbar/spotify-bpm-rename-and-sync.git
cd spotify-bpm-rename-and-sync
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

You do not need to activate the venv — the scripts find `.venv` on their own.

If PowerShell refuses to run the `.ps1` files with a message about scripts
being disabled, allow local scripts once per user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS / Linux

```bash
git clone https://github.com/githubbar/spotify-bpm-rename-and-sync.git
cd spotify-bpm-rename-and-sync
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Usage

One command does everything, for any playlist, on the first run and every run
after it. The first run creates `<Playlist Name>.spotdl` next to the script and
downloads everything; later runs sync against that file and pick up additions.

The download folder is named after the playlist — nothing is hardcoded.

### Windows

```powershell
.\sync_playlist.ps1 "https://open.spotify.com/playlist/<playlist-id>"
```

Also writing BPM-prefixed copies into your music library:

```powershell
.\sync_playlist.ps1 "https://open.spotify.com/playlist/<playlist-id>" -AddBpm -BpmTargetRoot "D:\Music"
```

To see what would run without running it, add `-DryRun`.

`sync_playlist.ps1` is a thin wrapper that forwards to `sync_playlist.py`; if
you prefer, call the Python directly on Windows too:

```powershell
.venv\Scripts\python.exe sync_playlist.py "https://open.spotify.com/playlist/<playlist-id>" --add-bpm --bpm-target "D:\Music"
```

### macOS / Linux

```bash
.venv/bin/python sync_playlist.py "https://open.spotify.com/playlist/<playlist-id>"
.venv/bin/python sync_playlist.py "https://open.spotify.com/playlist/<playlist-id>" --add-bpm --bpm-target ~/Music
```

### Options

| PowerShell | Python | Default | What it does |
| --- | --- | --- | --- |
| `-AddBpm` | `--add-bpm` | off | Run the BPM step after downloading |
| `-BpmTargetRoot <path>` | `--bpm-target <path>` | `./output` | Where BPM-prefixed copies go; each playlist gets a subfolder |
| `-PruneRemoved` | `--prune-removed` | off | Allow deleting local files for tracks that left the playlist |
| `-DryRun` | `--dry-run` | off | Print the commands that would run, then exit |

### Saving a playlist as its own command

Rather than retyping a URL, copy
[`sync_playlist.example.ps1`](sync_playlist.example.ps1) to
`sync_<something>.local.ps1`, fill in your URL and library path, and run that.
`*.local.ps1` is gitignored, so your playlists stay private. On macOS and Linux
a two-line shell script calling `sync_playlist.py` does the same job.

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

`add_bpm_to_title.py` takes a source folder and an optional target folder, and
can be used on its own:

```powershell
# Windows
.venv\Scripts\python.exe add_bpm_to_title.py "My Playlist" "D:\Music\My Playlist"   # tag + copy
.venv\Scripts\python.exe add_bpm_to_title.py "My Playlist"                            # tag in place
```

```bash
# macOS / Linux
.venv/bin/python add_bpm_to_title.py "My Playlist" ~/Music/"My Playlist"
.venv/bin/python add_bpm_to_title.py "My Playlist"
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

- Developed and tested on Windows. Everything that does real work is plain
  Python and platform-independent, but the macOS and Linux paths have not been
  exercised — reports welcome.
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
