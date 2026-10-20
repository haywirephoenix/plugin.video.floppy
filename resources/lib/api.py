"""Thin client for Floppy's REST API (/api/v1)."""

import hashlib
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import cache, common

CACHE_PREFIX = "floppy:"


class FloppyError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class FloppyAPI:
    def __init__(self, base_url=None, token=None, timeout=None):
        self.base_url = (base_url or common.setting("base_url")).strip().rstrip("/")
        self.token = (token or common.setting("token")).strip()
        self.timeout = timeout or common.setting_int("timeout", 15)
        token_hash = hashlib.sha1(
            "{}|{}".format(self.base_url, self.token).encode("utf-8")
        ).hexdigest()[:10]
        self._cache_ns = "{}{}:".format(CACHE_PREFIX, token_hash)

    # -- plumbing -----------------------------------------------------------

    @property
    def configured(self):
        return bool(self.base_url and self.token)

    def _url(self, path, params=None):
        url = "{}/api/v1/{}".format(self.base_url, path.strip("/") + "/")
        if params:
            pairs = []
            for key, value in params.items():
                if value is None or value == "":
                    continue
                if isinstance(value, (list, tuple)):
                    pairs.extend((key, v) for v in value)
                else:
                    pairs.append((key, value))
            if pairs:
                url += "?" + urlencode(pairs)
        return url

    def request(self, method, path, params=None, body=None):
        if not self.configured:
            raise FloppyError("Floppy address or API token is not set")
        url = self._url(path, params)
        data = None
        headers = {
            "Authorization": "Bearer {}".format(self.token),
            "Accept": "application/json",
            "User-Agent": "plugin.video.floppy/1.0 (Kodi)",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        common.log("{} {}".format(method, url))
        context = ssl.create_default_context() if url.startswith("https") else None
        try:
            with urlopen(req, timeout=self.timeout, context=context) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
            except Exception:  # noqa: BLE001 - error body is best effort
                pass
            raise FloppyError(detail or "HTTP {}".format(exc.code), exc.code)
        except (URLError, OSError, ValueError) as exc:
            raise FloppyError("Could not reach Floppy: {}".format(exc))

    def get(self, path, params=None, ttl=0):
        key = self._cache_ns + path + "?" + json.dumps(params or {}, sort_keys=True)
        if ttl > 0:
            hit = cache.get(key)
            if hit is not None:
                return hit
        data = self.request("GET", path, params)
        if ttl > 0 and data is not None:
            cache.set(key, data, ttl)
        return data

    def invalidate(self):
        cache.delete_prefix(CACHE_PREFIX)

    # -- endpoints ----------------------------------------------------------

    def info(self):
        return self.request("GET", "info")
    
    def scrobble(self, body):
        return self.request("POST", "scrobble", body=body)

    def media(self, media_type, ttl=0, **params):
        return self.get("media/{}".format(media_type), params, ttl)

    def playback_progress(self, media_types, completed=False, limit=50, offset=0, ttl=0):
        params = {"media_type": ",".join(media_types), "limit": limit, "offset": offset}
        if completed is not None:
            params["completed"] = "true" if completed else "false"
        return self.get("playback/progress", params, ttl)

    def put_progress(self, body):
        return self.request("PUT", "playback/progress", body=body)

    def delete_progress(self, body):
        return self.request("DELETE", "playback/progress", body=body)

    def recommendations(self, media_type, limit=20, offset=0, ttl=0):
        params = {"media_type": media_type, "limit": limit, "offset": offset}
        return self.get("recommendations", params, ttl)

    def discover(self, media_type, show_more=False, ttl=0):
        params = {"media_type": media_type}
        if show_more:
            params["show_more"] = "1"
        return self.get("discover", params, ttl)

    def history(self, media_types, limit=20, offset=0, ttl=0):
        params = {"flat": "1", "media_type": ",".join(media_types), "limit": limit, "offset": offset}
        return self.get("history", params, ttl)

    def calendar(self, start_date, end_date, ttl=0):
        params = {"start_date": start_date, "end_date": end_date, "limit": 500}
        return self.get("calendar", params, ttl)

    def lists(self, ttl=0):
        return self.get("lists", {"limit": 200}, ttl)

    def list_items(self, list_id, limit=20, offset=0, ttl=0):
        return self.get("lists/{}/items".format(list_id), {"limit": limit, "offset": offset}, ttl)

    def home(self, limit=30, ttl=0):
        return self.get("home", {"limit": limit}, ttl)

    def watch_movie(self, source, media_id):
        return self.request("POST", "media/movie/{}/{}/watch".format(source, media_id), body={})

    def watch_episode(self, source, media_id, season, episode):
        path = "media/tv/{}/{}/{}/episodes/{}/watch".format(source, media_id, season, episode)
        return self.request("POST", path, body={})

    def add_to_watchlist(self, media_type, source, media_id):
        body = {"media_id": str(media_id), "source": source, "status": 0}
        return self.request("POST", "media/{}".format(media_type), body=body)

    def untrack(self, media_type, source, media_id, lmt=None):
        return self.request("DELETE", "media/{}/{}/{}".format(media_type, source, media_id),
                            params={"library_media_type": lmt})
    
    def show_detail(self, tmdb_id, lmt=None, ttl=0):
        return self.get("media/tv/tmdb/{}".format(tmdb_id), {"library_media_type": lmt}, ttl)

    def season_episodes(self, tmdb_id, season, lmt=None, ttl=0):
        return self.get("media/tv/tmdb/{}/{}/episodes".format(tmdb_id, season),
                        {"limit": 200, "library_media_type": lmt}, ttl)

    def watch_episode(self, source, media_id, season, episode, lmt=None):
        path = "media/tv/{}/{}/{}/episodes/{}/watch".format(source, media_id, season, episode)
        return self.request("POST", path, body={"library_media_type": lmt} if lmt else {})

    def unwatch_episode(self, source, media_id, season, episode, lmt=None):
        path = "media/tv/{}/{}/{}/episodes/{}/watch".format(source, media_id, season, episode)
        return self.request("DELETE", path, params={"library_media_type": lmt},
                            body={"library_media_type": lmt} if lmt else None)
    
    def search(self, media_type, query, limit=20, ttl=0):
        return self.get("search/{}".format(media_type), {"search": query, "limit": limit}, ttl)
