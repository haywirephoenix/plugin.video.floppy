"""Tests for action=genre and tmdb.discover, with Kodi and TMDb stubbed: python -m unittest discover tests"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for name in ("xbmc", "xbmcaddon", "xbmcgui", "xbmcplugin", "xbmcvfs"):
    sys.modules.setdefault(name, mock.MagicMock())

from resources.lib import router, tmdb  # noqa: E402

GENRES = {
    "genre/movie/list": [{"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"},
                         {"id": 35, "name": "Comedy"}, {"id": 27, "name": "Horror"},
                         {"id": 16, "name": "Animation"}],
    "genre/tv/list": [{"id": 10759, "name": "Action & Adventure"}, {"id": 35, "name": "Comedy"},
                      {"id": 10764, "name": "Reality"}, {"id": 16, "name": "Animation"}],
}


class FakeTMDb:
    """Stands in for tmdb._get; answers genre lists and discover pages, recording discover calls."""

    def __init__(self, per_page=20, pages=3):
        self.per_page = per_page
        self.pages = pages
        self.calls = []

    def __call__(self, path, params):
        if path in GENRES:
            return {"genres": GENRES[path]}
        kind = path.split("/")[1]
        self.calls.append((kind, dict(params)))
        page = params["page"]
        base = (1000 if kind == "movie" else 2000) + (page - 1) * self.per_page
        results = []
        for n in range(base, base + self.per_page):
            row = {"id": n, "overview": "", "poster_path": "/p.jpg", "vote_average": 7}
            row.update({"title": "Movie {}".format(n), "release_date": "2020-01-01"} if kind == "movie"
                       else {"name": "Show {}".format(n), "first_air_date": "2019-05-01"})
            results.append(row)
        results[0]["adult"] = page == 1 and kind == "movie"
        return {"results": results, "total_pages": self.pages}


class GenreTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTMDb()
        store = {}
        patches = [
            mock.patch.object(tmdb, "_get", self.fake),
            mock.patch.object(tmdb, "_key", lambda: "k" * 32),
            mock.patch.object(tmdb, "_language", lambda: "en-GB"),
            mock.patch.object(tmdb.cache, "get", lambda key, *a, **k: store.get(key)),
            mock.patch.object(tmdb.cache, "set", lambda key, value, ttl: store.__setitem__(key, value)),
            mock.patch.object(router.Router, "_render_entries", self._capture),
            mock.patch.object(router.Router, "_finish", self._finished),
            mock.patch.object(router.listing, "is_widget_context", lambda: False),
            mock.patch.object(router.common, "notify", lambda *a, **k: None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.entries = None

    def _capture(self, entries, has_more, content, in_resume, next_params):
        self.entries, self.content = entries, content
        self.has_more, self.next_params = has_more, next_params

    def _finished(self, items, *a, **k):
        self.entries = items

    def run_genre(self, query, action="genre"):
        r = router.Router(["plugin://plugin.video.floppy/", "1", "?action={}&widget=1&{}".format(action, query)])
        getattr(r, action)()
        return self.entries

    def test_both_alternates_and_limits(self):
        entries = self.run_genre("limit=30&media_type=both&genres=Comedy")
        self.assertEqual(len(entries), 30)
        self.assertEqual([e["kind"] for e in entries[:4]], ["movie", "tvshow", "movie", "tvshow"])
        self.assertEqual(self.content, "videos")
        self.assertNotIn("1000", [e["tmdb"] for e in entries])  # the adult movie
        movie_call = next(p for k, p in self.fake.calls if k == "movie")
        self.assertEqual(movie_call["with_genres"], "35")
        self.assertEqual(movie_call["sort_by"], "popularity.desc")
        self.assertEqual(movie_call["vote_count.gte"], tmdb.MIN_VOTES)
        self.assertEqual(movie_call["include_adult"], "false")

    def test_names_map_per_type_and_or(self):
        self.run_genre("limit=10&genres=Action%20%2F%20Adventure%20%2F%20Action%20%26%20Adventure")
        withs = {k: p["with_genres"] for k, p in self.fake.calls}
        self.assertEqual(withs, {"movie": "12|28", "tv": "10759"})
        tv_call = next(p for k, p in self.fake.calls if k == "tv")
        self.assertEqual(tv_call["without_genres"], "10763,10767")

    def test_type_without_matching_genre_is_skipped(self):
        entries = self.run_genre("limit=10&genres=Reality")
        self.assertEqual({k for k, _ in self.fake.calls}, {"tv"})
        self.assertEqual({e["kind"] for e in entries}, {"tvshow"})
        self.run_genre("limit=10&genres=Nope")
        self.assertEqual(self.entries, [])

    def test_language_and_keywords(self):
        self.run_genre("limit=10&genres=Animation&language=ja")
        self.assertTrue(all(p["with_original_language"] == "ja" and p["with_genres"] == "16"
                            for _, p in self.fake.calls))
        self.fake.calls.clear()
        self.run_genre("limit=10&keywords=6075")
        self.assertEqual({k for k, _ in self.fake.calls}, {"movie", "tv"})
        self.assertTrue(all(p["with_keywords"] == "6075" and "with_genres" not in p
                            for _, p in self.fake.calls))

    def test_pages_until_limit_and_cached(self):
        self.run_genre("limit=30&media_type=movie&genres=Comedy")
        self.assertEqual([p["page"] for _, p in self.fake.calls], [1, 2])
        self.assertEqual(len(self.entries), 30)
        self.fake.calls.clear()
        self.run_genre("limit=30&media_type=movie&genres=Comedy")
        self.assertEqual(self.fake.calls, [])

    def test_next_pages_continue_the_list(self):
        query = "limit=30&media_type=both&genres=Comedy"
        first = self.run_genre(query)
        self.assertTrue(self.has_more)
        self.assertNotIn("page", self.next_params)
        second = self.run_genre(query + "&page=1")
        third = self.run_genre(query + "&page=2")
        ids = [(e["kind"], e["tmdb"]) for e in first + second + third]
        self.assertEqual(len(ids), 90)
        self.assertEqual(len(set(ids)), 90)
        # The fake has 3 pages of 20 per type (one adult movie dropped): 119 in all.
        self.run_genre(query + "&page=3")
        self.assertEqual(len(self.entries), 29)
        self.assertFalse(self.has_more)

    def test_genres_menu(self):
        items = self.run_genre("", action="genres")
        urls = [url for url, _, _ in items]
        # The fake genre lists have no Documentary, Drama, Music...: those categories are left out.
        self.assertEqual(len(urls), 6)
        self.assertFalse(any("Documentary" in url for url in urls))
        self.assertIn("plugin://plugin.video.floppy/?action=genre&media_type=both&genres=Comedy", urls)
        self.assertIn("plugin://plugin.video.floppy/?action=genre&media_type=both&genres=Animation&language=ja",
                      urls)
        movie_urls = [url for url, _, _ in self.run_genre("media_type=movie", action="genres")]
        self.assertFalse(any("Reality" in url for url in movie_urls))
        self.assertTrue(any("keywords=6075" in url for url in movie_urls))

    def test_no_key_is_empty(self):
        with mock.patch.object(tmdb, "_key", lambda: ""):
            self.assertEqual(self.run_genre("genres=Comedy"), [])
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
