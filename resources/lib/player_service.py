"""Background service: offers Floppy resume points and saves positions back.

Watch history is left to your scrobbler (Floppy's Kodi webhook via the HTTP
Scrobbler add-on). This only stores where you stopped, which Floppy keeps
separately from history, so nothing is ever logged twice.
"""

import threading
import time

import xbmc
import xbmcgui

from . import cache, common
from .api import FloppyAPI, FloppyError

PENDING_MAX_AGE = 180  # seconds between pressing play and the video starting
MIN_POSITION = 60  # do not save accidental starts
COMPLETED_RATIO = 0.90


def _fmt(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, secs) if hours else "{}:{:02d}".format(minutes, secs)


class Playing:
    """What is playing, expressed in Floppy's playback/progress vocabulary."""

    def __init__(self, kind, ids, season=None, episode=None, title="", resume=0):
        self.kind = kind
        self.ids = {k: str(v) for k, v in ids.items() if v}
        self.season = season
        self.episode = episode
        self.title = title
        self.resume = resume
        self.position = 0.0
        self.total = 0.0
        self.last_saved = time.time()

    def body(self, completed=False):
        body = {
            "media_type": "movie" if self.kind == "movie" else "episode",
            "ids": self.ids,
            "position_seconds": int(self.position),
            "completed": bool(completed),
        }
        if self.total:
            body["duration_seconds"] = int(self.total)
        if self.kind == "episode":
            body["season_number"] = int(self.season)
            body["episode_number"] = int(self.episode)
        return body


class FloppyPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.current = None
        self._lock = threading.Lock()

    # -- identify what started ---------------------------------------------------

    def _from_pending(self):
        pending = common.get_json_property(common.PROP_PENDING_PLAY)
        common.clear_home_property(common.PROP_PENDING_PLAY)
        if not pending or time.time() - pending.get("set_at", 0) > PENDING_MAX_AGE:
            return None
        kind = pending.get("kind")
        if kind not in ("movie", "episode"):
            return None
        ids = {"tmdb": pending.get("tmdb"), "imdb": pending.get("imdb"), "tvdb": pending.get("tvdb")}
        if kind == "episode" and (pending.get("season") is None or pending.get("episode") is None):
            return None
        return Playing(kind, ids, pending.get("season"), pending.get("episode"),
                       pending.get("title") or "", int(pending.get("resume") or 0))

    def _from_player(self):
        try:
            tag = self.getVideoInfoTag()
        except RuntimeError:
            return None
        media_type = tag.getMediaType()
        if media_type == "movie":
            ids = {"tmdb": tag.getUniqueID("tmdb"), "imdb": tag.getUniqueID("imdb") or tag.getIMDBNumber(),
                   "tvdb": tag.getUniqueID("tvdb")}
            playing = Playing("movie", ids, title=tag.getTitle())
        elif media_type == "episode":
            season, episode = tag.getSeason(), tag.getEpisode()
            if season < 0 or episode < 0:
                return None
            # A playing episode's tmdb uniqueid may be the episode's own id, which
            # Floppy would read as a show id. IMDb/TVDb ids are safe either way.
            ids = {"imdb": tag.getUniqueID("imdb") or tag.getIMDBNumber(),
                   "tvdb": tag.getUniqueID("tvdb")}
            playing = Playing("episode", ids, season, episode, tag.getTVShowTitle())
        else:
            return None
        return playing if playing.ids else None

    # -- callbacks -----------------------------------------------------------------

    def onAVStarted(self):
        if not self.isPlayingVideo():
            return
        playing = self._from_pending() or self._from_player()
        with self._lock:
            self.current = playing
        if not playing:
            return
        common.log("Tracking position for {} {}".format(playing.kind, playing.ids))
        self._maybe_resume(playing)

    def onPlayBackPaused(self):
        self._save(final=False)

    def onPlayBackStopped(self):
        self._save(final=True)

    def onPlayBackEnded(self):
        with self._lock:
            if self.current and self.current.total:
                self.current.position = self.current.total
        self._save(final=True, ended=True)

    def onPlayBackError(self):
        with self._lock:
            self.current = None

    # -- resume -------------------------------------------------------------------

    def _maybe_resume(self, playing):
        mode = common.setting_int("resume_mode", 1)
        if mode == 0 or playing.resume < MIN_POSITION:
            return
        # Give the player add-on a moment; if it already resumed, leave it alone.
        xbmc.sleep(1000)
        try:
            if self.getTime() > 30:
                return
            total = self.getTotalTime()
        except RuntimeError:
            return
        if total and playing.resume >= total * 0.95:
            return
        if mode == 1:
            self.pause()
            choice = xbmcgui.Dialog().contextmenu(
                ["Resume from {}".format(_fmt(playing.resume)), "Play from the start"])
            self.pause()
            if choice != 0:
                return
        try:
            self.seekTime(float(playing.resume))
        except RuntimeError:
            pass

    # -- saving -------------------------------------------------------------------

    def tick(self):
        """Called about once a second by the service loop."""
        with self._lock:
            playing = self.current
        if not playing or not self.isPlayingVideo():
            return
        try:
            playing.position = self.getTime()
            playing.total = self.getTotalTime() or playing.total
        except RuntimeError:
            return
        interval = max(30, common.setting_int("progress_interval", 120))
        if time.time() - playing.last_saved >= interval:
            self._save(final=False)

    def _save(self, final, ended=False):
        with self._lock:
            playing = self.current
            if final:
                self.current = None
        if not playing or not common.setting_bool("save_progress", True):
            return
        playing.last_saved = time.time()
        completed = ended or bool(
            playing.total and playing.position >= playing.total * COMPLETED_RATIO)
        if not completed and playing.position < MIN_POSITION:
            return
        body = playing.body(completed=completed)
        show_title = playing.title if playing.kind == "episode" else ""
        threading.Thread(target=self._send, args=(body, final, show_title), daemon=True).start()

    @staticmethod
    def _show_tmdb_from_title(api, show_title):
        """Match a show you track in Floppy by title, to get its TMDb id."""
        wanted = show_title.strip().lower()
        if not wanted:
            return ""
        try:
            payload = api.media("tv", ttl=3600, search=show_title, limit=10)
        except FloppyError:
            return ""
        for row in (payload or {}).get("results") or []:
            item = row.get("item") or {}
            titles = {(item.get(k) or "").strip().lower() for k in ("title", "localized_title", "original_title")}
            if wanted in titles and item.get("source") == "tmdb":
                return str(item.get("media_id") or "")
        return ""

    @classmethod
    def _send(cls, body, final, show_title=""):
        api = FloppyAPI()
        if not api.configured:
            return
        if body["media_type"] == "episode" and not body["ids"].get("tmdb"):
            tmdb_id = cls._show_tmdb_from_title(api, show_title)
            if tmdb_id:
                body["ids"]["tmdb"] = tmdb_id
        try:
            api.put_progress(body)
            common.log("Saved position {}s (completed={}) for {}".format(
                body["position_seconds"], body["completed"], body["ids"]))
        except FloppyError as exc:
            common.log("Could not save position: {}".format(exc), xbmc.LOGWARNING)
            return
        if final:
            api.invalidate()
            common.bump_widget_reload()


def run():
    monitor = xbmc.Monitor()
    player = FloppyPlayer()
    common.log("Service started", xbmc.LOGINFO)
    last_purge = 0
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
        try:
            player.tick()
        except Exception as exc:  # noqa: BLE001 - never let the service die
            common.log("tick failed: {}".format(exc), xbmc.LOGWARNING)
        if time.time() - last_purge > 6 * 3600:
            last_purge = time.time()
            try:
                cache.purge_expired()
            except Exception:  # noqa: BLE001
                pass
    common.log("Service stopped", xbmc.LOGINFO)
