"""
Thin wrapper around the spotdl CLI that fixes secondary-artist matching.

The problem
-----------
spotdl's `calc_artists_match` (spotdl/utils/matching.py) compares the
non-main artists of a Spotify track against the non-main artists of a
YouTube result *by position*: it sorts both lists, drops index 0 from
each, then zips what is left together.

That assumes index 0 of both lists is the same main artist. YouTube
frequently credits a composer/producer first, so the result list carries
one extra leading name and every later pair is shifted by one. The lists
no longer line up, the score collapses to 0, that drags the overall
artist score down to 50, and the `artists_match < 70` filter in
`order_results` discards the result.

Example: "Afro 23, Nesty - Lo Que Se Comenta" is credited on YouTube as
['Yulier Bonet', 'Nesty', 'Afro 23']. Name match 100, main artist match
100, duration off by 2s -- and stock spotdl still drops it, leaving
nothing to download and raising "No results found for song".

The fix
-------
Score each secondary song artist against the *best* matching result
artist rather than the positionally-corresponding one. That is immune to
extra credits and to ordering differences.

Applying that in isolation is not safe, though. `order_results` feeds the
artist score through `artists_match_fixup1/2/3`, and those bail out early
once the score is above a threshold. Raising the raw score can therefore
*skip* a fixup that would have raised it even further, lowering the final
score and changing which result wins.

So the patch is applied at the `order_results` level instead: score every
result twice -- once with stock spotdl, once with the improved matcher --
and keep the higher score for each result. Stock scores are never lowered
and stock ordering is preserved; the only change is that results stock
spotdl threw away entirely can now come back with a score.

A second, unrelated flakiness
-----------------------------
YouTube Music does not always return the same result set. For the track
above, roughly one freshly-created client in six never surfaces the
video at all -- it returns 36 unrelated results instead of 39 -- and a
client that lands in that state stays in it for its whole session.

spotdl already retries with a new client, but only when a search comes
back *completely* empty; 36 wrong results look like a successful search,
so that retry never fires and the download fails anyway.

So `search` is wrapped too: if it comes back with nothing, the YTMusic
client is recreated and the search retried. That only ever runs on the
path that was about to fail with "No results found for song", so it
cannot change any search that already succeeds.

A third gap: results the filtered searches never see
----------------------------------------------------
spotdl only ever runs two YouTube Music searches, `filter="songs"` and
`filter="videos"` (`YouTubeMusic.GET_RESULTS_OPTS`). Some catalogue
tracks appear under neither. "Dj Ricky Campanelli - Rumba Callejera" is
one: `songs` returns nothing at all, `videos` returns 40 results that
exclude it, and the real track (an ATV catalogue entry, exact title,
exact artist, exact 254s duration) only shows up in an *unfiltered*
search.

Even an unfiltered search would not rescue it, though, because YouTube
Music returns it as a "Top result" card with `artists: null`, and
`get_results` drops every result whose artists field is empty.

So the last-ditch fallback runs an unfiltered search and, for entries
that carry a videoId but no usable artist, fills the metadata in from
`get_song(videoId)` before scoring them. The candidates are then put
through spotdl's ordinary scoring and thresholds untouched -- no
threshold is loosened anywhere. In the example above the rescued
candidate scores 100 on name, artist and duration; anything that cannot
clear the normal bar is still rejected.

Usage: python spotdl_patched.py <normal spotdl arguments>
"""

import logging
import sys
from typing import Dict, List, Optional

from spotdl.types.result import Result
from spotdl.types.song import Song
from spotdl.utils.formatter import ratio, slugify

import spotdl.providers.audio.base as audio_base
import spotdl.utils.matching as matching
from spotdl.providers.audio import YouTubeMusic
from spotdl.types.result import Result
from spotdl.utils.formatter import create_search_query, create_song_title, parse_duration

logger = logging.getLogger(__name__)

_stock_calc_artists_match = matching.calc_artists_match
_stock_order_results = matching.order_results
_stock_ytm_search = YouTubeMusic.search

# How many times to retry a failed search with a brand new YTMusic client.
SEARCH_RETRIES = 3

# Unfiltered fallback search: how many results to ask for, and how many
# of them may cost an extra get_song call to fill in missing metadata.
UNFILTERED_LIMIT = 20
MAX_ENRICH_CALLS = 4


def _best_artist_score(artist: str, result_artists: List[str]) -> float:
    """
    Best score for one song artist against any of the result's artists.

    Uses fuzzy ratio, plus a token-boundary containment check so that
    single-field channel names that concatenate every credit (e.g.
    "afro-23-nesty") still count as a match for "nesty".
    """

    best = 0.0
    for candidate in result_artists:
        best = max(best, ratio(artist, candidate))
        if artist and f"-{artist}-" in f"-{candidate}-":
            return 100.0

    return best


def calc_artists_match(song: Song, result: Result) -> float:
    """
    Order- and length-insensitive replacement for spotdl's version.
    """

    if len(song.artists) == 1 or not result.artists:
        return 0.0

    song_artists = [slugify(artist) for artist in song.artists]
    result_artists = [slugify(artist) for artist in result.artists]

    # The main artist is scored separately by calc_main_artist_match.
    secondary = song_artists[1:]
    if not secondary:
        return _stock_calc_artists_match(song, result)

    improved = sum(
        _best_artist_score(artist, result_artists) for artist in secondary
    ) / len(secondary)

    return max(_stock_calc_artists_match(song, result), improved)


def order_results(
    results: List[Result],
    song: Song,
    search_query: Optional[str] = None,
) -> Dict[Result, float]:
    """
    Run spotdl's scorer twice and keep the better score per result.

    Pass 1 is stock spotdl, pass 2 uses the improved artist matcher.
    Merging by max means no result can score lower than it does today,
    so existing matches are unaffected; results that stock spotdl
    dropped can now survive.
    """

    stock_scores = _stock_order_results(results, song, search_query)

    matching.calc_artists_match = calc_artists_match
    try:
        improved_scores = _stock_order_results(results, song, search_query)
    finally:
        matching.calc_artists_match = _stock_calc_artists_match

    merged = dict(stock_scores)
    for result, score in improved_scores.items():
        if score > merged.get(result, 0.0):
            merged[result] = score

    return merged


def ytm_search(self, song: Song, only_verified: bool = False) -> Optional[str]:
    """
    Retry a failed YouTube Music search with a fresh client.

    Only runs when the stock search found nothing at all, i.e. when
    spotdl was about to give up on the song entirely.
    """

    result = _stock_ytm_search(self, song, only_verified)
    if result is not None:
        return result

    for attempt in range(SEARCH_RETRIES):
        logger.debug(
            "Nothing found for %s, retrying with a new YTMusic client (%s/%s)",
            song.display_name,
            attempt + 1,
            SEARCH_RETRIES,
        )

        try:
            self.client = self._create_client()
        except Exception:  # pylint: disable=broad-except
            logger.debug("Could not recreate the YTMusic client", exc_info=True)
            break

        result = _stock_ytm_search(self, song, only_verified)
        if result is not None:
            return result

    # Nothing under filter="songs" or filter="videos" -- try unfiltered.
    return unfiltered_fallback(self, song)


def _search_query_for(provider, song: Song) -> str:
    """
    Reproduce the query string `AudioProvider.search` builds.
    """

    if provider.search_query:
        return create_search_query(song, provider.search_query, False, None, True)

    return create_song_title(song.name, song.artists).lower()


def _unfiltered_results(provider, song: Song, query: str) -> List[Result]:
    """
    Run an unfiltered YouTube Music search and build scorable results.

    Entries that carry a videoId but no usable artist -- notably the
    "Top result" card, which is often the actual catalogue track -- get
    their metadata filled in from `get_song`.
    """

    try:
        raw = provider.client.search(query, ignore_spelling=True, limit=UNFILTERED_LIMIT)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Unfiltered search failed for %s", query, exc_info=True)
        return []

    results: List[Result] = []
    enriched = 0

    for entry in raw:
        video_id = entry.get("videoId")
        if not video_id:
            continue

        artists = [
            artist["name"]
            for artist in (entry.get("artists") or [])
            if artist.get("name")
        ]
        name = entry.get("title")
        duration = parse_duration(entry.get("duration"))
        is_song = entry.get("resultType") == "song"

        if not artists or not name:
            if enriched >= MAX_ENRICH_CALLS:
                continue

            enriched += 1
            try:
                details = provider.client.get_song(video_id)["videoDetails"]
            except Exception:  # pylint: disable=broad-except
                logger.debug("Could not read details for %s", video_id, exc_info=True)
                continue

            name = details.get("title") or name
            author = details.get("author")
            if not name or not author:
                continue

            artists = [author]
            duration = float(details.get("lengthSeconds") or duration or 0)

        results.append(
            Result(
                source=provider.name,
                url=(
                    f'https://{"music" if is_song else "www"}'
                    f".youtube.com/watch?v={video_id}"
                ),
                verified=is_song,
                name=name,
                result_id=video_id,
                author=artists[0],
                artists=tuple(artists),
                duration=duration,
                isrc_search=False,
                search_query=query,
                explicit=entry.get("isExplicit"),
                album=(entry.get("album") or {}).get("name") or None,
            )
        )

    return results


def unfiltered_fallback(provider, song: Song) -> Optional[str]:
    """
    Last-ditch search for songs the two filtered passes never surface.

    Scoring and thresholds are spotdl's own -- this only widens the pool
    of candidates that get scored, it never lowers the bar.
    """

    query = _search_query_for(provider, song)
    results = _unfiltered_results(provider, song, query)
    if not results:
        return None

    scored = order_results(results, song, provider.search_query)
    if not scored:
        return None

    try:
        best_result, best_score = provider.get_best_result(scored)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Could not rank fallback results", exc_info=True)
        best_result, best_score = max(scored.items(), key=lambda item: item[1])

    logger.debug(
        "Unfiltered fallback picked %s with score %s for %s",
        best_result.url,
        best_score,
        song.display_name,
    )

    return best_result.url


def apply_patches() -> None:
    """
    Install the patched scorer and the search retry.

    `spotdl.providers.audio.base` does `from spotdl.utils.matching import
    order_results`, so it holds its own reference and has to be rebound
    separately from the one in `spotdl.utils.matching`.
    """

    matching.order_results = order_results
    audio_base.order_results = order_results
    YouTubeMusic.search = ytm_search


def main() -> None:
    apply_patches()

    from spotdl import console_entry_point

    console_entry_point()


if __name__ == "__main__":
    sys.exit(main())
