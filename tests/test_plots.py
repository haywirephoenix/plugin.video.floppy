"""Tests for Home rows' shorter plots: python -m unittest discover tests"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for name in ("xbmc", "xbmcaddon", "xbmcgui", "xbmcplugin", "xbmcvfs"):
    sys.modules.setdefault(name, mock.MagicMock())

from resources.lib import common, tmdb  # noqa: E402

PLOT = ("Dr. Smith moves to a quiet town. Nothing is as it seems. Her past catches up with her. "
        "Then the river floods.")


class ShortPlotTest(unittest.TestCase):
    def short(self, text, sentences=None):
        settings = {} if sentences is None else {"plot_short": sentences}
        with mock.patch.object(common, "setting_int", lambda key, default=0: settings.get(key, default)):
            return tmdb.short_plot(text)

    def test_three_sentences_by_default(self):
        # "Dr." isn't the end of a sentence.
        self.assertEqual(self.short(PLOT),
                         "Dr. Smith moves to a quiet town. Nothing is as it seems. Her past catches up with her.")

    def test_picked_length(self):
        self.assertEqual(self.short(PLOT, 1), "Dr. Smith moves to a quiet town.")

    def test_full_plot_setting(self):
        self.assertEqual(self.short(PLOT, 0), "")

    def test_nothing_when_already_short(self):
        self.assertEqual(self.short("One sentence only."), "")
        self.assertEqual(self.short(""), "")

    def test_character_limit(self):
        long = " ".join(["Sentence number {} goes on for quite a while indeed.".format(n) for n in range(10)])
        short = self.short(long, 3)
        self.assertLessEqual(len(short), tmdb.SHORT_PLOT_CHARS)
        self.assertTrue(short.endswith("."))


if __name__ == "__main__":
    unittest.main()
