"""
Print the filesystem-safe name of a Spotify playlist.

`sync_playlist.ps1` uses this to name the .spotdl sync file after the
playlist. spotdl names the download folder itself via its `{list-name}`
output variable, and this reuses spotdl's own `sanitize_string`, so the
sync file and the folder can never drift apart.

Usage: python playlist_name.py <spotify playlist url>
"""

import sys

from spotdl.types.playlist import Playlist
from spotdl.utils.config import DEFAULT_CONFIG, get_config
from spotdl.utils.formatter import sanitize_string
from spotdl.utils.spotify import SpotifyClient


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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python playlist_name.py <spotify playlist url>", file=sys.stderr)
        return 2

    credentials = _credentials()
    SpotifyClient.init(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        no_cache=True,
    )

    metadata = Playlist.get_metadata(sys.argv[1])
    if isinstance(metadata, tuple):
        metadata = metadata[0]

    name = sanitize_string(metadata["name"]).strip()
    if not name:
        print("Playlist has no usable name.", file=sys.stderr)
        return 1

    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
