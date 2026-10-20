"""Build Kodi ListItems from entries and decide where each item points."""

from urllib.parse import urlencode

import xbmc
import xbmcgui

from . import common, model, tmdb

TMDBH = "plugin://plugin.video.themoviedb.helper/"


# -- where things go ----------------------------------------------------------

def tmdbh_seasons_url(tmdb_id):
    return TMDBH + "?" + urlencode({"info": "seasons", "tmdb_type": "tv", "tmdb_id": tmdb_id})

def seasons_url(tmdb_id, title="", lmt=None):
    return common.plugin_url(action="seasons", tmdb=tmdb_id, show=title, lmt=lmt)


def episodes_url(tmdb_id, season, title="", poster="", lmt=None):
    return common.plugin_url(action="episodes", tmdb=tmdb_id, season=season, show=title,
                             poster=poster, lmt=lmt)
# def episodes_url(tmdb_id, season, title="", poster=""):
#     return common.plugin_url(action="episodes", tmdb=tmdb_id, season=season, show=title, poster=poster)


def tmdbh_play_url(entry):
    """TMDb Helper player URL for a movie or episode entry."""
    if entry["kind"] == "movie":
        params = {"info": "play", "tmdb_type": "movie"}
    else:
        params = {
            "info": "play",
            "tmdb_type": "tv",
            "season": entry.get("season"),
            "episode": entry.get("episode"),
        }
    if entry.get("tmdb"):
        params["tmdb_id"] = entry["tmdb"]
    elif entry.get("imdb"):
        params["imdb_id"] = entry["imdb"]
    elif entry.get("tvdb"):
        params["tvdb_id"] = entry["tvdb"]
    return TMDBH + "?" + urlencode(params)


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def custom_play_url(entry):
    template = common.setting(
        "movie_template" if entry["kind"] == "movie" else "episode_template"
    )
    if not template:
        return tmdbh_play_url(entry)
    values = _SafeDict(
        tmdb=entry.get("tmdb") or "",
        imdb=entry.get("imdb") or "",
        tvdb=entry.get("tvdb") or "",
        season=entry.get("season") if entry.get("season") is not None else "",
        episode=entry.get("episode") if entry.get("episode") is not None else "",
        title=entry.get("show_title") or entry.get("title") or "",
        year=entry.get("year") or "",
    )
    return template.format_map(values)


def player_url(entry):
    if common.setting_int("player", 0) == 1:
        return custom_play_url(entry)
    return tmdbh_play_url(entry)


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
            if action == 2:
                return tmdbh_seasons_url(entry["tmdb"]), True
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
        # Tracked movies/shows (watchlist items already have "Remove from watchlist").
        # Season rows are skipped so a season in a list can never delete the whole show.
    if (
        kind in ("movie", "tvshow")
        and entry.get("status") not in (None, 0)
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
    extra = tmdb.details("movie" if kind == "movie" else "tv", entry.get("tmdb")) if entry.get("tmdb") else {}

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
        if ids:
            tag.setUniqueIDs(ids, "tmdb" if ids.get("tmdb") else next(iter(ids)))
        if entry.get("imdb") or extra.get("imdb"):
            tag.setIMDBNumber(entry.get("imdb") or extra.get("imdb"))

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
