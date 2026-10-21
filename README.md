# Floppy for Kodi (plugin.video.floppy)

A Kodi add-on for your self-hosted [Floppy](https://github.com/dannyvfilms/Floppy) tracker. It turns your Floppy library into lists and widgets, browses shows with Floppy's own watched state, searches through Floppy, and can send your watch history and resume positions straight to Floppy, with no Trakt and no separate scrobbler.

Works standalone or as a widget source for any skin that supports custom widgets. Playback goes through TMDb Helper's players, or any player add-on you point it at.

Needs Kodi 20 (Nexus) or newer and a Floppy instance with its API token. Built against Floppy's API (October 2026 `latest`).

[Download Latest Release](https://github.com/haywirephoenix/plugin.video.floppy/releases/latest/download/plugin.video.floppy.zip)

## Features

- **Lists for everything**: Continue Watching, Next Up, In Progress, watchlists, history, calendar, Discover rows, your Floppy lists and your Floppy home rows. Movies, TV and anime are available separately or combined.
- **Floppy watched state everywhere**: seasons and episodes show Floppy's watch progress, not Trakt's or Kodi's library.
- **Anime-aware**: shows tracked in Floppy's Anime library are read and marked in the right place.
- **Search through Floppy**: movies, shows, collections and people, with the same context menu as the widgets.
- **Scrobbling built in**: plays, resume positions and Floppy's Now Playing card, sent with your API token.
- **Context menu actions**: mark watched or unwatched, mark a season or a whole show watched, watchlist, remove from Floppy, and remove from Continue Watching.

## Install

1. Kodi: Settings → System → Add-ons → turn on **Unknown sources**.
2. Add-ons → Install from zip file → `plugin.video.floppy-x.x.x.zip`.
3. Open the add-on's settings:
   - **Floppy address**: e.g. `http://localhost:8000` (the default; no `/api`).
   - **API token**: Floppy → Settings → Integrations → API Token.
   - **Test connection** to check both.
4. Optional, Artwork → **TMDb API key**: adds fanart, landscape art and clear logos, and enables collection and people search. Floppy's own `TMDB_API` key works. Without it you get Floppy's posters only.
5. Optional, Playback → **Send watch history to Floppy**: see [Scrobbling](#scrobbling).

## Browsing

The add-on's main menu:

| Menu | What's in it |
|---|---|
| Continue Watching | Movies and episodes you stopped part-way through |
| Next Up | The next episode of every show you're watching |
| All Videos | Films, series and anime combined: In Progress, Next Up, Continue Watching |
| Movies / TV Shows | Every movie and TV list (see the widget tables below) |
| Discover | Floppy's Discover rows for movies, TV and anime, including the extra "More rows" |
| Search | Movies and shows through Floppy |
| My Lists | Your Floppy lists |
| Floppy Home Rows | The rows from your Floppy home page |
| Tools | Refresh widgets, show widget paths, test connection, clear cache, settings |

Selecting a **show** opens its seasons and episodes, built from Floppy, with Floppy's watched ticks, resume bars and air dates. Selecting an **episode or movie** plays it. You can change what a show does in Playback → "When a TV show is selected":
- open its seasons in the Floppy view (default);
- play its next episode;
- open its seasons in TMDb Helper.

## Widgets

Customise your skin's home menu → choose a widget → Add-ons/Video add-ons → Floppy → browse to the list and pick it. Or paste a path from below. Tools → **Show widget paths** lists them all inside Kodi.

To make a widget refresh by itself after you watch something or use a Floppy context-menu action, add this to the end of its path:

```
&reload=$INFO[Window(Home).Property(floppy.widget_reload)]
```

Widgets never show a "Next page" item. Add `&limit=30` to a path to change how many items a widget shows.

**All Videos** (films, series and anime together, last watched first)

| List | Path |
|---|---|
| In Progress | `plugin://plugin.video.floppy/?action=list&cat=all_in_progress` |
| Next Up | `plugin://plugin.video.floppy/?action=list&cat=all_next_up` |
| Continue Watching | `plugin://plugin.video.floppy/?action=list&cat=continue_watching` |

**Movies**

| List | Path |
|---|---|
| Continue Watching | `plugin://plugin.video.floppy/?action=list&cat=movies_continue` |
| Top Picks For You | `plugin://plugin.video.floppy/?action=list&cat=movies_top_picks` |
| Trending | `plugin://plugin.video.floppy/?action=list&cat=movies_trending` |
| All-Time Greats You Haven't Seen | `plugin://plugin.video.floppy/?action=list&cat=movies_greats` |
| Coming Soon | `plugin://plugin.video.floppy/?action=list&cat=movies_coming_soon` |
| Comfort Rewatches | `plugin://plugin.video.floppy/?action=list&cat=movies_comfort` |
| Watchlist | `plugin://plugin.video.floppy/?action=list&cat=movies_watchlist` |
| New On Your Watchlist | `plugin://plugin.video.floppy/?action=list&cat=movies_watchlist_new` |
| Watchlist: Not Out Yet | `plugin://plugin.video.floppy/?action=list&cat=movies_watchlist_unreleased` |
| Upcoming Releases | `plugin://plugin.video.floppy/?action=list&cat=movies_upcoming` |
| Recently Watched | `plugin://plugin.video.floppy/?action=list&cat=movies_history` |
| Watched | `plugin://plugin.video.floppy/?action=list&cat=movies_completed` |
| Rated By You | `plugin://plugin.video.floppy/?action=list&cat=movies_rated` |
| Recently Added | `plugin://plugin.video.floppy/?action=list&cat=movies_recently_added` |
| My Collection | `plugin://plugin.video.floppy/?action=list&cat=movies_collection` |
| Paused | `plugin://plugin.video.floppy/?action=list&cat=movies_paused` |
| Dropped | `plugin://plugin.video.floppy/?action=list&cat=movies_dropped` |

**TV**

| List | Path |
|---|---|
| Next Up | `plugin://plugin.video.floppy/?action=list&cat=tv_next_up` |
| Continue Watching | `plugin://plugin.video.floppy/?action=list&cat=tv_continue` |
| Top Picks For You | `plugin://plugin.video.floppy/?action=list&cat=tv_top_picks` |
| Clear Out Next | `plugin://plugin.video.floppy/?action=list&cat=tv_clear_out` |
| Trending | `plugin://plugin.video.floppy/?action=list&cat=tv_trending` |
| All-Time Greats You Haven't Seen | `plugin://plugin.video.floppy/?action=list&cat=tv_greats` |
| Coming Soon | `plugin://plugin.video.floppy/?action=list&cat=tv_coming_soon` |
| Comfort Rewatches | `plugin://plugin.video.floppy/?action=list&cat=tv_comfort` |
| Upcoming Episodes | `plugin://plugin.video.floppy/?action=list&cat=tv_upcoming` |
| Recently Aired | `plugin://plugin.video.floppy/?action=list&cat=tv_recently_aired` |
| Watching | `plugin://plugin.video.floppy/?action=list&cat=tv_watching` |
| In Progress: Not Caught Up | `plugin://plugin.video.floppy/?action=list&cat=tv_in_progress` |
| Watchlist | `plugin://plugin.video.floppy/?action=list&cat=tv_watchlist` |
| Recently Watched | `plugin://plugin.video.floppy/?action=list&cat=tv_history` |
| Watched | `plugin://plugin.video.floppy/?action=list&cat=tv_completed` |
| Rated By You | `plugin://plugin.video.floppy/?action=list&cat=tv_rated` |
| Recently Added | `plugin://plugin.video.floppy/?action=list&cat=tv_recently_added` |
| My Collection | `plugin://plugin.video.floppy/?action=list&cat=tv_collection` |
| Paused | `plugin://plugin.video.floppy/?action=list&cat=tv_paused` |
| Dropped | `plugin://plugin.video.floppy/?action=list&cat=tv_dropped` |

**Discover rows**

```
plugin://plugin.video.floppy/?action=discover_row&media_type=movie&key=top_picks_for_you
```

`media_type` is `movie`, `tv` or `anime`. The available keys are:
- `top_picks_for_you`
- `trending_right_now`
- `all_time_greats_unseen`
- `coming_soon`
- `comfort_rewatches`
- `clear_out_next` (TV and anime only)

Rows from Discover's "More rows" need `&show_more=1` added to the path.

Your Floppy lists and Floppy home rows are under **My Lists** and **Floppy Home Rows**; browse to one to use it as a widget.

## Search

Point your skin's search (or use **Search** in the add-on) at:

| Search | Path (the skin appends the search term) |
|---|---|
| Movies and shows | `plugin://plugin.video.floppy/?action=search&media_type=both&widget=1&query=` |
| Movies | `plugin://plugin.video.floppy/?action=search&media_type=movie&widget=1&query=` |
| Shows | `plugin://plugin.video.floppy/?action=search&media_type=tv&widget=1&query=` |
| Collections | `plugin://plugin.video.floppy/?action=search&media_type=collection&widget=1&query=` |
| People | `plugin://plugin.video.floppy/?action=search&media_type=person&widget=1&query=` |

Keep `query=` last. Movie and show searches go through Floppy's search API. Collection and people searches use TMDb directly and need the TMDb API key. Results you already track in Floppy get the matching context menu, for example "Remove from Floppy" instead of "Add to watchlist".

## Scrobbling

Turn on Playback → **Scrobble: Send watch history to Floppy** and the add-on's background service reports playback through Floppy's scrobble API:

- **Start, pause and resume** update Floppy's Now Playing card.
- **Stopping past the watched threshold** logs the play in your Floppy history.
- **Your position** is saved on pause and stop, and every couple of minutes while playing, so Continue Watching always knows where you are.

**If you used the HTTP Scrobbler add-on with Floppy, disable it (or remove its Floppy URL) before turning this on, or every play is logged twice.**

With scrobbling off, the add-on still saves resume positions (Playback → "Save resume positions to Floppy") but leaves watch history to whatever else you use.

Settings:
- **Count as watched after**: how far through a film or episode counts as watched (default 80%). Playing to the very end always counts.
- **Resume from Floppy positions**: Ask (default), Always or Off. If your player add-on already resumed, the add-on leaves it alone.

Playback started from this add-on is identified exactly by its TMDb id. Playback started elsewhere in Kodi is identified from the player's info (IMDb/TVDb ids, with a title match against your Floppy shows).

## Playback

- **TMDb Helper** (default): movies and episodes use `plugin://plugin.video.themoviedb.helper/?info=play...`, so your existing TMDb Helper players are used. TMDb Helper is only used to play; lists, watched state and actions all come from Floppy.
- **Custom player URL**: templates with `{tmdb} {imdb} {tvdb} {season} {episode} {title} {year}`.

## Context menu

| On | Actions |
|---|---|
| Movies | Mark as watched / unwatched, add to / remove from watchlist, remove from Floppy, remove from Continue Watching |
| Shows | Mark show watched, add to / remove from watchlist, remove from Floppy |
| Seasons | Mark season watched |
| Episodes | Mark as watched / unwatched, remove from Continue Watching, go to show |
| Everything | Refresh widgets |

**Mark show watched** and **Mark season watched** only mark aired episodes you haven't watched yet, and skip specials. They show progress as they go and can be cancelled. **Remove from Floppy** deletes the title's status, rating and history in Floppy, after asking you first. It is offered on watchlist items too, for titles you no longer want tracked at all; **Remove from watchlist** only removes the Planning entry and keeps any earlier watch history.

## Anime

Floppy keeps anime in its own library bucket. The add-on detects shows tracked there and reads and writes their seasons, episodes and watched marks in that bucket. Anime tracked from MyAnimeList (with no TMDb id) can't be played or browsed by season and is left out of lists.

## Skin integration

Items carry properties a skin's info dialog can use, so its buttons work for Floppy items as well as library ones:

| Property | On | Use |
|---|---|---|
| `floppy.play_path` | Movies, episodes | Play / Resume button: `RunPlugin($INFO[ListItem.Property(floppy.play_path)])`. Add `&noresume=1` for "play from beginning". |
| `floppy.seasons_path` | Shows | Episodes button: `ActivateWindow(Videos,"$INFO[ListItem.Property(floppy.seasons_path)]",return)` |
| `floppy.next_play_path` | Shows with a next episode | Play next episode button: `RunPlugin($INFO[ListItem.Property(floppy.next_play_path)])` |
| `floppy.next_label` | Shows with a next episode | The next episode's code, e.g. `S01E04` |
| `floppy.episodes_left` | Tracked shows | Released episodes still to watch |
| `floppy.air_datetime` | Calendar items | Air or release date and time |
| `tvshow.tmdb_id` | Episodes | The show's TMDb id |

Add a condition such as `!String.IsEmpty(ListItem.Property(floppy.play_path))` to the skin's own button actions so they don't also fire for Floppy items. Season items also set Kodi's standard `TotalEpisodes`, `WatchedEpisodes` and `UnWatchedEpisodes` properties from Floppy.

## What the lists use

- **Continue Watching**: Floppy's saved resume positions (`/playback/progress`), written by this add-on's service and by Plex/Jellyfin/Emby webhooks if you use them.
- **Next Up / In Progress**: in-progress shows that aren't caught up, with Floppy's next released, unwatched episode. The All Videos versions rank films, series and anime together by your most recent activity (finished plays and saved positions).
- **Discover rows**: Floppy's Discover. They're empty if Discover is turned off in Floppy, and the Trakt-sourced rows need Floppy to reach Trakt.
- **Upcoming / Recently Aired**: Floppy's calendar for things you track.
- **Everything else**: your Floppy library with status and sort filters.

## Troubleshooting

Turn on Settings → Advanced → **Debug logging**, then look for `plugin.video.floppy` in `kodi.log`.

| What you see | What to check |
|---|---|
| A list or widget is empty | Test connection; for Discover rows, check Discover is on in Floppy. |
| A show's episodes all look unwatched | It may be tracked in Floppy's Anime library under a MyAnimeList id, which the add-on can't browse. |
| A play isn't logged | With debug logging on, look for `Scrobbled stop` in the log. Plays need a TMDb, IMDb or TVDb id. |
| Plays are logged twice | Another scrobbler (e.g. the HTTP Scrobbler) is also sending to Floppy. |
| Stale lists | Tools → Refresh widgets, or lower Advanced → "Keep lists for". |
