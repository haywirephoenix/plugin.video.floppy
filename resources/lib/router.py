"""Plugin entry point: menus, lists and item actions."""

import sys
import time
from urllib.parse import parse_qsl

import xbmc
import xbmcgui
import xbmcplugin
import itertools
import threading

from . import cache, categories, common, listing, model, perf, tmdb
from .api import FloppyAPI, FloppyError


class Router:
    def __init__(self, argv):
        self.base = argv[0]
        self.handle = int(argv[1]) if len(argv) > 1 and argv[1].lstrip("-").isdigit() else -1
        query = argv[2][1:] if len(argv) > 2 and argv[2].startswith("?") else ""
        self.params = dict(parse_qsl(query))
        self.api = FloppyAPI()
        # Widgets get whatever is cached straight away; the service keeps it fresh.
        self.widget = self.params.get("widget") == "1" or listing.is_widget_context()
        self.api.serve_stale = self.widget

    # -- helpers --------------------------------------------------------------

    def _finish(self, items, content="videos", succeeded=True, cache_to_disc=False):
        if self.handle < 0:
            return
        xbmcplugin.setContent(self.handle, content)
        if items:
            xbmcplugin.addDirectoryItems(self.handle, items, len(items))
        xbmcplugin.addSortMethod(self.handle, xbmcplugin.SORT_METHOD_UNSORTED)
        perf.mark("add_items")
        xbmcplugin.endOfDirectory(self.handle, succeeded=succeeded, cacheToDisc=cache_to_disc)
        perf.mark("end_of_directory")

    def _need_setup(self):
        if self.api.configured:
            return False
        if not listing.is_widget_context():
            common.notify("Set your Floppy address and API token first")
            common.addon().openSettings()
        self._finish([], succeeded=False)
        return True

    def _error(self, exc):
        common.log("Floppy request failed: {}".format(exc), xbmc.LOGWARNING)
        if not listing.is_widget_context():
            common.notify(str(exc))

    def _page_size(self):
        try:
            return max(1, int(self.params.get("limit") or common.setting_int("page_size", 20)))
        except ValueError:
            return 20

    def _show_next_page(self):
        if self.params.get("widget") == "1":
            return False
        return common.setting_bool("next_page", True) and not listing.is_widget_context()

    def _render_entries(self, entries, has_more, content, in_resume_list, next_params):
        perf.mark("fetch")
        tmdb.prefetch(
            (("movie" if e["kind"] == "movie" else "tv", e.get("tmdb")) for e in entries),
            deadline=1.0 if self.widget else None,
        )
        perf.mark("prefetch")
        items = []
        for entry in entries:
            try:
                items.append(listing.build(entry, in_resume_list))
            except Exception as exc:  # noqa: BLE001 - one bad row must not empty a widget
                common.log("Skipping item {}: {}".format(entry.get("title"), exc), xbmc.LOGWARNING)
        perf.mark("build")
        if has_more and self._show_next_page():
            page = int(self.params.get("page") or 0) + 1
            url = common.plugin_url(**dict(next_params, page=page))
            label = "[B]Next page ({})[/B]".format(page + 1)
            items.append(listing.folder_item(label, url, icon="DefaultFolder.png"))
        self._finish(items, content)

    # -- menus ----------------------------------------------------------------

    def root(self):
        menu = [
            ("Continue Watching", common.plugin_url(action="list", cat="continue_watching"),
             "DefaultInProgressShows.png", "Movies and episodes you stopped part-way through."),
            ("Next Up", common.plugin_url(action="list", cat="tv_next_up"),
             "DefaultRecentlyAddedEpisodes.png", "The next episode of every show you are watching."),
            ("All Videos", common.plugin_url(action="menu", menu="all"),
             "DefaultVideo.png", "Films, series and anime together."),
            ("Movies", common.plugin_url(action="menu", menu="movies"),
             "DefaultMovies.png", ""),
            ("TV Shows", common.plugin_url(action="menu", menu="tv"),
             "DefaultTVShows.png", ""),
            ("Discover", common.plugin_url(action="discover"),
             "DefaultAddonVideo.png", "Recommendations powered by global trends and your local activity."),
            ("Search", common.plugin_url(action="search"),
             "DefaultAddonsSearch.png", "Search movies and TV shows through Floppy."),
            ("My Lists", common.plugin_url(action="lists"),
             "DefaultPlaylist.png", "Your Floppy lists."),
            ("Floppy Home Rows", common.plugin_url(action="home_rows"),
             "DefaultAddonVideo.png", "The rows from your Floppy home page."),
            ("Tools", common.plugin_url(action="menu", menu="tools"),
             "DefaultAddonProgram.png", ""),
        ]
        items = []
        for entry in menu:
            if len(entry) != 4:
                common.log("Bad root menu entry: {!r}".format(entry), xbmc.LOGWARNING)
                continue
            label, url, icon, plot = entry
            items.append(listing.folder_item(label, url, icon, plot))
        self._finish(items, content="files")

    def menu(self):
        name = self.params.get("menu")
        if name == "tools":
            items = [
                listing.folder_item("Refresh widgets", common.plugin_url(action="refresh"),
                                    "DefaultAddonService.png", "Clear cached lists and reload widgets."),
                listing.folder_item("Show widget paths", common.plugin_url(action="widget_paths"),
                                    "DefaultAddonProgram.png", "Every list's path, for adding widgets by hand."),
                listing.folder_item("Test connection", common.plugin_url(action="test"),
                                    "DefaultAddonNetwork.png", ""),
                listing.folder_item("Clear cache", common.plugin_url(action="clear_cache"),
                                    "DefaultAddonProgram.png", "Also clears cached TMDb artwork."),
                listing.folder_item("Settings", common.plugin_url(action="settings"),
                                    "DefaultAddonProgram.png", ""),
            ]
            # Tools are actions, not folders.
            items = [(url, li, False) for url, li, _ in items]
            self._finish(items, content="files")
            return
        if name == "all":
            keys, icon = categories.ALL_MENU, "DefaultVideo.png"
        elif name == "movies":
            keys, icon = categories.MOVIE_MENU, "DefaultMovies.png"
        else:
            keys, icon = categories.TV_MENU, "DefaultTVShows.png"
        items = []
        for key in keys:
            label, _, _, description, _ = categories.CATEGORIES[key]
            items.append(listing.folder_item(label, common.plugin_url(action="list", cat=key),
                                             icon, description))
        self._finish(items, content="files")

    # -- lists ----------------------------------------------------------------

    def list(self):
        key = self.params.get("cat")
        if key not in categories.CATEGORIES:
            self._finish([], succeeded=False)
            return
        if self._need_setup():
            return
        _, content, fetch, _, in_resume = categories.CATEGORIES[key]
        page = int(self.params.get("page") or 0)
        try:
            entries, has_more = fetch(self.api, page, self._page_size())
        except FloppyError as exc:
            if exc.status == 404 and "Discover" in str(exc):
                common.log("Discover is turned off in Floppy; {} is empty".format(key))
                entries, has_more = [], False
            else:
                self._error(exc)
                self._finish([], content, succeeded=False)
                return
        next_params = {k: v for k, v in self.params.items() if k != "page"}
        self._render_entries(entries, has_more, content, in_resume, next_params)

    def lists(self):
        if self._need_setup():
            return
        try:
            payload = self.api.lists(ttl=categories._list_ttl())
        except FloppyError as exc:
            self._error(exc)
            self._finish([], succeeded=False)
            return
        items = []
        for row in (payload or {}).get("results") or []:
            label = "{} ({})".format(row.get("name"), row.get("items_count", 0))
            url = common.plugin_url(action="list_items", list_id=row.get("id"))
            items.append(listing.folder_item(label, url, row.get("image") or "DefaultPlaylist.png",
                                             row.get("description") or ""))
        self._finish(items, content="files")

    def list_items(self):
        if self._need_setup():
            return
        list_id = self.params.get("list_id")
        page = int(self.params.get("page") or 0)
        size = self._page_size()
        try:
            payload = self.api.list_items(list_id, limit=size, offset=page * size,
                                          ttl=categories._list_ttl())
        except FloppyError as exc:
            self._error(exc)
            self._finish([], succeeded=False)
            return
        entries = [model.from_media(row) for row in (payload or {}).get("results") or []]
        entries = [e for e in model.dedupe(entries) if model.playable(e)]
        has_more = categories._has_more(payload)
        kinds = {e["kind"] for e in entries}
        content = "movies" if kinds == {"movie"} else "tvshows" if kinds == {"tvshow"} else "videos"
        next_params = {k: v for k, v in self.params.items() if k != "page"}
        self._render_entries(entries, has_more, content, False, next_params)

    def home_rows(self):
        if self._need_setup():
            return
        try:
            payload = self.api.home(limit=50, ttl=categories._list_ttl())
        except FloppyError as exc:
            self._error(exc)
            self._finish([], succeeded=False)
            return
        items = []
        for group in (payload or {}).get("groups") or []:
            if group.get("media_type") not in ("movie", "tv", "anime", "all", None, ""):
                continue
            for row in group.get("rows") or []:
                if not row.get("row_id"):
                    continue
                label = row.get("title") or row["row_id"]
                if group.get("label"):
                    label = "{}: {}".format(group["label"], label)
                url = common.plugin_url(action="home_row", row_id=row["row_id"])
                items.append(listing.folder_item(label, url, "DefaultAddonVideo.png",
                                                 row.get("summary") or ""))
        self._finish(items, content="files")

    def home_row(self):
        if self._need_setup():
            return
        row_id = self.params.get("row_id")
        try:
            payload = self.api.home(limit=50, ttl=categories._list_ttl())
        except FloppyError as exc:
            self._error(exc)
            self._finish([], succeeded=False)
            return
        row = None
        for group in (payload or {}).get("groups") or []:
            for candidate in group.get("rows") or []:
                if str(candidate.get("row_id")) == row_id:
                    row = candidate
                    break
            if row:
                break
        entries = [model.from_media(item) for item in (row or {}).get("items") or []]
        entries = [e for e in model.dedupe(entries) if model.playable(e)]
        kinds = {e["kind"] for e in entries}
        content = "movies" if kinds == {"movie"} else "tvshows" if kinds == {"tvshow"} else "videos"
        self._render_entries(entries, False, content, False, {})

    # -- discover -------------------------------------------------------------

    _DISCOVER_TYPES = (
        ("movie", "Movies", "DefaultMovies.png"),
        ("tv", "TV Shows", "DefaultTVShows.png"),
        ("anime", "Anime", "DefaultTVShows.png"),
    )

    def _discover_payload(self, media_type, show_more):
        """Return Floppy's Discover rows, or None after reporting the problem."""
        try:
            return self.api.discover(media_type, show_more=show_more,
                                     ttl=categories._discover_ttl()) or {}
        except FloppyError as exc:
            if exc.status == 404 and "Discover" in str(exc):
                if not listing.is_widget_context():
                    common.notify("Discover is turned off in your Floppy settings")
            else:
                self._error(exc)
            return None

    def discover(self):
        media_type = self.params.get("media_type")
        if not media_type:
            items = [
                listing.folder_item(label, common.plugin_url(action="discover", media_type=mt), icon)
                for mt, label, icon in self._DISCOVER_TYPES
            ]
            items.append(listing.folder_item(
                "Genres", common.plugin_url(action="genres"), "DefaultGenre.png",
                "Popular movies and TV shows on TMDb by genre, not just your own library."))
            self._finish(items, content="files")
            return
        if self._need_setup():
            return

        show_more = self.params.get("show_more") == "1"
        payload = self._discover_payload(media_type, show_more)
        if payload is None:
            self._finish([], succeeded=False)
            return

        icon = "DefaultMovies.png" if media_type == "movie" else "DefaultTVShows.png"
        items = []
        for row in payload.get("rows") or []:
            key = row.get("key")
            entries = [model.from_candidate(i, media_type) for i in row.get("items") or []]
            count = len([e for e in model.dedupe(entries) if model.playable(e)])
            if not key or not count:
                continue
            url = common.plugin_url(action="discover_row", media_type=media_type, key=key,
                                    show_more="1" if show_more else None)
            label = "{} ({})".format(row.get("title") or key, count)
            items.append(listing.folder_item(label, url, icon, row.get("why") or row.get("mission") or ""))

        if not show_more:
            items.append(listing.folder_item(
                "[B]More rows…[/B]",
                common.plugin_url(action="discover", media_type=media_type, show_more="1"),
                "DefaultFolder.png", "Floppy's extra Discover rows."))
        self._finish(items, content="files")

    def discover_row(self):
        if self._need_setup():
            return
        media_type = self.params.get("media_type", "movie")
        key = self.params.get("key")
        show_more = self.params.get("show_more") == "1"
        payload = self._discover_payload(media_type, show_more)
        if payload is None:
            self._finish([], succeeded=False)
            return

        row = next((r for r in payload.get("rows") or [] if r.get("key") == key), None)
        entries = [model.from_candidate(i, media_type) for i in (row or {}).get("items") or []]
        entries = [e for e in model.dedupe(entries) if model.playable(e)]

        page = int(self.params.get("page") or 0)
        page_entries, has_more = categories._slice(entries, page, self._page_size())
        content = "movies" if media_type == "movie" else "tvshows"
        next_params = {k: v for k, v in self.params.items() if k != "page"}
        self._render_entries(page_entries, has_more, content, False, next_params)

    # -- search ---------------------------------------------------------------

    def search(self):
        query = (self.params.get("query") or "").strip()
        in_widget = self.params.get("widget") == "1" or listing.is_widget_context()
        if not query:
            if in_widget:
                self._finish([])
                return
            query = xbmcgui.Dialog().input("Search Floppy").strip()
            if not query:
                self._finish([], succeeded=False)
                return
        if self._need_setup():
            return

        media_type = self.params.get("media_type", "both")
        if media_type in ("collection", "person"):
            self._search_tmdb(media_type, query)
            return
        types = ["movie", "tv"] if media_type == "both" else [media_type]
        size = self._page_size()

        results = {}

        def run(kind):
            try:
                results[kind] = self.api.search(kind, query, limit=size, ttl=3600)
            except FloppyError as exc:
                results[kind] = exc

        threads = [threading.Thread(target=run, args=(kind,)) for kind in types]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        groups = []
        for kind in types:
            payload = results.get(kind)
            if isinstance(payload, FloppyError):
                self._error(payload)
                continue
            groups.append([model.from_candidate(r, kind) for r in (payload or {}).get("results") or []])

        # Alternate movie / show so neither type buries the other.
        entries = []
        for group in itertools.zip_longest(*groups):
            entries.extend(e for e in group if e)
        entries = [e for e in model.dedupe(entries) if model.playable(e)]
        self._mark_tracked(entries, types, query)

        content = "movies" if types == ["movie"] else "tvshows" if types == ["tv"] else "videos"
        self._render_entries(entries, False, content, False, {})

    # Fields a tracked row adds to a search result (status 0 is Planning, so test for None).
    _TRACKED_FIELDS = ("status", "playcount", "user_score", "episodes_left", "next_season",
                       "next_episode", "resume_pos", "resume_total", "tmdb", "imdb", "tvdb",
                       "source", "media_id", "title", "poster", "plot", "runtime")

    def _mark_tracked(self, entries, types, query):
        """Merge library rows into results so they carry what the widgets carry."""
        buckets = list(types)
        if "tv" in types:
            buckets.append("anime")  # a separate Floppy library for shows
        payloads = {}

        def run(bucket):
            try:
                payloads[bucket] = self.api.media(bucket, ttl=categories._list_ttl(),
                                                  search=query, limit=50)
            except FloppyError:
                payloads[bucket] = None

        threads = [threading.Thread(target=run, args=(b,)) for b in buckets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        tracked = {}
        for bucket in buckets:  # tv before anime: a show in both keeps its TV row
            kind = "movie" if bucket == "movie" else "tv"
            for row in (payloads.get(bucket) or {}).get("results") or []:
                found = model.from_media(row)
                if not found or (found["kind"] == "movie") != (kind == "movie"):
                    continue
                found.pop("season", None)
                found["lmt"] = "anime" if bucket == "anime" else None
                for key in ((kind, found.get("source"), found.get("media_id")),
                            (kind, "tmdb", found.get("tmdb"))):
                    if key[2]:
                        tracked.setdefault(key, found)
        for entry in entries:
            kind = "movie" if entry["kind"] == "movie" else "tv"
            found = (tracked.get((kind, entry.get("source"), str(entry.get("media_id"))))
                     or tracked.get((kind, "tmdb", entry.get("tmdb"))))
            if not found:
                continue
            for field in self._TRACKED_FIELDS:
                value = found.get(field)
                if value is not None and value != "":
                    entry[field] = value
            entry["lmt"] = found["lmt"]

    def _search_tmdb(self, kind, query):
        if not tmdb.enabled():
            if self.params.get("widget") != "1" and not listing.is_widget_context():
                common.notify("Add a TMDb API key in Artwork settings to search {}".format(
                    "people" if kind == "person" else "collections"))
            self._finish([])
            return
        items = []
        for r in tmdb.search(kind, query)[: self._page_size()]:
            if kind == "collection":
                url = common.plugin_url(action="collection", id=r.get("id"))
                art = tmdb._image(r.get("poster_path"), "w500") or "DefaultSets.png"
                items.append(listing.folder_item(r.get("name") or "", url, art, r.get("overview") or "",
                                                 fanart=tmdb._image(r.get("backdrop_path"), "w1280")))
            else:
                url = common.plugin_url(action="person", id=r.get("id"))
                art = tmdb._image(r.get("profile_path"), "w500") or "DefaultActor.png"
                known = ", ".join(k.get("title") or k.get("name") or "" for k in r.get("known_for") or [])
                items.append(listing.folder_item(r.get("name") or "", url, art, known))
        self._finish(items, content="files")

    # -- genres --------------------------------------------------------------

    def genre(self):
        """Popular TMDb titles in any of ``genres`` (names joined by " / "), for search categories."""
        in_widget = self.params.get("widget") == "1" or listing.is_widget_context()
        if not tmdb.enabled():
            if not in_widget:
                common.notify("Add a TMDb API key in Artwork settings to browse genres")
            self._finish([])
            return
        media_type = self.params.get("media_type", "both")
        types = ["movie", "tv"] if media_type == "both" else [media_type]
        names = [n.strip().lower() for n in (self.params.get("genres") or "").split("/") if n.strip()]
        language = (self.params.get("language") or "").strip()
        keywords = (self.params.get("keywords") or "").strip()
        size = self._page_size()
        page = int(self.params.get("page") or 0)
        # Pages are cut from one merged list, so each type needs enough for every page so far
        # (plus one, to tell whether there is a next page). TMDb pages are cached.
        wanted_count = (page + 1) * size + 1

        queries = {}
        for kind in types:
            ids = tmdb.genre_ids(kind)
            wanted = sorted({ids[n] for n in names if n in ids})
            # Movie and TV genre names differ: a type with none of the asked genres is skipped.
            if wanted or (not names and (language or keywords)):
                queries[kind] = wanted

        results = {}

        def run(kind):
            results[kind] = tmdb.discover(kind, queries[kind], language, keywords, limit=wanted_count)

        threads = [threading.Thread(target=run, args=(kind,)) for kind in queries]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        groups = [[tmdb.to_entry(r, kind) for r in results.get(kind) or []] for kind in types]
        # Alternate movie / show so neither type buries the other.
        entries = []
        for group in itertools.zip_longest(*groups):
            entries.extend(e for e in group if e)
        entries = [e for e in model.dedupe(entries) if model.playable(e)]
        page_entries, has_more = categories._slice(entries, page, size)

        content = "movies" if types == ["movie"] else "tvshows" if types == ["tv"] else "videos"
        next_params = {k: v for k, v in self.params.items() if k != "page"}
        self._render_entries(page_entries, has_more, content, False, next_params)

    def genres(self):
        """The genre categories as folders, each opening action=genre."""
        from . import genres

        if not tmdb.enabled():
            common.notify("Add a TMDb API key in Artwork settings to browse genres")
            self._finish([], succeeded=False)
            return
        media_type = self.params.get("media_type", "both")
        types = ["movie", "tv"] if media_type == "both" else [media_type]
        known = set()
        for kind in types:
            known.update(tmdb.genre_ids(kind))
        icon = "DefaultMovies.png" if media_type == "movie" else "DefaultTVShows.png"             if media_type == "tv" else "DefaultGenre.png"
        items = []
        for label, params in genres.CATEGORIES:
            # Leave out categories none of these types has, like Reality TV under Movies.
            if params.get("genres") and not any(g.lower() in known for g in params["genres"]):
                continue
            url = common.plugin_url(action="genre", media_type=media_type, **genres.genre_params(params))
            items.append(listing.folder_item(label, url, icon))
        self._finish(items, content="files")

    def collection(self):
        entries = [tmdb.to_entry(p, "movie") for p in tmdb.collection_parts(self.params.get("id"))]
        entries.sort(key=lambda e: e.get("premiered") or "9999")
        self._apply_library_status(entries)
        self._render_entries(entries, False, "movies", False, {})

    def person(self):
        credits = tmdb.person_credits(self.params.get("id"))
        entries = model.dedupe(tmdb.to_entry(c, c.get("media_type")) for c in credits
                               if c.get("media_type") in ("movie", "tv"))
        page = int(self.params.get("page") or 0)
        page_entries, has_more = categories._slice(entries, page, self._page_size())
        self._apply_library_status(page_entries)
        next_params = {k: v for k, v in self.params.items() if k != "page"}
        self._render_entries(page_entries, has_more, "videos", False, next_params)

    def _apply_library_status(self, entries):
        """Mark entries you already track, so the context menu offers the right actions."""
        kinds = {"movie" if e["kind"] == "movie" else "tv" for e in entries}
        status = {}
        for kind in kinds:
            offset = 0
            while True:
                try:
                    payload = self.api.media(kind, ttl=max(categories._list_ttl(), 300),
                                             limit=200, offset=offset)
                except FloppyError:
                    break
                rows = (payload or {}).get("results") or []
                for row in rows:
                    item = row.get("item") or {}
                    status[(kind, item.get("source"), str(item.get("media_id")))] = row.get("status")
                if not rows or not categories._has_more(payload):
                    break
                offset += len(rows)
        for entry in entries:
            kind = "movie" if entry["kind"] == "movie" else "tv"
            key = (kind, entry.get("source"), str(entry.get("media_id")))
            if key in status:
                entry["status"] = status[key]
                if status[key] == model.STATUS_COMPLETED:
                    entry["playcount"] = 1

    # -- playback -------------------------------------------------------------

    def play(self):
        p = self.params
        entry = {
            "kind": p.get("kind", "movie"),
            "tmdb": p.get("tmdb", ""),
            "imdb": p.get("imdb", ""),
            "tvdb": p.get("tvdb", ""),
            "title": p.get("title", ""),
            "show_title": p.get("show", ""),
            "year": p.get("year", ""),
            "premiered": p.get("premiered", ""),
            "poster": p.get("poster", ""),
            "thumb": p.get("thumb", ""),
            "show_imdb": p.get("show_imdb", ""),
        }
        if entry["kind"] == "episode":
            try:
                entry["season"] = int(p.get("season"))
                entry["episode"] = int(p.get("episode"))
            except (TypeError, ValueError):
                common.notify("This episode has no season/episode number")
                return
        if not model.playable(entry):
            common.notify("No TMDb, IMDb or TVDb id for this item")
            return
        url = listing.player_url(entry)
        if not url:
            common.notify("Choose a player in Floppy settings > Playback")
            return
        # A known position (resume lists) or 0 for "from the start"; left empty, the
        # service looks the position up when the video starts.
        resume = "0" if p.get("noresume") == "1" else str(int(float(p.get("resume") or 0)) or "")
        common.set_play_handoff(
            kind=entry["kind"],
            tmdb=entry["tmdb"],
            imdb=entry["imdb"],
            tvdb=entry["tvdb"],
            season=entry.get("season"),
            episode=entry.get("episode"),
            title=entry.get("show_title") or entry["title"],
            resume=resume,
        )
        common.log("Handing playback to {}".format(url))
        # Player files marked is_resolvable=false start the video themselves.
        builtin = "PlayMedia" if listing.player_resolvable(entry) else "RunPlugin"
        xbmc.executebuiltin('{}("{}")'.format(builtin, url))

    # -- actions --------------------------------------------------------------

    def _after_change(self, message):
        # The service refreshes the widget lists, then reloads them (see refresher.py).
        common.mark_data_changed()
        common.notify(message)
        xbmc.executebuiltin("Container.Refresh")

    def mark_watched(self):
        p = self.params
        source = p.get("source") or "tmdb"
        media_id = p.get("media_id") or p.get("tmdb")
        try:
            if p.get("kind") == "movie":
                self.api.watch_movie(source, media_id)
            else:
                self.api.watch_episode(source, media_id, p.get("season"), p.get("episode"),
                        lmt=p.get("lmt") or None)
        except FloppyError as exc:
            common.notify("Could not mark as watched: {}".format(exc))
            return
        self._clear_resume_quietly()
        self._after_change("Marked as watched")

    def _resume_body(self):
        p = self.params
        ids = {k: p.get(k) for k in ("tmdb", "imdb", "tvdb") if p.get(k)}
        if p.get("kind") == "episode":
            # tmdb here is the show's id; imdb/tvdb on episodes may be episode-level,
            # which Floppy also resolves to the show.
            body = {"media_type": "episode", "ids": ids,
                    "season_number": int(p.get("season")), "episode_number": int(p.get("episode"))}
        else:
            body = {"media_type": "movie", "ids": ids}
        return body

    def _clear_resume_quietly(self):
        try:
            self.api.delete_progress(self._resume_body())
        except (FloppyError, TypeError, ValueError):
            pass

    def clear_resume(self):
        try:
            self.api.delete_progress(self._resume_body())
        except FloppyError as exc:
            if exc.status != 404:
                common.notify("Could not remove: {}".format(exc))
                return
        self._after_change("Removed from Continue Watching")

    def add_watchlist(self):
        try:
            self.api.add_to_watchlist(self.params.get("media_type"), "tmdb", self.params.get("tmdb"))
        except FloppyError as exc:
            common.notify("Could not add: {}".format(exc))
            return
        self._after_change("Added to your Floppy watchlist")

    def remove_watchlist(self):
        if not xbmcgui.Dialog().yesno(common.ADDON_NAME,
                                      "Remove this from your Floppy watchlist?"):
            return
        # Delete only the Planning entries: untracking would also wipe any earlier watch history.
        media_type = self.params.get("media_type")
        source = self.params.get("source") or "tmdb"
        media_id = self.params.get("media_id")
        lmt = self.params.get("lmt") or None
        try:
            payload = self.api.consumptions(media_type, source, media_id, lmt=lmt)
            planning = [row["consumption_id"] for row in (payload or {}).get("results") or []
                        if row.get("status") == model.STATUS_PLANNING]
            for consumption_id in planning:
                self.api.delete_consumption(media_type, source, media_id, consumption_id, lmt=lmt)
        except FloppyError as exc:
            common.notify("Could not remove: {}".format(exc))
            return
        self._after_change("Removed from your Floppy watchlist")

    def remove_from_floppy(self):
        p = self.params
        title = p.get("title") or "this title"
        if not xbmcgui.Dialog().yesno(
            common.ADDON_NAME,
            "Remove {} from Floppy?\n\nThis deletes its status, rating and watch history "
            "in Floppy and cannot be undone.".format(title),
            nolabel="Cancel",
            yeslabel="Remove",
        ):
            return
        try:
            self.api.untrack(p.get("media_type"), p.get("source") or "tmdb", p.get("media_id"),
                    lmt=p.get("lmt") or None)
        except FloppyError as exc:
            if exc.status == 404:
                common.notify("{} is not in your Floppy library".format(title))
            else:
                common.notify("Could not remove: {}".format(exc))
            return
        self._after_change("Removed {} from Floppy".format(title))

    def refresh(self):
        self.api.invalidate()
        common.bump_widget_reload()
        common.notify("Widgets will reload")
        xbmc.executebuiltin("Container.Refresh")

    def clear_cache(self):
        cache.clear_all()
        common.bump_widget_reload()
        common.notify("Cache cleared")

    def test(self):
        if not self.api.configured:
            common.notify("Set your Floppy address and API token first")
            return
        try:
            info = self.api.info() or {}
            self.api.media("movie", limit=1)
        except FloppyError as exc:
            if exc.status in (401, 403):
                message = "Floppy answered but refused the API token."
            else:
                message = str(exc)
            xbmcgui.Dialog().ok(common.ADDON_NAME, message)
            return
        version = info.get("version") or info.get("app_version") or ""
        art = "TMDb artwork: on" if tmdb.enabled() else "TMDb artwork: off (no key)"
        xbmcgui.Dialog().ok(common.ADDON_NAME, "Connected to Floppy {}\n{}".format(version, art).strip())

    def widget_paths(self):
        lines = ["Add any of these as a widget source. To refresh automatically, add",
                 "&reload=$INFO[Window(Home).Property({})]".format(common.PROP_RELOAD),
                 "to the end of the path.", ""]
        sections = (("All Videos", categories.ALL_MENU), ("Mixed", ["continue_watching"]), ("Movies", categories.MOVIE_MENU),
                    ("TV", categories.TV_MENU))
        for title, keys in sections:
            lines.append("[B]{}[/B]".format(title))
            for key in keys:
                label = categories.CATEGORIES[key][0]
                lines.append("{}: {}".format(label, common.plugin_url(action="list", cat=key)))
            lines.append("")
        xbmcgui.Dialog().textviewer("Floppy widget paths", "\n".join(lines))
    
    # shows is imported only by the routes that use it, to keep widget start-up light.

    def seasons(self):
        from . import shows
        shows.list_seasons(self)

    def episodes(self):
        from . import shows
        shows.list_episodes(self)

    def mark_season_watched(self):
        from . import shows
        shows.mark_season_watched(self)

    def mark_show_watched(self):
        from . import shows
        shows.mark_show_watched(self)

    def unwatch(self):
        from . import shows
        shows.unwatch(self)
    
    def settings(self):
        common.addon().openSettings()

    def pick_play_path(self):
        from . import pathpicker
        pathpicker.pick(self.params.get("kind", "movie"))

    def noop(self):
        if self.params.get("reason") == "no_tmdb":
            common.notify("This show has no TMDb id in Floppy")


def run(argv=None):
    argv = argv or sys.argv
    common.freeze_settings()
    router = Router(argv)
    perf.mark("init")
    action = router.params.get("action", "root")
    handler = getattr(router, action, None)
    if handler is None or action.startswith("_"):
        common.log("Unknown action {}".format(action), xbmc.LOGWARNING)
        router._finish([], succeeded=False)
        return
    handler()
    if common.setting_bool("debug"):
        detail = router.params.get("cat") or router.params.get("row_id") or ""
        common.log(perf.summary("{} {}".format(action, detail).strip()), xbmc.LOGINFO)
