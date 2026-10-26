"""Build Kodi ListItems from entries and decide where each item points."""

from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcgui

from . import common, model, tmdb

PLAYBACK_NONE, PLAYBACK_PLUGIN, PLAYBACK_CUSTOM = 0, 1, 2


# -- where things go ----------------------------------------------------------

def seasons_url(tmdb_id, title="", lmt=None):
    return common.plugin_url(action="seasons", tmdb=tmdb_id, show=title, lmt=lmt)


def episodes_url(tmdb_id, season, title="", poster="", lmt=None):
    return common.plugin_url(action="episodes", tmdb=tmdb_id, season=season, show=title,
                             poster=poster, lmt=lmt)
# def episodes_url(tmdb_id, season, title="", poster=""):
#     return common.plugin_url(action="episodes", tmdb=tmdb_id, season=season, show=title, poster=poster)


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _play_values(entry):
    return _SafeDict(
        tmdb=entry.get("tmdb") or "",
        imdb=entry.get("imdb") or "",
        tvdb=entry.get("tvdb") or "",
        season=entry.get("season") if entry.get("season") is not None else "",
        episode=entry.get("episode") if entry.get("episode") is not None else "",
        title=entry.get("show_title") or entry.get("title") or "",
        year=entry.get("year") or "",
    )


def custom_play_url(entry):
    template = common.setting(
        "movie_template" if entry["kind"] == "movie" else "episode_template"
    )
    return template.format_map(_play_values(entry)) if template else ""


# Query keys a picked plugin path may already use for each value; the first is added when none is.
_PATH_KEYS = (
    ("tmdb", ("tmdb_id", "tmdb", "tmdbid")),
    ("imdb", ("imdb_id", "imdb", "imdbnumber")),
    ("tvdb", ("tvdb_id", "tvdb", "tvdbid")),
    ("season", ("season",)),
    ("episode", ("episode",)),
    ("title", ("title",)),
    ("year", ("year",)),
)


def plugin_path_url(entry):
    """The picked plugin path with this item's ids filled in or added to its query."""
    path = common.setting(
        "movie_plugin_path" if entry["kind"] == "movie" else "episode_plugin_path"
    )
    if not path:
        return ""
    values = _play_values(entry)
    if "{" in path:
        return path.format_map(values)
    base, _, query = path.partition("?")
    params = parse_qsl(query, keep_blank_values=True)
    present = {k.lower() for k, _ in params}
    replace = {}
    for field, keys in _PATH_KEYS:
        for key in keys:
            replace[key] = field
    params = [(k, values[replace[k.lower()]] if k.lower() in replace else v) for k, v in params]
    for field, keys in _PATH_KEYS:
        if values[field] != "" and not present.intersection(keys):
            params.append((keys[0], values[field]))
    params = [(k, v) for k, v in params if v != ""]
    return base + "?" + urlencode(params) if params else base


def player_url(entry):
    """Where to send a movie or episode, or "" when no player is set up."""
    mode = common.setting_int("playback", PLAYBACK_NONE)
    if mode == PLAYBACK_PLUGIN:
        return plugin_path_url(entry)
    if mode == PLAYBACK_CUSTOM:
        return custom_play_url(entry)
    return ""


def play_route(entry):
    """Our own play route; it records what is about to play, then hands off."""
    return common.plugin_url(
        action="play",
        kind=entry["kind"],
        tmdb=entry.get("tmdb"),
        imdb=entry.get("imdb"),
        tvdb=entry.get("tvdb"),
        season=entry.get("season"),
        episode=entry.get("episode"),
        title=entry.get("title"),
        show=entry.get("show_title"),
        year=entry.get("year"),
        resume=entry.get("resume_pos") or None,
        total=entry.get("resume_total") or None,
    )


def target(entry):
    """Return (path, is_folder) for an entry."""
    if entry["kind"] == "tvshow":
        action = common.setting_int("tvshow_action", 0)
        if (
            action == 1
            and entry.get("next_season") is not None
            and entry.get("next_episode") is not None
        ):
            episode = dict(entry, kind="episode", show_title=entry.get("title"),
                           season=entry["next_season"], episode=entry["next_episode"])
            return play_route(episode), False
        if entry.get("tmdb"):
            return seasons_url(entry["tmdb"], entry.get("title", ""), entry.get("lmt")), True
        return common.plugin_url(action="noop", reason="no_tmdb"), False
    return play_route(entry), False


# -- context menu ---------------------------------------------------------------

def context_menu(entry, in_resume_list=False):
    items = []
    kind = entry["kind"]
    has_ids = bool(entry.get("tmdb") or entry.get("imdb") or entry.get("tvdb"))
    if kind in ("movie", "episode") and has_ids:
        ids = dict(kind=kind, source=entry.get("source"), media_id=entry.get("media_id"),
            tmdb=entry.get("tmdb"), season=entry.get("season"), episode=entry.get("episode"),
            lmt=entry.get("lmt"))
        if entry.get("playcount"):
            items.append(("Floppy: Mark as unwatched", "RunPlugin({})".format(
                common.plugin_url(action="unwatch", **ids))))
        else:
            items.append(("Floppy: Mark as watched", "RunPlugin({})".format(
                common.plugin_url(action="mark_watched", **ids))))
    if kind == "tvshow" and entry.get("tmdb") and entry.get("season") is None:
        items.append(("Floppy: Mark show watched", "RunPlugin({})".format(common.plugin_url(
            action="mark_show_watched", tmdb=entry["tmdb"], lmt=entry.get("lmt"),
            title=entry.get("title")))))
    if in_resume_list or entry.get("resume_pos"):
        items.append(("Floppy: Remove from Continue Watching", "RunPlugin({})".format(common.plugin_url(
            action="clear_resume", kind=kind, tmdb=entry.get("tmdb"), imdb=entry.get("imdb"),
            tvdb=entry.get("tvdb"), season=entry.get("season"), episode=entry.get("episode")))))
    if kind in ("movie", "tvshow") and entry.get("tmdb"):
        media_type = "movie" if kind == "movie" else "tv"
        if entry.get("status") == 0:
            items.append(("Floppy: Remove from watchlist", "RunPlugin({})".format(common.plugin_url(
                action="remove_watchlist", media_type=media_type, source=entry.get("source") or "tmdb",
                media_id=entry.get("media_id") or entry["tmdb"]))))
        elif entry.get("status") is None:
            items.append(("Floppy: Add to watchlist", "RunPlugin({})".format(common.plugin_url(
                action="add_watchlist", media_type=media_type, tmdb=entry["tmdb"]))))
        # Any tracked movie/show, watchlist items included, can be removed from Floppy entirely.
        # Season rows are skipped so a season in a list can never delete the whole show.
    if (
        kind in ("movie", "tvshow")
        and entry.get("status") is not None
        and entry.get("media_id")
        and entry.get("season") is None
    ):
        items.append(("Floppy: Remove from Floppy", "RunPlugin({})".format(common.plugin_url(
            action="remove_from_floppy",
            lmt=entry.get("lmt"),
            media_type="movie" if kind == "movie" else "tv",
            source=entry.get("source") or "tmdb",
            media_id=entry.get("media_id"),
            title=entry.get("title")))))
    if kind == "episode" and entry.get("tmdb"):
         items.append(("Floppy: Go to show", "ActivateWindow(Videos,{},return)".format(
            seasons_url(entry["tmdb"], entry.get("show_title", ""), entry.get("lmt")))))
    items.append(("Floppy: Refresh widgets", "RunPlugin({})".format(
        common.plugin_url(action="refresh"))))
    return items


# -- list items -----------------------------------------------------------------

def _episode_label(entry):
    season, episode = entry.get("season"), entry.get("episode")
    if season is None or episode is None:
        return entry.get("title") or ""
    return "{}x{:02d}. {}".format(season, int(episode), entry.get("title") or "")


def build(entry, in_resume_list=False):
    kind = entry["kind"]
    # Artwork was looked up by tmdb.prefetch; anything it left to the service shows Floppy's poster.
    extra = tmdb.details("movie" if kind == "movie" else "tv", entry.get("tmdb"),
                         fetch=False) if entry.get("tmdb") else {}

    if kind == "episode":
        label = _episode_label(entry)
    else:
        label = entry.get("title") or extra.get("title") or ""
    if entry.get("label_prefix"):
        label = "{}  {}".format(entry["label_prefix"], label)

    li = xbmcgui.ListItem(label=label, offscreen=True)
    if entry.get("label2"):
        li.setLabel2(entry["label2"])

    # -- info tag ---------------------------------------------------------------
    tag = li.getVideoInfoTag()
    tag.setMediaType(kind)
    tag.setTitle(entry.get("title") or extra.get("title") or "")
    plot = entry.get("plot") or (extra.get("plot") if kind != "episode" else "")
    if plot:
        tag.setPlot(plot)
    if entry.get("tagline"):
        tag.setTagLine(entry["tagline"])
    premiered = entry.get("premiered") or (extra.get("premiered") if kind != "episode" else "")
    if premiered:
        if kind == "episode":
            tag.setFirstAired(premiered)
        tag.setPremiered(premiered)
        try:
            tag.setYear(int(premiered[:4]))
        except ValueError:
            pass
    elif entry.get("year"):
        tag.setYear(int(entry["year"]))
    genres = entry.get("genres") or extra.get("genres")
    if genres:
        tag.setGenres(list(genres))
    if extra.get("studio"):
        tag.setStudios(extra["studio"])
    rating = entry.get("rating") or extra.get("rating")
    if rating:
        tag.setRating(float(rating), int(extra.get("votes") or 0), "tmdb", True)
    if entry.get("user_score"):
        try:
            tag.setUserRating(int(round(float(entry["user_score"]))))
        except (TypeError, ValueError):
            pass
    runtime = entry.get("runtime") or (extra.get("runtime") if kind == "movie" else 0)
    if runtime:
        tag.setDuration(int(runtime))
    if entry.get("playcount"):
        tag.setPlaycount(int(entry["playcount"]))
    if entry.get("lastplayed"):
        tag.setLastPlayed(entry["lastplayed"] + " 00:00:00")
    if entry.get("resume_pos"):
        tag.setResumePoint(float(entry["resume_pos"]), float(entry.get("resume_total") or 0))

    if kind == "episode":
        tag.setTvShowTitle(entry.get("show_title") or extra.get("title") or "")
        if entry.get("season") is not None:
            tag.setSeason(int(entry["season"]))
        if entry.get("episode") is not None:
            tag.setEpisode(int(entry["episode"]))
        # Episode entries carry the show's ids; keep them out of uniqueids so
        # nothing mistakes them for episode ids.
        if entry.get("tmdb"):
            li.setProperty("tvshow.tmdb_id", entry["tmdb"])
        if extra.get("tvdb") or entry.get("tvdb"):
            li.setProperty("tvshow.tvdb_id", extra.get("tvdb") or entry.get("tvdb"))
        # Only show-level sources: an episode entry's own imdb may be the episode's.
        if extra.get("imdb") or entry.get("show_imdb"):
            li.setProperty("tvshow.imdb_id", extra.get("imdb") or entry.get("show_imdb"))
    else:
        if kind == "tvshow":
            tag.setTvShowTitle(entry.get("title") or "")
            if extra.get("status"):
                tag.setTvShowStatus(extra["status"])
            if entry.get("season") is not None:
                tag.setSeason(int(entry["season"]))
        ids = {k: v for k, v in (("tmdb", entry.get("tmdb")),
                                  ("imdb", entry.get("imdb") or extra.get("imdb")),
                                  ("tvdb", entry.get("tvdb") or extra.get("tvdb"))) if v}
        # Kodi derives IMDBNumber from the default unique id, so imdb leads when known.
        # No setIMDBNumber: it overwrites whichever id is the default.
        if ids:
            default = "imdb" if ids.get("imdb") else "tmdb" if ids.get("tmdb") else next(iter(ids))
            tag.setUniqueIDs(ids, default)

    # -- properties -------------------------------------------------------------
    if entry.get("tmdb"):
        li.setProperty("tmdb_id", entry["tmdb"])
        li.setProperty("tmdb_type", "movie" if kind == "movie" else "tv")
    if entry.get("episodes_left") is not None:
        li.setProperty("floppy.episodes_left", str(entry["episodes_left"]))
    if entry.get("air_datetime"):
        li.setProperty("floppy.air_datetime", entry["air_datetime"])

    # -- art --------------------------------------------------------------------
    poster = entry.get("poster") or extra.get("poster") or ""
    fanart = extra.get("fanart") or ""
    landscape = extra.get("landscape") or fanart
    art = {
        "poster": poster,
        "fanart": fanart or poster,
        "landscape": landscape,
        "clearlogo": extra.get("clearlogo") or "",
        "icon": poster,
    }
    if kind == "episode":
        thumb = entry.get("thumb") or landscape or fanart or poster
        art.update({
            "thumb": thumb,
            "tvshow.poster": poster,
            "tvshow.fanart": fanart,
            "tvshow.landscape": landscape,
            "tvshow.clearlogo": extra.get("clearlogo") or "",
        })
    else:
        art["thumb"] = poster
    li.setArt({k: v for k, v in art.items() if v})

    # -- paths used by the skin's info dialog buttons ---------------------------
    path, is_folder = target(entry)
    li.setPath(path)
    if kind in ("movie", "episode") and model.playable(entry):
        # Play / Resume / Play from beginning buttons
        li.setProperty("floppy.play_path", play_route(entry))
    if kind == "tvshow" and entry.get("tmdb"):
        # Episodes button
        li.setProperty("floppy.seasons_path",
                       seasons_url(entry["tmdb"], entry.get("title", ""), entry.get("lmt")))
        # Play next episode button (only when Floppy knows the next episode)
        if entry.get("next_season") is not None and entry.get("next_episode") is not None:
            nxt = dict(entry, kind="episode", show_title=entry.get("title"),
                       season=entry["next_season"], episode=entry["next_episode"])
            li.setProperty("floppy.next_play_path", play_route(nxt))
            li.setProperty("floppy.next_label", "S{:02d}E{:02d}".format(
                int(entry["next_season"]), int(entry["next_episode"])))
    if kind in ("movie", "tvshow") and entry.get("tmdb"):
        # Add / Remove from watchlist button: floppy.status 0 means on the watchlist (planning);
        # no floppy.status means Floppy doesn't track the item, as in context_menu()
        if entry.get("status") is not None:
            li.setProperty("floppy.status", str(entry["status"]))
        li.setProperty("floppy.remove_watchlist_path", common.plugin_url(
            action="remove_watchlist", media_type="movie" if kind == "movie" else "tv",
            source=entry.get("source") or "tmdb", media_id=entry.get("media_id") or entry["tmdb"]))

    li.setProperty("IsPlayable", "false")
    li.addContextMenuItems(context_menu(entry, in_resume_list))
    return path, li, is_folder


def folder_item(label, url, icon="DefaultFolder.png", plot="", fanart=""):
    li = xbmcgui.ListItem(label=label, offscreen=True)
    art = {"icon": icon, "thumb": icon}
    if fanart:
        art["fanart"] = fanart
    li.setArt(art)
    if plot:
        li.getVideoInfoTag().setPlot(plot)
    return url, li, True


def is_widget_context():
    """Widgets live on the Home window; normal browsing happens in Videos."""
    return bool(xbmc.getCondVisibility("Window.IsVisible(home)")) and not bool(
        xbmc.getCondVisibility("Window.IsVisible(videos)")
    )
