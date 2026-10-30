"""Season and episode browsing that uses Floppy's watched state.

TMDb Helper is only used to play an episode; nothing here reads or writes Trakt.
"""

from datetime import date

import xbmc
import xbmcgui

from . import categories, common, listing, model, tmdb
from .api import FloppyError


def _date(value):
    return value[:10] if isinstance(value, str) and value else ""


def _aired(day):
    return bool(day) and day <= date.today().isoformat()


def _resume_map(router, tmdb_id, season):
    try:
        payload = router.api.playback_progress(["episode"], completed=False, limit=200,
                                               ttl=categories._list_ttl())
    except FloppyError:
        return {}
    out = {}
    for row in (payload or {}).get("results") or []:
        if str(row.get("media_id")) == str(tmdb_id) and row.get("season_number") == season:
            out[row.get("episode_number")] = (int(row.get("position_seconds") or 0),
                                              int(row.get("duration_seconds") or 0))
    return out

def _resolve_bucket(router, tmdb_id):
    """Find which Floppy library (TV or anime) tracks this show."""
    ttl = categories._list_ttl()
    detail = router.api.show_detail(tmdb_id, ttl=ttl) or {}
    if detail.get("tracked"):
        return detail, None
    try:
        anime = router.api.show_detail(tmdb_id, lmt="anime", ttl=ttl) or {}
    except FloppyError:
        return detail, None
    if anime.get("tracked"):
        return anime, "anime"
    return detail, None

def list_seasons(router):
    if router._need_setup():
        return
    tmdb_id = router.params.get("tmdb")
    lmt = router.params.get("lmt") or None
    try:
        if lmt:
            detail = router.api.show_detail(tmdb_id, lmt=lmt, ttl=categories._list_ttl()) or {}
        else:
            detail, lmt = _resolve_bucket(router, tmdb_id)
    except FloppyError as exc:
        router._error(exc)
        router._finish([], "seasons", succeeded=False)
        return
    extra = tmdb.details("tv", tmdb_id)
    title = detail.get("title") or extra.get("title") or router.params.get("show", "")
    poster = tmdb.art_url(model._img(detail.get("image")) or extra.get("poster", ""), "poster")
    fanart = tmdb.art_url(extra.get("fanart") or model._img(detail.get("backdrop")) or "", "backdrop") or poster
    landscape = tmdb.art_url(extra.get("landscape") or "", "backdrop") or fanart
    clearlogo = tmdb.art_url(extra.get("clearlogo", ""), "clearlogo")

    # Floppy serialises each season like a tracked-media row: details under "item",
    # episodes watched in "progress", episodes still to watch in "*episodes_left".
    rows = (detail.get("related") or {}).get("seasons") or []
    seasons = []
    for row in rows:
        item = row.get("item") or {}
        number = item.get("season_number")
        if number is None:
            continue
        seen = int(row.get("progress") or 0)
        left = row.get("total_episodes_left")
        if left is None:
            left = row.get("episodes_left")
        total = seen + int(left) if left is not None else 0
        seasons.append((number, item, seen, total))
    seasons.sort(key=lambda s: (s[0] == 0, s[0]))

    items = []
    for number, item, seen, total in seasons:
        label = item.get("title") or ("Specials" if number == 0 else "Season {}".format(number))
        if label == title:
            label = "Specials" if number == 0 else "Season {}".format(number)

        li = xbmcgui.ListItem(label=label, offscreen=True)
        tag = li.getVideoInfoTag()
        tag.setMediaType("season")
        tag.setTitle(label)
        tag.setTvShowTitle(title)
        tag.setSeason(int(number))
        aired = _date(item.get("release_datetime"))
        if aired:
            tag.setPremiered(aired)
            try:
                tag.setYear(int(aired[:4]))
            except ValueError:
                pass
        if total and seen >= total:
            tag.setPlaycount(1)
        li.setProperty("TotalEpisodes", str(total))
        li.setProperty("WatchedEpisodes", str(seen))
        li.setProperty("UnWatchedEpisodes", str(max(total - seen, 0)))
        li.setProperty("tvshow.tmdb_id", str(tmdb_id))
        art = {
            "poster": tmdb.art_url(model._img(item.get("image")), "poster") or poster,
            "fanart": fanart,
            "landscape": landscape,
            "clearlogo": clearlogo,
            "tvshow.poster": poster,
            "tvshow.fanart": fanart,
            "tvshow.clearlogo": clearlogo,
        }
        li.setArt({k: v for k, v in art.items() if v})
        li.addContextMenuItems([
            ("Floppy: Mark season watched", "RunPlugin({})".format(common.plugin_url(
                action="mark_season_watched", tmdb=tmdb_id, season=number, lmt=lmt))),
            ("Floppy: Refresh widgets", "RunPlugin({})".format(common.plugin_url(action="refresh"))),
        ])
        items.append((listing.episodes_url(tmdb_id, number, title, poster, lmt), li, True))
    router._finish(items, "seasons")


def list_episodes(router):
    if router._need_setup():
        return
    p = router.params
    tmdb_id = p.get("tmdb")
    season = int(p.get("season") or 1)
    lmt = p.get("lmt") or None
    try:
        payload = router.api.season_episodes(tmdb_id, season, lmt=lmt, ttl=categories._list_ttl())
    except FloppyError as exc:
        router._error(exc)
        router._finish([], "episodes", succeeded=False)
        return
    extra = tmdb.details("tv", tmdb_id)
    resume = _resume_map(router, tmdb_id, season)
    rows = (payload or {}).get("results") or []
    # TMDb fills only what Floppy's episode data lacks; one cached request per season.
    fill = {}
    items = [row.get("item") or {} for row in rows]
    if any(not i.get("synopsis") or not i.get("runtime_minutes") or not model._img(i.get("image"))
           for i in items):
        fill = tmdb.season_episodes(tmdb_id, season)

    entries = []
    for row in rows:
        item = row.get("item") or {}
        number = item.get("episode_number")
        if number is None:
            continue
        gap = fill.get(number) or {}
        aired = _date(item.get("release_datetime"))
        entry = {
            "kind": "episode",
            "tmdb": str(tmdb_id),
            "imdb": "",
            "tvdb": "",
            "source": "tmdb",
            "media_id": str(tmdb_id),
            "show_title": p.get("show") or extra.get("title", ""),
            "title": item.get("title") or "Episode {}".format(number),
            "season": season,
            "episode": number,
            "thumb": model._img(item.get("image")) or gap.get("thumb", ""),
            "poster": p.get("poster") or extra.get("poster", ""),
            "premiered": aired,
            "plot": item.get("synopsis") or gap.get("plot", ""),
            "playcount": 1 if row.get("tracked") else 0,
            "runtime": int(item.get("runtime_minutes") or gap.get("runtime") or 0) * 60,
        }
        pos, total = resume.get(number, (0, 0))
        if pos >= 60 and not (total and pos >= total * 0.95):
            entry["resume_pos"], entry["resume_total"] = pos, total
        if aired and not _aired(aired):
            entry["label2"] = "Airs {}".format(aired)
        entries.append(entry)
    router._render_entries(entries, False, "episodes", False, {})

def _unwatched_aired(router, tmdb_id, season, lmt):
    """(season, episode) pairs that have aired and aren't watched in Floppy."""
    payload = router.api.season_episodes(tmdb_id, season, lmt=lmt)
    todo = []
    for row in (payload or {}).get("results") or []:
        item = row.get("item") or {}
        number = item.get("episode_number")
        if (number is not None and not row.get("tracked")
                and _aired(_date(item.get("release_datetime")))):
            todo.append((season, number))
    return todo


def _watch_all(router, tmdb_id, todo, lmt, heading):
    """Log a play for each episode, with a cancellable progress dialog."""
    dialog = xbmcgui.DialogProgress()
    dialog.create(common.ADDON_NAME, heading)
    done = 0
    try:
        for index, (season, number) in enumerate(todo):
            if dialog.iscanceled():
                break
            dialog.update(int(index * 100 / len(todo)),
                          "S{:02d}E{:02d}  ({} of {})".format(season, number, index + 1, len(todo)))
            try:
                router.api.watch_episode("tmdb", tmdb_id, season, number, lmt=lmt)
                done += 1
            except FloppyError as exc:
                common.log("Could not mark S{}E{}: {}".format(season, number, exc), xbmc.LOGWARNING)
    finally:
        dialog.close()
    return done


def mark_show_watched(router):
    p = router.params
    tmdb_id = p.get("tmdb")
    lmt = p.get("lmt") or None
    title = p.get("title") or "this show"
    try:
        if lmt:
            detail = router.api.show_detail(tmdb_id, lmt=lmt) or {}
        else:
            detail, lmt = _resolve_bucket(router, tmdb_id)
    except FloppyError as exc:
        common.notify(str(exc))
        return

    seasons = []
    for row in (detail.get("related") or {}).get("seasons") or []:
        number = (row.get("item") or {}).get("season_number")
        if not number:  # skips missing numbers and specials (season 0)
            continue
        if row.get("episodes_left") == 0 and int(row.get("progress") or 0) > 0:
            continue  # every released episode already watched
        seasons.append(number)

    todo = []
    for number in sorted(seasons):
        try:
            todo.extend(_unwatched_aired(router, tmdb_id, number, lmt))
        except FloppyError as exc:
            common.log("Could not read season {}: {}".format(number, exc), xbmc.LOGWARNING)

    if not todo:
        common.notify("Nothing left to mark in {}".format(title))
        return
    if not xbmcgui.Dialog().yesno(
        common.ADDON_NAME,
        "Mark {} unwatched episode(s) of {} as watched in Floppy?\n\nSpecials are not included."
        .format(len(todo), title),
    ):
        return
    done = _watch_all(router, tmdb_id, todo, lmt, "Marking {} as watched".format(title))
    router._after_change("Marked {} episode(s) as watched".format(done))

def mark_season_watched(router):
    p = router.params
    tmdb_id, season = p.get("tmdb"), int(p.get("season"))
    lmt = p.get("lmt") or None
    try:
        todo = _unwatched_aired(router, tmdb_id, season, lmt)
    except FloppyError as exc:
        common.notify(str(exc))
        return
    if not todo:
        common.notify("Nothing left to mark in this season")
        return
    if not xbmcgui.Dialog().yesno(common.ADDON_NAME, "Mark {} episode(s) of season {} as watched in Floppy?"
                                  .format(len(todo), season)):
        return
    done = _watch_all(router, tmdb_id, todo, lmt, "Marking season {} as watched".format(season))
    router._after_change("Marked {} episode(s) as watched".format(done))


def unwatch(router):
    """Remove the most recent play of a movie or episode."""
    p = router.params
    source = p.get("source") or "tmdb"
    media_id = p.get("media_id") or p.get("tmdb")
    try:
        if p.get("kind") == "movie":
            router.api.unwatch_movie(source, media_id)
        else:
            router.api.unwatch_episode(source, media_id, p.get("season"), p.get("episode"),
                                       lmt=p.get("lmt") or None)
    except FloppyError as exc:
        common.notify("Could not mark as unwatched: {}".format(exc))
        return
    router._after_change("Marked as unwatched")