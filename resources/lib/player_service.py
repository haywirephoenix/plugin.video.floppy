"""Background service: offers Floppy resume points, saves positions back and scrobbles.

With "Send watch history to Floppy" on, plays go through Floppy's scrobble API and
TMDb Helper's own Floppy scrobbling stands down so nothing is logged twice. With it
off, only resume positions are saved, which never create a play.
"""

import threading
import time
import queue
import uuid

import xbmc
import xbmcgui

from . import cache, common, model
from .api import FloppyAPI, FloppyError
from .refresher import Refresher

PENDING_MAX_AGE = 180  # seconds between the floppy.play.* hand-off and the video starting
MIN_POSITION = 60  # do not save accidental starts
PROP_TMDBHELPER_PLAYING = "TMDbHelper.PlayerInfoString"  # set by TMDb Helper's player

def completed_ratio():
        """Watched threshold from settings (default 80%)."""
        return max(50, min(100, common.setting_int("watched_percent", 80))) / 100.0

def _fmt(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, secs) if hours else "{}:{:02d}".format(minutes, secs)


class Playing:
    """What is playing, expressed in Floppy's playback/progress vocabulary."""

    def __init__(self, kind, ids, season=None, episode=None, title="", resume=None):
        self.kind = kind
        self.ids = {k: str(v) for k, v in ids.items() if v}
        self.season = season
        self.episode = episode
        self.title = title
        self.decided = False  # resume chosen before the play: no question when it starts
        self.resume = resume  # seconds; None = look it up in Floppy when the video starts
        self.position = 0.0
        self.total = 0.0
        self.last_saved = time.time()
        self.session = uuid.uuid4().hex

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
        self._handoff_seen = (None, 0.0)  # (floppy.play.* values, when first seen)
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def shutdown(self, timeout=3):
        """Stop the send worker; Kodi waits on every Python thread, daemon or not, before exiting."""
        self._queue.put(None)
        self._thread.join(timeout)

    # -- identify what started ---------------------------------------------------

    def _watch_handoff(self):
        """Note when floppy.play.* appears, and drop it once too old to belong to a new video."""
        values = common.read_play_handoff()
        seen, since = self._handoff_seen
        if not values:
            self._handoff_seen = (None, 0.0)
        elif values != seen:
            self._handoff_seen = (values, time.time())
        elif time.time() - since > PENDING_MAX_AGE:
            common.log("Dropping a play hand-off that never started: {}".format(values))
            common.clear_play_handoff()
            self._handoff_seen = (None, 0.0)

    def _from_handoff(self):
        values = common.read_play_handoff()
        common.clear_play_handoff()
        seen, since = self._handoff_seen
        self._handoff_seen = (None, 0.0)
        if not values or (values == seen and time.time() - since > PENDING_MAX_AGE):
            return None
        kind = values.get("kind")
        if kind not in ("movie", "episode"):
            return None
        ids = {"tmdb": values.get("tmdb"), "imdb": values.get("imdb"), "tvdb": values.get("tvdb")}
        if not any(ids.values()):
            return None
        season = episode = None
        if kind == "episode":
            try:
                season, episode = int(values["season"]), int(values["episode"])
            except (KeyError, ValueError):
                return None
        # resume: chosen before the play (skin.ultra's Resume / Play from beginning): "auto" for
        # the saved position, or seconds ("0" from the beginning); not asked again
        decided = "resume" in values
        try:
            resume = None if values.get("resume", "auto") == "auto" else int(float(values["resume"]))
        except ValueError:
            resume = None
        playing = Playing(kind, ids, season, episode, values.get("title") or "", resume)
        playing.decided = decided
        return playing

    @staticmethod
    def _from_tmdbhelper(kind, season=None, episode=None, tag_ids=None):
        """Exact ids for playback started by TMDb Helper's player, if it is what is playing.

        TMDb Helper keeps its last played item in a Home window property; episodes carry
        the show's ids, which is what Floppy expects. The property is not cleared after
        playback, so it is only used when it matches what is playing now.
        """
        info = common.get_json_property(PROP_TMDBHELPER_PLAYING) or {}
        if not info.get("tmdb_id"):
            return {}
        if kind == "movie" and info.get("tmdb_type") != "movie":
            return {}
        if kind == "movie" and any(
            value and info.get(key) and str(info[key]) != str(value)
            for key, value in (("tmdb_id", (tag_ids or {}).get("tmdb")), ("imdb_id", (tag_ids or {}).get("imdb")))
        ):
            return {}  # left over from an earlier TMDb Helper play
        if kind == "episode" and (
            info.get("tmdb_type") not in ("episode", "tv")
            or info.get("season") != season
            or info.get("episode") != episode
        ):
            return {}
        return {"tmdb": info.get("tmdb_id"), "imdb": info.get("imdb_id"), "tvdb": info.get("tvdb_id")}

    def _from_player(self):
        try:
            tag = self.getVideoInfoTag()
        except RuntimeError:
            return None
        media_type = tag.getMediaType()
        if media_type == "movie":
            tag_ids = {"tmdb": tag.getUniqueID("tmdb"), "imdb": tag.getUniqueID("imdb") or tag.getIMDBNumber(),
                       "tvdb": tag.getUniqueID("tvdb")}
            ids = self._from_tmdbhelper("movie", tag_ids=tag_ids) or tag_ids
            playing = Playing("movie", ids, title=tag.getTitle())
        elif media_type == "episode":
            season, episode = tag.getSeason(), tag.getEpisode()
            if season < 0 or episode < 0:
                return None
            # A playing episode's tmdb uniqueid may be the episode's own id, which
            # Floppy would read as a show id. IMDb/TVDb ids are safe either way.
            ids = self._from_tmdbhelper("episode", season, episode) or {
                "imdb": tag.getUniqueID("imdb") or tag.getIMDBNumber(),
                "tvdb": tag.getUniqueID("tvdb")}
            playing = Playing("episode", ids, season, episode, tag.getTVShowTitle())
        else:
            return None
        return playing if playing.ids else None
    
    # -- callbacks -----------------------------------------------------------------

    def onAVStarted(self):
        if not self.isPlayingVideo():
            return
        if common.background_trailer():
            # Not tracked, and a pending floppy.play.* hand-off stays for the real video.
            with self._lock:
                self.current = None
            return
        playing = self._from_handoff() or self._from_player()
        with self._lock:
            self.current = playing
        if not playing:
            return
        common.log("Tracking position for {} {}".format(playing.kind, playing.ids))
        self._maybe_resume(playing)
        if self._scrobbling():
            try:
                playing.position = self.getTime()
                playing.total = self.getTotalTime() or playing.total
            except RuntimeError:
                pass
            self._dispatch(playing, "start")

    def onPlayBackPaused(self):
        self._save(final=False)

    def onPlayBackStopped(self):
        if common.background_trailer():
            return
        self._save(final=True)

    def onPlayBackEnded(self):
        if common.background_trailer():
            return
        with self._lock:
            if self.current and self.current.total:
                self.current.position = self.current.total
        self._save(final=True, ended=True)

    def onPlayBackError(self):
        with self._lock:
            self.current = None

    # -- resume -------------------------------------------------------------------

    @staticmethod
    def _find_resume(playing):
        """Floppy's saved position for what is playing, matched by its ids."""
        api = FloppyAPI()
        if not api.configured:
            return 0
        media_type = "movie" if playing.kind == "movie" else "episode"
        try:
            payload = api.playback_progress([media_type], completed=False, limit=100)
        except FloppyError:
            return 0
        # Episode rows carry the show's ids, so only show-level ids are compared for them.
        keys = ("tmdb", "imdb") if playing.kind == "movie" else ("tmdb", "tvdb")
        for row in (payload or {}).get("results") or []:
            candidate = model.from_progress(row)
            if not candidate or not any(
                playing.ids.get(k) and candidate.get(k) == playing.ids[k] for k in keys
            ):
                continue
            if playing.kind == "episode" and (
                candidate.get("season") != playing.season
                or candidate.get("episode") != playing.episode
            ):
                continue
            return int(candidate.get("resume_pos") or 0)
        return 0

    def _maybe_resume(self, playing):
        mode = common.setting_int("resume_mode", 1)
        if mode == 0 and not playing.decided:
            return
        if playing.resume is None:
            playing.resume = self._find_resume(playing)
        if playing.resume < MIN_POSITION:
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
        if mode == 1 and not playing.decided:
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
        if common.background_trailer():
            return
        self._watch_handoff()
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
            self._save(final=False, periodic=True)


    def _save(self, final, ended=False, periodic=False):
        with self._lock:
            playing = self.current
            if final:
                self.current = None
        if not playing:
            return
        playing.last_saved = time.time()
        completed = ended or bool(
            playing.total and playing.position >= playing.total * completed_ratio())

        if self._scrobbling() and not periodic:
            if final:
                self._dispatch(playing, "stop", completed=completed, final=True)
                return
            # A scrobbled pause only updates Now Playing, so also save the position below.
            self._dispatch(playing, "pause")

        if not common.setting_bool("save_progress", True):
            return
        if not completed and playing.position < MIN_POSITION:
            return
        body = playing.body(completed=completed)
        show_title = playing.title if playing.kind == "episode" else ""
        self._queue.put((self._send, (body, final, show_title)))

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
            common.mark_data_changed()

    # -- scrobble -------------------------------------------------------------------
    
    def _worker(self):
        while True:
            job = self._queue.get()
            if job is None:
                return
            fn, args = job
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001 - never let the worker die
                common.log("Floppy send failed: {}".format(exc), xbmc.LOGWARNING)

    @staticmethod
    def _scrobbling():
        return common.setting_bool("scrobble", False)

    def _dispatch(self, playing, action, completed=None, final=False):
        body = playing.body(completed=bool(completed))
        body["action"] = action
        if completed is None:
            body.pop("completed", None)
        if action == "stop":
            body["client_event_id"] = "kodi-{}-stop".format(playing.session)
        show_title = playing.title if playing.kind == "episode" else ""
        self._queue.put((self._send_scrobble, (body, final, show_title)))

    @classmethod
    def _send_scrobble(cls, body, final, show_title=""):
        api = FloppyAPI()
        if not api.configured:
            return
        if body["media_type"] == "episode" and not body["ids"].get("tmdb"):
            tmdb_id = cls._show_tmdb_from_title(api, show_title)
            if tmdb_id:
                body["ids"]["tmdb"] = tmdb_id
        try:
            api.scrobble(body)
            common.log("Scrobbled {} {}s completed={} for {}".format(
                body["action"], body.get("position_seconds"), body.get("completed"), body["ids"]))
        except FloppyError as exc:
            common.log("Scrobble {} failed: {}".format(body["action"], exc), xbmc.LOGWARNING)
            return
        if final:
            common.mark_data_changed()

    def onPlayBackResumed(self):
        with self._lock:
            playing = self.current
        if playing and self._scrobbling():
            self._dispatch(playing, "start")

def run():
    monitor = xbmc.Monitor()
    player = FloppyPlayer()
    widgets = Refresher()
    widgets.start()
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
    widgets.shutdown()
    player.shutdown()
    common.log("Service stopped", xbmc.LOGINFO)
