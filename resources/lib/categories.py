"""Every list the add-on offers, in the spirit of the Trakt widget menus.

Each category's fetch(api, page, size) returns (entries, has_more).
"""

from datetime import date, datetime, timedelta, timezone

from . import common, model
from .api import FloppyError

MOVIE, TV, MIXED = "movies", "tvshows", "videos"


def _list_ttl():
    return max(0, common.setting_int("cache_minutes", 5)) * 60


def _discover_ttl():
    return max(0, common.setting_int("discover_cache_minutes", 60)) * 60


def _has_more(payload):
    pagination = (payload or {}).get("pagination") or {}
    return bool(pagination.get("next"))


def _slice(entries, page, size):
    start = page * size
    return entries[start:start + size], len(entries) > start + size


# -- fetch builders ---------------------------------------------------------------

def media_list(media_type, next_up=False, **params):
    def fetch(api, page, size):
        payload = api.media(media_type, ttl=_list_ttl(), limit=size, offset=page * size, **params)
        results = (payload or {}).get("results") or []
        entries = [model.from_media(row, next_up=next_up) for row in results]
        return model.dedupe(entries), _has_more(payload)
    return fetch


def next_up():
    def fetch(api, page, size):
        order = common.setting_int("nextup_sort", 0)
        if order == 1:
            sort = {"sort": "next_episode_air_date", "direction": "asc"}
        elif order == 2:
            sort = {"sort": "title", "direction": "asc"}
        else:
            sort = {"sort": "end_date", "direction": "desc"}
        return media_list("tv", next_up=True, status=model.STATUS_IN_PROGRESS,
                          progress="not_caught_up", **sort)(api, page, size)
    return fetch


def resume(media_types):
    def fetch(api, page, size):
        payload = api.playback_progress(media_types, completed=False, limit=size,
                                        offset=page * size, ttl=_list_ttl())
        rows = (payload or {}).get("results") or []
        entries = []
        for row in rows:
            entry = model.from_progress(row)
            if not entry or not model.playable(entry):
                continue
            # Ignore accidental starts; a finished item is reported as completed.
            if entry["resume_pos"] < 60:
                continue
            total = entry.get("resume_total") or 0
            if total and entry["resume_pos"] >= total * 0.95:
                continue
            entries.append(entry)
        return model.dedupe(entries), _has_more(payload)
    return fetch


def discover_row(media_type, row_key):
    def fetch(api, page, size):
        payload = api.discover(media_type, ttl=_discover_ttl())
        rows = (payload or {}).get("rows") or []
        row = next((r for r in rows if r.get("key") == row_key), None)
        items = (row or {}).get("items") or []
        entries = [model.from_candidate(item, media_type) for item in items]
        entries = [e for e in model.dedupe(entries) if model.playable(e)]
        return _slice(entries, page, size)
    return fetch


def recommendations(media_type):
    def fetch(api, page, size):
        payload = api.recommendations(media_type, limit=size, offset=page * size,
                                      ttl=_discover_ttl())
        entries = [model.from_candidate(p, media_type) for p in (payload or {}).get("results") or []]
        entries = [e for e in model.dedupe(entries) if model.playable(e)]
        return entries, _has_more(payload)
    return fetch


def history(media_type):
    # Floppy's history filter calls episodes "tv" (it expands to seasons/episodes).
    history_type = "tv" if media_type == "episode" else media_type

    def fetch(api, page, size):
        payload = api.history([history_type], limit=size, offset=page * size, ttl=_list_ttl())
        entries = [model.from_history(row) for row in (payload or {}).get("results") or []]
        return model.dedupe(entries), _has_more(payload)
    return fetch


def calendar(kind, ahead):
    def fetch(api, page, size):
        today = date.today()
        if ahead:
            start, end = today, today + timedelta(days=common.setting_int("upcoming_days", 14))
        else:
            start, end = today - timedelta(days=common.setting_int("recent_days", 7)), today
        payload = api.calendar(start.isoformat(), end.isoformat(), ttl=_list_ttl())
        entries = [model.from_event(event) for event in (payload or {}).get("results") or []]
        entries = [e for e in entries if e and e["kind"] == kind and model.playable(e)]
        now_iso = common_now_iso()
        if ahead:
            entries = [e for e in entries if (e.get("sort_date") or "") >= now_iso[:10]]
        else:
            entries = [e for e in entries if (e.get("sort_date") or "") <= now_iso]
        entries.sort(key=lambda e: e.get("sort_date") or "", reverse=not ahead)
        for entry in entries:
            entry["label_prefix"] = _day_label(entry.get("sort_date"))
        return _slice(model.dedupe(entries), page, size)
    return fetch


def common_now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _day_label(value):
    if not value:
        return ""
    try:
        day = date.fromisoformat(value[:10])
    except ValueError:
        return ""
    today = date.today()
    if day == today:
        return "[Today]"
    if day == today + timedelta(days=1):
        return "[Tomorrow]"
    if day == today - timedelta(days=1):
        return "[Yesterday]"
    return "[{}]".format(day.strftime("%a %d %b"))


def merged(*fetchers):
    """Interleave several sources by recency (used for mixed Continue Watching)."""
    def fetch(api, page, size):
        pool = []
        for fetcher in fetchers:
            entries, _ = fetcher(api, 0, max(size * (page + 1), 50))
            pool.extend(entries)
        pool.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
        return _slice(model.dedupe(pool), page, size)
    return fetch

def _ts(value):
    """ISO date/datetime string -> UTC timestamp (0 when missing)."""
    if not value or not isinstance(value, str):
        return 0.0
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.fromisoformat(value[:10])
        except ValueError:
            return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def all_in_progress(next_up=False):
    """Films, series and anime in progress, ordered by your most recent play."""
    sources = (
        ("movie", {"status": model.STATUS_IN_PROGRESS}),
        ("tv", {"status": model.STATUS_IN_PROGRESS, "progress": "not_caught_up"}),
        ("anime", {"status": model.STATUS_IN_PROGRESS, "progress": "not_caught_up"}),
    )

    def fetch(api, page, size):
        ttl = _list_ttl()

        # Most recent play per title, from Floppy's history (newest first).
        last_play = {}
        try:
            history = api.history(["movie", "tv", "anime"], limit=200, ttl=ttl)
            for row in (history or {}).get("results") or []:
                item = row.get("item") or {}
                kind = "movie" if row.get("media_type") == "movie" else "tv"
                key = (kind, item.get("source"), str(item.get("media_id")))
                last_play.setdefault(key, _ts(row.get("played_at_local") or row.get("end_date")))
        except FloppyError as exc:
            common.log("History unavailable for ordering: {}".format(exc))

        pool = []
        for media_type, params in sources:
            try:
                payload = api.media(media_type, ttl=ttl, limit=200, sort="end_date",
                                    direction="desc", **params)
            except FloppyError as exc:
                common.log("Could not read {} in progress: {}".format(media_type, exc))
                continue
            for row in (payload or {}).get("results") or []:
                item = row.get("item") or {}
                # Seasons and episodes come from TMDb routes, so series need a TMDb source.
                if media_type != "movie" and item.get("source") != "tmdb":
                    continue
                entry = model.from_media(row, next_up=next_up and media_type != "movie")
                if not entry or not model.playable(entry):
                    continue
                kind = "movie" if media_type == "movie" else "tv"
                key = (kind, item.get("source"), str(item.get("media_id")))
                entry["_last"] = last_play.get(key) or max(
                    _ts(row.get(f)) for f in ("end_date", "progressed_at", "start_date", "created_at"))
                pool.append(entry)

        pool.sort(key=lambda e: e.get("_last") or 0, reverse=True)
        return _slice(model.dedupe(pool), page, size)

    return fetch

# -- the menu -----------------------------------------------------------------------
# key: (label, content, fetch, description, in_resume_list)

_RESUME_MOVIES = resume(["movie"])
_RESUME_EPISODES = resume(["episode"])

CATEGORIES = {
    # Mixed
    "continue_watching": ("Continue Watching", MIXED, merged(_RESUME_MOVIES, _RESUME_EPISODES),
                          "Movies and episodes you stopped part-way through.", True),
    # All videos (films, series, anime)
    "all_in_progress": ("In Progress", MIXED, all_in_progress(),
                        "Films, series and anime you're part-way through, last watched first.", False),
    "all_next_up": ("Next Up", MIXED, all_in_progress(next_up=True),
                    "The next episode of every series and anime, plus films in progress, "
                    "last watched first.", False),
    # Movies
    "movies_continue": ("Continue Watching", MOVIE, _RESUME_MOVIES,
                        "Movies you stopped part-way through.", True),
    "movies_top_picks": ("Top Picks For You", MOVIE, recommendations("movie"),
                         "New-to-you movies matched to your taste.", False),
    "movies_trending": ("Trending", MOVIE, discover_row("movie", "trending_right_now"),
                        "What everyone has been watching this week.", False),
    "movies_greats": ("All-Time Greats You Haven't Seen", MOVIE,
                      discover_row("movie", "all_time_greats_unseen"), "Classics still missing.", False),
    "movies_coming_soon": ("Coming Soon", MOVIE, discover_row("movie", "coming_soon"),
                           "Upcoming releases.", False),
    "movies_comfort": ("Comfort Rewatches", MOVIE, discover_row("movie", "comfort_rewatches"),
                       "Past favourites ready to revisit.", False),
    "movies_watchlist": ("Watchlist", MOVIE, media_list("movie", status=model.STATUS_PLANNING,
                                                        sort="date_added", direction="desc"),
                         "Movies you plan to watch.", False),
    "movies_watchlist_new": ("New On Your Watchlist", MOVIE,
                             media_list("movie", status=model.STATUS_PLANNING, release="released",
                                        release_date_within=60, release_date_within_unit="days",
                                        sort="release_date", direction="desc"),
                             "Watchlist movies released in the last 60 days.", False),
    "movies_watchlist_unreleased": ("Watchlist: Not Out Yet", MOVIE,
                                    media_list("movie", status=model.STATUS_PLANNING,
                                               release="not_released", sort="release_date",
                                               direction="asc"),
                                    "Watchlist movies that have not been released yet.", False),
    "movies_upcoming": ("Upcoming Releases", MOVIE, calendar("movie", ahead=True),
                        "Release dates for movies you track.", False),
    "movies_history": ("Recently Watched", MOVIE, history("movie"),
                       "Your latest movie plays.", False),
    "movies_completed": ("Watched", MOVIE, media_list("movie", status=model.STATUS_COMPLETED,
                                                      sort="end_date", direction="desc"),
                         "Every movie you have finished.", False),
    "movies_rated": ("Rated By You", MOVIE, media_list("movie", rating="rated", sort="score",
                                                       direction="desc"),
                     "Your highest-rated movies first.", False),
    "movies_recently_added": ("Recently Added", MOVIE, media_list("movie", sort="date_added",
                                                                  direction="desc"),
                              "Movies most recently added to Floppy.", False),
    "movies_collection": ("My Collection", MOVIE, media_list("movie", collection="collected",
                                                             sort="date_added", direction="desc"),
                          "Movies you own.", False),
    "movies_paused": ("Paused", MOVIE, media_list("movie", status=model.STATUS_PAUSED,
                                                  sort="updated", direction="desc"),
                      "Movies on hold.", False),
    "movies_dropped": ("Dropped", MOVIE, media_list("movie", status=model.STATUS_DROPPED,
                                                    sort="updated", direction="desc"),
                       "Movies you gave up on.", False),

    # TV
    "tv_next_up": ("Next Up", "episodes", next_up(),
                   "The next unwatched episode of every show you are watching.", False),
    "tv_continue": ("Continue Watching", "episodes", _RESUME_EPISODES,
                    "Episodes you stopped part-way through.", True),
    "tv_top_picks": ("Top Picks For You", TV, recommendations("tv"),
                     "Shows matched to your taste.", False),
    "tv_clear_out": ("Clear Out Next", TV, discover_row("tv", "clear_out_next"),
                     "Your in-progress shows ranked by what fits right now.", False),
    "tv_trending": ("Trending", TV, discover_row("tv", "trending_right_now"),
                    "What everyone has been watching this week.", False),
    "tv_greats": ("All-Time Greats You Haven't Seen", TV, discover_row("tv", "all_time_greats_unseen"),
                  "Classics still missing.", False),
    "tv_coming_soon": ("Coming Soon", TV, discover_row("tv", "coming_soon"),
                       "Upcoming shows.", False),
    "tv_comfort": ("Comfort Rewatches", TV, discover_row("tv", "comfort_rewatches"),
                   "Past favourites ready to revisit.", False),
    "tv_upcoming": ("Upcoming Episodes", "episodes", calendar("episode", ahead=True),
                    "Episodes airing soon for shows you track.", False),
    "tv_recently_aired": ("Recently Aired", "episodes", calendar("episode", ahead=False),
                          "Episodes that aired in the last few days.", False),
    "tv_watching": ("Watching", TV, media_list("tv", status=model.STATUS_IN_PROGRESS,
                                            sort="end_date", direction="desc"),
                "Shows in progress.", False),
    "tv_in_progress": ("In Progress: Not Caught Up", TV,
                    media_list("tv", status=model.STATUS_IN_PROGRESS, progress="not_caught_up",
                                sort="end_date", direction="desc"),
                    "Shows with unwatched episodes, most recently watched first.", False),
    "tv_watchlist": ("Watchlist", TV, media_list("tv", status=model.STATUS_PLANNING,
                                                 sort="date_added", direction="desc"),
                     "Shows you plan to watch.", False),
    "tv_history": ("Recently Watched", "episodes", history("episode"),
                   "Your latest episode plays.", False),
    "tv_completed": ("Watched", TV, media_list("tv", status=model.STATUS_COMPLETED,
                                               sort="end_date", direction="desc"),
                     "Shows you have finished.", False),
    "tv_rated": ("Rated By You", TV, media_list("tv", rating="rated", sort="score", direction="desc"),
                 "Your highest-rated shows first.", False),
    "tv_recently_added": ("Recently Added", TV, media_list("tv", sort="date_added", direction="desc"),
                          "Shows most recently added to Floppy.", False),
    "tv_collection": ("My Collection", TV, media_list("tv", collection="collected",
                                                      sort="date_added", direction="desc"),
                      "Shows you own.", False),
    "tv_paused": ("Paused", TV, media_list("tv", status=model.STATUS_PAUSED, sort="updated",
                                           direction="desc"), "Shows on hold.", False),
    "tv_dropped": ("Dropped", TV, media_list("tv", status=model.STATUS_DROPPED, sort="updated",
                                             direction="desc"), "Shows you gave up on.", False),
}

MOVIE_MENU = [
    "movies_continue", "movies_top_picks", "movies_trending", "movies_greats",
    "movies_coming_soon", "movies_comfort", "movies_watchlist", "movies_watchlist_new",
    "movies_watchlist_unreleased", "movies_upcoming", "movies_history", "movies_completed",
    "movies_rated", "movies_recently_added", "movies_collection", "movies_paused", "movies_dropped",
]

TV_MENU = [
    "tv_next_up", "tv_continue", "tv_top_picks", "tv_clear_out", "tv_trending", "tv_greats",
    "tv_coming_soon", "tv_comfort", "tv_upcoming", "tv_recently_aired", "tv_watching", "tv_in_progress",
    "tv_watchlist", "tv_history", "tv_completed", "tv_rated", "tv_recently_added",
    "tv_collection", "tv_paused", "tv_dropped",
]

ALL_MENU = ["all_in_progress", "all_next_up", "continue_watching"]
