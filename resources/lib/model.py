"""Turn the different Floppy response shapes into one simple entry dict.

Every entry has:
    kind        "movie", "tvshow" or "episode"
    tmdb        TMDb id of the movie, or of the show for tvshow/episode entries
    imdb, tvdb  extra ids when known
    source, media_id   Floppy's own identity for the movie/show (for actions)
plus optional display fields (title, show_title, season, episode, plot, poster,
thumb, premiered, genres, rating, runtime, resume_pos, resume_total, status,
playcount, label_prefix, user_score, episodes_left).
"""

STATUS_PLANNING = 0
STATUS_IN_PROGRESS = 1
STATUS_PAUSED = 2
STATUS_COMPLETED = 3
STATUS_DROPPED = 4

_TV_TYPES = {"tv", "season", "anime"}
_IMG_NONE_HINTS = ("none.svg", "img_none", "/static/img/none")


def _img(url):
    if not url or not isinstance(url, str):
        return ""
    if any(hint in url for hint in _IMG_NONE_HINTS):
        return ""
    return url


def _date(value):
    if not value or not isinstance(value, str):
        return ""
    return value[:10]


def _year(date):
    try:
        return int(date[:4]) if date else None
    except ValueError:
        return None


def _ids_from(item):
    """Return (tmdb, imdb, tvdb) for a serialized Floppy item."""
    item = item or {}
    ids = dict(item.get("ids") or {})
    raw = item.get("provider_external_ids") or {}
    for short, long_name in (("tmdb", "tmdb_id"), ("imdb", "imdb_id"), ("tvdb", "tvdb_id")):
        if not ids.get(short) and raw.get(long_name):
            ids[short] = str(raw[long_name])
    tmdb = ""
    if item.get("source") == "tmdb" and item.get("media_id"):
        tmdb = str(item["media_id"])
    elif ids.get("tmdb"):
        tmdb = str(ids["tmdb"])
    return tmdb, str(ids.get("imdb") or ""), str(ids.get("tvdb") or "")


def _kind_for(media_type):
    if media_type == "movie":
        return "movie"
    if media_type == "episode":
        return "episode"
    if media_type in _TV_TYPES:
        return "tvshow"
    return None


def _base(kind, item):
    tmdb, imdb, tvdb = _ids_from(item)
    return {
        "kind": kind,
        "tmdb": tmdb,
        "imdb": imdb,
        "tvdb": tvdb,
        "source": (item or {}).get("source") or ("tmdb" if tmdb else ""),
        "media_id": str((item or {}).get("media_id") or tmdb),
    }


def from_media(result, next_up=False):
    """A tracked-media row from /media, /lists/{id}/items or /home."""
    item = result.get("item") or {}
    kind = _kind_for(item.get("media_type"))
    if kind is None:
        return None
    if kind == "episode":
        kind = "tvshow"  # a tracked show row; episodes come from next_episode
    entry = _base(kind, item)
    premiered = _date(item.get("release_datetime") or item.get("release_date"))
    entry.update(
        {
            "title": item.get("localized_title") or item.get("title") or "",
            "plot": item.get("synopsis") or "",
            "poster": _img(item.get("image")),
            "premiered": premiered,
            "year": _year(premiered),
            "genres": list(item.get("genres") or []),
            "rating": item.get("provider_rating") or 0,
            "runtime": int(item.get("runtime_minutes") or 0) * 60,
            "status": result.get("status"),
            "user_score": result.get("score"),
            "episodes_left": result.get("episodes_left"),
            "playcount": 1 if result.get("status") == STATUS_COMPLETED else 0,
        }
    )
    if item.get("media_type") == "season" and item.get("season_number") is not None:
        entry["season"] = item["season_number"]

    nxt = result.get("next_episode")
    if next_up:
        if kind != "tvshow" or not nxt or nxt.get("season_number") is None:
            return None
        show_poster = entry["poster"]
        entry.update(
            {
                "kind": "episode",
                "show_title": entry["title"],
                "title": nxt.get("title") or "Episode {}".format(nxt.get("episode_number")),
                "season": nxt.get("season_number"),
                "episode": nxt.get("episode_number"),
                "thumb": _img(nxt.get("image")),
                "poster": show_poster,
                "premiered": _date(nxt.get("air_date")),
                "plot": "",
                "playcount": 0,
                "sort_date": _date(nxt.get("air_date")),
            }
        )
    elif kind == "tvshow" and nxt and nxt.get("season_number") is not None:
        entry["next_season"] = nxt.get("season_number")
        entry["next_episode"] = nxt.get("episode_number")
    return entry


def from_progress(row):
    """A resume position from /playback/progress."""
    kind = _kind_for(row.get("media_type"))
    if kind not in ("movie", "episode"):
        return None
    item = {
        "source": row.get("source"),
        "media_id": row.get("media_id"),
        "ids": row.get("ids") or {},
    }
    entry = _base(kind, item)
    if kind == "episode" and row.get("source") == "tmdb":
        # Episode rows are keyed by the show's TMDb id; never trust an
        # episode-level tmdb id from `ids` here.
        entry["tmdb"] = str(row.get("media_id") or "")
    position = int(row.get("position_seconds") or 0)
    duration = int(row.get("duration_seconds") or 0)
    entry.update(
        {
            "title": row.get("title") or "",
            "show_title": row.get("series_title") or "",
            "season": row.get("season_number"),
            "episode": row.get("episode_number"),
            "poster": _img(row.get("image")),
            "resume_pos": position,
            "resume_total": duration,
            "runtime": duration,
            "updated_at": row.get("updated_at") or "",
        }
    )
    if kind == "episode":
        if entry["title"] == entry["show_title"]:
            entry["title"] = "Episode {}".format(row.get("episode_number"))
        entry["thumb"] = entry["poster"]
    return entry


def from_candidate(candidate, media_type):
    """A Discover row item or a /recommendations pick."""
    kind = _kind_for(media_type or candidate.get("media_type"))
    if kind not in ("movie", "tvshow"):
        return None
    entry = _base(kind, candidate)
    premiered = _date(candidate.get("release_date"))
    entry.update(
        {
            "title": candidate.get("localized_title") or candidate.get("title") or "",
            "poster": _img(candidate.get("image")),
            "premiered": premiered,
            "year": _year(premiered),
            "genres": list(candidate.get("genres") or []),
            "rating": candidate.get("rating") or 0,
        }
    )
    if not entry.get("year") and candidate.get("year"):
        try:
            entry["year"] = int(str(candidate["year"])[:4])
        except ValueError:
            pass
    reason = candidate.get("source_reason")
    anchor = candidate.get("anchor_title")
    if reason and anchor:
        entry["tagline"] = "{} {}".format(reason, anchor)
    return entry


def from_history(row):
    """A flat /history entry."""
    kind = _kind_for(row.get("media_type"))
    if kind not in ("movie", "episode"):
        return None
    item = row.get("item") or {}
    entry = _base(kind, item)
    entry["lmt"] = "anime" if item.get("library_media_type") == "anime" else None
    played = _date(row.get("played_at_local") or row.get("end_date"))
    if kind == "movie":
        entry.update(
            {
                "title": item.get("localized_title") or row.get("title") or "",
                "poster": _img(row.get("poster")),
                "genres": list(row.get("genres") or item.get("genres") or []),
                "runtime": int(row.get("runtime_minutes") or 0) * 60,
            }
        )
    else:
        show = row.get("show") or {}
        title = row.get("display_title") or ""
        code = row.get("episode_code") or ""
        if code and title.startswith(code):
            title = title[len(code):].lstrip(" -:·")
        show_title = show.get("title") or row.get("title") or ""
        if not title or title == show_title:
            title = "Episode {}".format(row.get("episode_number", item.get("episode_number")))
        entry.update(
            {
                "show_title": show_title,
                "title": title,
                "season": row.get("season_number", item.get("season_number")),
                "episode": row.get("episode_number", item.get("episode_number")),
                "thumb": _img(row.get("poster")),
                "poster": _img(show.get("image")),
                "runtime": int(row.get("runtime_minutes") or 0) * 60,
            }
        )
    entry.update({"playcount": 1, "lastplayed": played, "user_score": row.get("score")})
    return entry


def from_event(event):
    """A calendar event from /calendar."""
    item = event.get("item") or {}
    media_type = item.get("media_type")
    when = _date(event.get("datetime"))
    if media_type == "movie":
        entry = _base("movie", item)
        entry.update(
            {
                "title": item.get("localized_title") or item.get("title") or "",
                "poster": _img(item.get("image")),
                "premiered": when,
                "year": _year(when),
                "plot": item.get("synopsis") or "",
            }
        )
        release_type = event.get("release_type") or ""
        if release_type:
            entry["tagline"] = release_type.replace("_", " ").title()
    elif media_type in ("episode", "season", "tv") and event.get("content_number") is not None:
        entry = _base("episode", item)
        entry.update(
            {
                "show_title": item.get("title") or "",
                "title": "Episode {}".format(event["content_number"]),
                "season": item.get("season_number"),
                "episode": event["content_number"],
                "poster": _img(item.get("image")),
                "thumb": "",
                "premiered": when,
            }
        )
    else:
        return None
    entry["sort_date"] = event.get("datetime") or ""
    entry["air_datetime"] = event.get("datetime") or ""
    return entry


def entry_key(entry):
    return (
        entry.get("kind"),
        entry.get("tmdb") or entry.get("imdb") or entry.get("tvdb") or entry.get("title"),
        entry.get("season"),
        entry.get("episode"),
    )


def dedupe(entries):
    seen = set()
    out = []
    for entry in entries:
        if not entry:
            continue
        key = entry_key(entry)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def playable(entry):
    """True when a player can be pointed at this entry."""
    return bool(entry.get("tmdb") or entry.get("imdb") or entry.get("tvdb"))
