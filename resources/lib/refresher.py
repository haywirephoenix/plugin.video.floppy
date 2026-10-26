"""Service side of the widget cache: keeps the lists widgets use fresh, then reloads them.

Widgets show whatever is cached, however old (see FloppyAPI.serve_stale), and record which
Floppy requests they made. Every few seconds this refreshes those requests when Floppy data
has changed since, or (with "Refresh widgets automatically" on) when they have expired,
fetches artwork widgets did not wait for, and
changes the widget reload token when anything new arrived so Kodi fetches the widgets
again, this time straight from the cache.
"""

import threading
import time

import xbmc

from . import cache, categories, common, tmdb
from .api import FloppyAPI, FloppyError

CHECK_EVERY = 2  # seconds
RETRY_AFTER = 60  # seconds before a request that failed is tried again
KEY_MAX_AGE = 3 * 24 * 3600  # lists no widget has asked for in this long are left alone


class Refresher:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def shutdown(self, timeout=3):
        self._stop.set()
        self._thread.join(timeout)

    def _run(self):
        while not self._stop.wait(CHECK_EVERY):
            try:
                self.cycle()
            except Exception as exc:  # noqa: BLE001 - never let the refresher die
                common.log("Widget refresh failed: {}".format(exc), xbmc.LOGWARNING)

    def cycle(self):
        # Leave the network to the video while one is playing; finishing it marks data changed.
        if xbmc.getCondVisibility("Player.HasVideo") or common.background_trailer():
            return
        changed = self._refresh_lists()
        if tmdb.fetch_pending(self._stop):
            changed = True
        if changed and not self._stop.is_set():
            common.log("Widget data refreshed; reloading widgets")
            common.bump_widget_reload(data_changed=False)

    def _refresh_lists(self):
        now = time.time()
        not_before = common.data_changed_time()
        # With automatic refresh off, only a change to Floppy data (or a missing entry) makes a list due.
        auto = categories.auto_refresh()
        due = [
            (key, path, params, ttl if auto else categories.KEEP_UNTIL_CHANGED)
            for key, path, params, ttl, last_try, stored, expires in cache.widget_keys(now - KEY_MAX_AGE)
            if (stored is None or (auto and expires < now) or stored < not_before)
            and last_try < now - RETRY_AFTER
        ]
        if not due:
            return False
        api = FloppyAPI()
        if not api.configured:
            return False
        changed = False
        for key, path, params, ttl in due:
            if self._stop.is_set():
                break
            try:
                started = time.time()
                if api.refresh(key, path, params, ttl):
                    changed = True
                common.log("Refreshed {} in {:.0f} ms".format(path, (time.time() - started) * 1000))
            except FloppyError as exc:
                cache.mark_tried(key)
                common.log("Could not refresh {}: {}".format(path, exc), xbmc.LOGWARNING)
        return changed
