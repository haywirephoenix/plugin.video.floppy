# Floppy for Kodi (plugin.video.floppy)

Widgets and lists from your self-hosted [Floppy](https://github.com/dannyvfilms/Floppy) tracker, built for skins like Bingie. Items play through TMDb Helper (or any player add-on you point it at), and the add-on saves where you stopped back to Floppy so Continue Watching works.

Needs Kodi 20 (Nexus) or newer. Tested against Floppy's own API code (October 2026 `latest`).

## Install

1. Kodi: Settings → System → Add-ons → turn on **Unknown sources**.
2. Add-ons → Install from zip file → `plugin.video.floppy-1.0.0.zip`.
3. Open the add-on's settings:
   - **Floppy address**: e.g. `http://192.168.1.10:8000` (no `/api`).
   - **API token**: Floppy → Settings → Integrations → API Token.
   - **Test connection** to check both.
4. Optional, Artwork → **TMDb API key**: adds fanart, landscape art and clear logos (Bingie uses these heavily). Floppy's own `TMDB_API` key works. Without it you get Floppy's posters only.

Keep your HTTP Scrobbler add-on: it still writes watch history. This add-on only reads lists and saves resume positions, which Floppy stores separately, so nothing is logged twice.

## Adding widgets in Bingie

Customise the home menu → choose a widget → Add-ons/Video add-ons → Floppy → browse to the list and pick it. Or paste a path from below.

To make a widget refresh by itself after you watch something or use a Floppy context-menu action, add this to the end of its path:

```
&reload=$INFO[Window(Home).Property(floppy.widget_reload)]
```

Widgets never show a "Next page" item. Add `&limit=30` to a path to change how many items a widget shows.

**Mixed**

| List | Path |
|---|---|
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
| Watchlist | `plugin://plugin.video.floppy/?action=list&cat=tv_watchlist` |
| Recently Watched | `plugin://plugin.video.floppy/?action=list&cat=tv_history` |
| Watched | `plugin://plugin.video.floppy/?action=list&cat=tv_completed` |
| Rated By You | `plugin://plugin.video.floppy/?action=list&cat=tv_rated` |
| Recently Added | `plugin://plugin.video.floppy/?action=list&cat=tv_recently_added` |
| My Collection | `plugin://plugin.video.floppy/?action=list&cat=tv_collection` |
| Paused | `plugin://plugin.video.floppy/?action=list&cat=tv_paused` |
| Dropped | `plugin://plugin.video.floppy/?action=list&cat=tv_dropped` |

Your Floppy lists and the rows from your Floppy home page are under **My Lists** and **Floppy Home Rows** in the add-on; browse to them to use one as a widget.

## What the lists use

- **Continue Watching**: Floppy's saved resume positions (`/playback/progress`). These come from this add-on's service (and from Plex/Jellyfin/Emby webhooks if you use them). Floppy's Kodi webhook does not store positions, so this list fills up once you watch through Kodi with the add-on installed.
- **Next Up**: shows you are watching that are not caught up, with Floppy's next released, unwatched episode.
- **Top Picks / Trending / All-Time Greats / Coming Soon / Comfort Rewatches / Clear Out Next**: Floppy's Discover rows. They are empty if Discover is turned off in Floppy, and the Trakt-sourced rows need Floppy to reach Trakt.
- **Upcoming / Recently Aired**: Floppy's calendar for things you track.
- Everything else: your Floppy library with status/sort filters.

## Playback

- **TMDb Helper** (default): movies and episodes use `plugin://plugin.video.themoviedb.helper/?info=play...`, so your existing TMDb Helper players are used. Selecting a TV show opens its seasons in TMDb Helper, or plays its next episode if you change "When a TV show is selected".
- **Custom player URL**: templates with `{tmdb} {imdb} {tvdb} {season} {episode} {title} {year}`.
- **Resume from Floppy positions**: Ask (default), Always or Off. If your player add-on already resumed, the add-on leaves it alone.

## Context menu

Mark as watched, add to / remove from watchlist, remove from Continue Watching, go to show, refresh widgets.

## Troubleshooting

Turn on Settings → Advanced → Debug logging, then look for `plugin.video.floppy` in `kodi.log`. Tools → Show widget paths lists every path.
