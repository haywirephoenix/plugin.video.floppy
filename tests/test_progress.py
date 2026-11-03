"""Tests for a show's watched progress: python -m unittest discover tests"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for name in ("xbmc", "xbmcaddon", "xbmcgui", "xbmcplugin", "xbmcvfs"):
    sys.modules.setdefault(name, mock.MagicMock())

from resources.lib import model  # noqa: E402


class WatchedPercentTest(unittest.TestCase):
    def test_watched_of_aired(self):
        self.assertEqual(model.watched_percent(3, 9), 25)
        self.assertEqual(model.watched_percent(5, 0), 100)

    def test_unknown(self):
        self.assertIsNone(model.watched_percent(2, None))
        self.assertIsNone(model.watched_percent(0, 0))

    def test_tracked_show_carries_its_count(self):
        entry = model.from_media({"item": {"media_type": "tv", "title": "Dark", "tmdb_id": 70523},
                                  "status": "In progress", "progress": 4, "episodes_left": 12})
        self.assertEqual((entry["episodes_watched"], entry["episodes_left"]), (4, 12))


class ShowBannerTest(unittest.TestCase):
    def test_from_the_next_episode(self):
        today = "2026-11-03"
        self.assertEqual(model.show_banner(0, "2027-01-05", "2027-01-05", today=today), "comingsoon")
        self.assertEqual(model.show_banner(3, "2026-10-30", "2026-10-30", today=today), "newepisodes")
        self.assertIsNone(model.show_banner(3, "2026-08-01", "2026-08-01", today=today))

    def test_tracked_show_carries_next_air(self):
        entry = model.from_media({"item": {"media_type": "tv", "title": "Dark", "tmdb_id": 70523},
                                  "status": "In progress", "progress": 4, "episodes_left": 0,
                                  "next_episode": {"season_number": 2, "episode_number": 1, "air_date": "2027-01-05T00:00:00Z"}})
        self.assertEqual(entry["next_air"], "2027-01-05")


if __name__ == "__main__":
    unittest.main()
