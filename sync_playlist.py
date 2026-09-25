"""
Download or update a Spotify playlist into a folder named after it.

Works on the first run and on every run after it. The first run creates
"<Playlist Name>.spotdl" next to this script and downloads everything;
later runs sync against that file, picking up additions.

The download folder is named after the playlist. spotdl fills that in
itself through its {list-name} output variable, so nothing is hardcoded
and this works for any playlist.

Downloads go through spotdl_patched.py rather than spotdl directly, so
the improved YouTube Music matching applies. See docs/matching-fixes.md.

Usage:
    python sync_playlist.py "https://open.spotify.com/playlist/<id>"
    python sync_playlist.py "<url>" --add-bpm --bpm-target ~/Music
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

try:
    from spotdl.types.playlist import Playlist
    from spotdl.utils.config import DEFAULT_CONFIG, get_config
    from spotdl.utils.formatter import sanitize_string
    from spotdl.utils.spotify import SpotifyClient
except ImportError as exc:
    sys.exit(
        f"Missing dependency: {exc.name}\n\n"
        "Install the requirements into this project's environment:\n"
        "    Windows:       .venv/Scripts/python.exe -m pip install -r requirements.txt\n"
        "    macOS / Linux: .venv/bin/python -m pip install -r requirements.txt\n\n"
        "If there is no .venv yet, create one first:\n"
        "    Windows:       py -m venv .venv\n"
        "    macOS / Linux: python3 -m venv .venv\n\n"
        "See the README for the full setup steps."
    )

__all__ = ["resolve_playlist_name", "build_sync_args", "main"]

SCRIPT_DIR = Path(__file__).resolve().parent

# Both of these are deliberately fixed rather than exposed as options:
# the output template is what makes the folder match the playlist name,
# and the yt-dlp args work around a YouTube player-client issue.
OUTPUT_TEMPLATE = "{list-name}/{artists} - {title}.{output-ext}"
YT_DLP_ARGS = "--extractor-args youtube:player_client=default,-android_sdkless"


def interpreter() -> str:
    """
    The Python to run the child commands with.

    Prefers a .venv next to this script, on either platform, so the
    script works whether or not the environment is activated. That is
    also why nothing here activates a venv: activation inside a script
    is fragile, and the Windows and Unix paths differ.
    """

    for candidate in (
        SCRIPT_DIR / ".venv" / "Scripts" / "python.exe",  # Windows
        SCRIPT_DIR / ".venv" / "bin" / "python",  # macOS / Linux
    ):
        if candidate.is_file():
            return str(candidate)

    return sys.executable


def _credentials() -> dict:
    """
    Use the same credentials the spotdl CLI would, falling back to the
    built-in defaults when there is no user config.
    """

    try:
        config = get_config()
    except Exception:  # pylint: disable=broad-except
        config = {}

    return {
        "client_id": config.get("client_id") or DEFAULT_CONFIG["client_id"],
        "client_secret": (
            config.get("client_secret") or DEFAULT_CONFIG["client_secret"]
        ),
    }


def resolve_playlist_name(playlist_url: str) -> str:
    """
    Ask Spotify what the playlist is called.

    Sanitized with spotdl's own `sanitize_string`, so the sync file name
    and the folder that {list-name} creates can never drift apart.
    """

    credentials = _credentials()
    SpotifyClient.init(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        no_cache=True,
    )

    metadata = Playlist.get_metadata(playlist_url)
    if isinstance(metadata, tuple):
        metadata = metadata[0]

    name = sanitize_string(metadata["name"]).strip()
    if not name:
        raise RuntimeError(f"Playlist has no usable name: {playlist_url}")

    return name


def build_sync_args(
    playlist_url: str,
    playlist_name: str,
    prune_removed: bool = False,
    sync_file_exists: Optional[bool] = None,
) -> List[str]:
    """
    Build the argument list passed to spotdl_patched.py.

    ### Arguments
    - playlist_url: the Spotify playlist URL.
    - playlist_name: the resolved, sanitized playlist name.
    - prune_removed: allow spotdl to delete files for tracks that have
      left the playlist. Off by default -- see the README.
    - sync_file_exists: override the on-disk check, for testing.
    """

    sync_file = f"{playlist_name}.spotdl"

    if sync_file_exists is None:
        sync_file_exists = (SCRIPT_DIR / sync_file).is_file()

    if sync_file_exists:
        args = ["spotdl_patched.py", "sync", sync_file]
    else:
        args = ["spotdl_patched.py", "sync", playlist_url, "--save-file", sync_file]

    args += ["--yt-dlp-args", YT_DLP_ARGS, "--output", OUTPUT_TEMPLATE]

    # A transient Spotify metadata failure makes spotdl drop a track from
    # the sync file; its delete pass would then remove a file for a song
    # that is still in the playlist. So deleting is opt-in.
    if not prune_removed:
        args.append("--sync-without-deleting")

    return args


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Download or update a Spotify playlist into a folder named "
            "after it, optionally adding BPM to the filenames."
        )
    )
    parser.add_argument("playlist_url", help="The Spotify playlist URL.")
    parser.add_argument(
        "--add-bpm",
        action="store_true",
        help="Also run the BPM step after downloading.",
    )
    parser.add_argument(
        "--bpm-target",
        metavar="ROOT",
        default=str(SCRIPT_DIR / "output"),
        help=(
            "Where --add-bpm writes BPM-prefixed copies; each playlist "
            "gets its own subfolder. Defaults to ./output"
        ),
    )
    parser.add_argument(
        "--prune-removed",
        action="store_true",
        help=(
            "Let spotdl delete local files for tracks no longer in the "
            "playlist. Off by default; see the README for why."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run, then exit.",
    )
    args = parser.parse_args(argv)

    python = interpreter()
    playlist_name = resolve_playlist_name(args.playlist_url)
    sync_args = build_sync_args(
        args.playlist_url, playlist_name, prune_removed=args.prune_removed
    )

    bpm_args = None
    if args.add_bpm:
        bpm_args = [
            "add_bpm_to_title.py",
            playlist_name,
            str(Path(args.bpm_target) / playlist_name),
        ]

    if args.dry_run:
        print("ARGV " + json.dumps(sync_args))
        if bpm_args:
            print("ARGV " + json.dumps(bpm_args))
        return 0

    sync_file = SCRIPT_DIR / f"{playlist_name}.spotdl"
    if sync_file.is_file():
        print(f"Updating '{playlist_name}' from {sync_file.name} ...")
    else:
        print(f"First run for '{playlist_name}', creating {sync_file.name} ...")

    result = subprocess.run([python, *sync_args], cwd=SCRIPT_DIR, check=False)
    if result.returncode != 0:
        print(f"spotdl failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode

    if bpm_args:
        print(f"Adding BPM, copying to '{bpm_args[2]}' ...")
        result = subprocess.run([python, *bpm_args], cwd=SCRIPT_DIR, check=False)
        if result.returncode != 0:
            print(
                f"BPM step failed with exit code {result.returncode}", file=sys.stderr
            )
            return result.returncode

    print(f"Done: '{playlist_name}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
