# The spotdl matching fixes

`spotdl_patched.py` is a thin wrapper around spotdl's CLI. It forwards every
argument untouched and monkey-patches three things at runtime, so `spotdl`
itself is never edited and `pip install -U spotdl` will not wipe the changes:

```powershell
python spotdl_patched.py sync "My Playlist.spotdl" --output "..."
```

All three fixes were found while chasing real
`LookupError: No results found for song` failures in a 117-track library. Each
is described below with the evidence that motivated it.

The guiding constraint throughout: **no matching threshold was loosened.**
Every fix either feeds spotdl better data or widens the candidate pool, and
then lets spotdl's own scoring decide. That matters because loosening the bar
enough to catch a marginal track also admits karaoke covers and live
recordings — two karaoke uploads showed up in one of the searches below.

---

## Fix 1 — secondary artists were compared by position

**Symptom.** `Afro 23, Nesty - Lo Que Se Comenta` failed, even though the
correct video was the *first* result returned.

**Cause.** `calc_artists_match` in `spotdl/utils/matching.py` sorts the song's
artists and the result's artists, drops index 0 from each as "the main artist",
then `zip_longest`s the remainder. That assumes index 0 is the same artist on
both sides. YouTube often credits a composer or producer first:

| | list |
| --- | --- |
| Spotify artists | `['nesty', 'afro-23']` |
| YouTube artists | `['yulier-bonet', 'nesty', 'afro-23']` |

After dropping index 0, `['afro-23']` is compared against
`['nesty', 'afro-23']`, pairing `afro-23` with `nesty` for a ratio of 0.

That zero halves the artist score to 50, and `order_results` discards anything
under 70 — despite a name match of 100 and a duration within 2 seconds.

**Fix.** Score each secondary artist against the *best* matching result artist
instead of the positionally-corresponding one, which is immune to extra credits
and to ordering. A token-boundary containment check also handles channel names
that concatenate every credit into one field (`afro-23-nesty`).

**A trap worth knowing about.** Patching `calc_artists_match` directly causes a
regression. Raising the raw score past 50 makes `artists_match_fixup1` return
early and skip a boost it would otherwise apply, so the *final* score can end
up **lower**:

| candidate | stock | naive patch |
| --- | --- | --- |
| `Ivan Venot & Tony Velardi - ME LA DAS` | **100.0** | 87.5 |
| `ME LA DAS - IVAN VENOT FT TONY VELARDI` (reupload) | 97.8 | **97.8** ← wins |

So the patch is applied at the `order_results` level instead: score every
result twice, once with stock spotdl and once with the improved matcher, and
keep the higher score per result. Stock scores can never decrease, so existing
matches are preserved by construction, and only results stock spotdl discarded
entirely can come back.

**Verified.** All 30 multi-artist tracks in the test library: 30 unchanged,
0 altered.

---

## Fix 2 — a bad YouTube Music client stays bad

**Symptom.** The same track resolved on most runs and failed on others.

**Cause.** YouTube Music does not always return the same result set. For the
track above, roughly **one freshly created client in six** never surfaced the
video at all — 36 unrelated results instead of 39 — and a client that landed in
that state stayed in it for its whole session:

```
videos=39 target=True     videos=39 target=True
videos=39 target=True     videos=36 target=False
videos=39 target=True     videos=39 target=True
```

spotdl does retry with a new client, but only when a search comes back
*completely empty*. Thirty-six wrong results look like a successful search, so
the retry never fires.

**Fix.** When a search returns nothing usable, recreate the `YTMusic` client
and retry (3 attempts). This only runs on the path that was about to fail, so
it cannot change a search that already succeeds.

**Verified.** 8 of 8 fresh processes resolved the track afterwards, up from
roughly 5 in 6.

---

## Fix 3 — results neither filtered search can reach

**Symptom.** `Dj Ricky Campanelli - Rumba Callejera` failed. The real
catalogue track existed — exact title, exact artist as the channel, duration
matching Spotify to the second.

**Cause, part one.** spotdl only ever runs two searches,
`filter="songs"` and `filter="videos"` (`YouTubeMusic.GET_RESULTS_OPTS`). This
track appears in neither:

| filter | results | target present |
| --- | --- | --- |
| `songs` | 0 | no |
| `videos` | 40 | no |
| **none** | 14 | **yes** |

**Cause, part two.** Even an unfiltered search would not have helped, because
YouTube Music returns it as a "Top result" card with `resultType: "album"` and
**`artists: null`** — and `get_results` drops every result whose artists field
is empty.

**Fix.** As a last resort, run an unfiltered search and, for entries that carry
a `videoId` but no usable artist, fill the metadata in from `get_song(videoId)`
before scoring. The candidates then go through spotdl's ordinary scoring and
thresholds untouched. The rescued track scored 100 on name, 100 on artist and
100 on duration; anything that cannot clear the normal bar is still rejected.

At most 4 extra `get_song` calls are made, and only on a search that was about
to fail outright.

**Verified.** Beyond the original track, a regression run over 12 multi-artist
tracks rescued 4 more and changed 0 existing matches.

---

## Tuning

Constants at the top of `spotdl_patched.py`:

| Name | Default | Meaning |
| --- | --- | --- |
| `SEARCH_RETRIES` | 3 | Fresh-client retries after an empty search |
| `UNFILTERED_LIMIT` | 20 | Results requested by the unfiltered fallback |
| `MAX_ENRICH_CALLS` | 4 | Cap on `get_song` metadata lookups per search |

## What is still unfixed

Tracks with many credited artists. Spotify listing five artists produces a
130+ character query that matches nothing, and none of the three fixes
address query length. Truncating the query to the primary artist plus title
would be the next thing to try.
