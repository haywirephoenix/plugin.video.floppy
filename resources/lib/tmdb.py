"""Optional TMDb lookups for fanart, landscape art, clear logos and missing details."""

import json
import threading
from urllib.parse import urlencode

from . import cache, common, perf

API_HOST = "api.themoviedb.org"
IMG = "https://image.tmdb.org/t/p/"
TTL = 14 * 24 * 3600
MISS_TTL = 24 * 3600
SEARCH_TTL = 24 * 3600

# Errors a lookup can end with; callers treat them all as "no TMDb data".
# (http.client errors are turned into OSError in _get.)
LOOKUP_ERRORS = (OSError, ValueError)

# details() results for this plugin run, filled by prefetch so building items needs no more lookups.
_memo = {}
# One kept-alive HTTPS connection per thread: a new TLS handshake costs 0.2-1 s, sometimes far more.
_local = threading.local()


def _key():
    return common.setting("tmdb_key").strip()


def enabled():
    return bool(_key())


def _language():
    return common.setting("tmdb_language", "en-GB").strip() or "en-GB"


def _get(path, params):
    key = _key()
    headers = {"Accept": "application/json"}
    query = dict(params)
    # A v4 read access token is a long JWT; a v3 key is a 32 character hex string.
    if len(key) > 40 and "." in key:
        headers["Authorization"] = "Bearer {}".format(key)
    else:
        query["api_key"] = key
    url = "/3/{}?{}".format(path, urlencode(query))
    import http.client

    with perf.span("tmdb_http"):
        for attempt in (1, 2):
            conn = getattr(_local, "conn", None)
            if conn is None:
                conn = _local.conn = http.client.HTTPSConnection(API_HOST, timeout=10)
            try:
                conn.request("GET", url, headers=headers)
                resp = conn.getresponse()
                body = resp.read()
            except (OSError, http.client.HTTPException) as exc:
                conn.close()
                _local.conn = None
                # A kept-alive connection the server has since closed: retry once on a new one.
                if attempt == 2:
                    raise OSError(str(exc) or exc.__class__.__name__)
                continue
            if resp.status != 200:
                raise OSError("HTTP {}".format(resp.status))
            return json.loads(body.decode("utf-8"))


def _image(path, size):
    return "{}{}{}".format(IMG, size, path) if path else ""


def _pick_logo(logos, language):
    lang = language.split("-")[0]
    for wanted in (lang, "en", None):
        for logo in logos:
            if logo.get("iso_639_1") == wanted and logo.get("file_path"):
                return logo["file_path"]
    return logos[0]["file_path"] if logos else None


def _pick_landscape(backdrops, language):
    lang = language.split("-")[0]
    for wanted in (lang, "en"):
        for backdrop in backdrops:
            if backdrop.get("iso_639_1") == wanted and backdrop.get("file_path"):
                return backdrop["file_path"]
    return None


def _details_key(kind, tmdb_id, language):
    return "tmdb:{}:{}:{}".format("movie" if kind == "movie" else "tv", tmdb_id, language)


def details(kind, tmdb_id, fetch=True):
    """Return a compact details/artwork dict for a movie or TV show, cached.

    With ``fetch`` off, only what is already cached (or prefetched this run) is returned.
    """
    if not enabled() or not tmdb_id:
        return {}
    tmdb_type = "movie" if kind == "movie" else "tv"
    language = _language()
    cache_key = _details_key(kind, tmdb_id, language)
    if cache_key in _memo:
        return _memo[cache_key]
    hit = cache.get(cache_key)
    if hit is not None:
        return hit
    if not fetch:
        return {}
    lang = language.split("-")[0]
    try:
        data = _get(
            "{}/{}".format(tmdb_type, tmdb_id),
            {
                "language": language,
                "append_to_response": "images,external_ids",
                "include_image_language": "{},en,null".format(lang),
            },
        )
    except LOOKUP_ERRORS as exc:
        common.log("TMDb lookup failed for {} {}: {}".format(tmdb_type, tmdb_id, exc))
        cache.set(cache_key, {}, MISS_TTL)
        return {}

    images = data.get("images") or {}
    backdrops = images.get("backdrops") or []
    external = data.get("external_ids") or {}
    date = data.get("release_date") if tmdb_type == "movie" else data.get("first_air_date")
    runtime = data.get("runtime")
    if not runtime and data.get("episode_run_time"):
        runtime = data["episode_run_time"][0]
    result = {
        "title": data.get("title") or data.get("name") or "",
        "plot": data.get("overview") or "",
        "premiered": date or "",
        "rating": data.get("vote_average") or 0,
        "votes": data.get("vote_count") or 0,
        "genres": [g.get("name") for g in data.get("genres") or [] if g.get("name")],
        "runtime": int(runtime or 0) * 60,
        "studio": [c.get("name") for c in (data.get("production_companies") or data.get("networks") or [])[:2] if c.get("name")],
        "status": data.get("status") or "",
        "imdb": external.get("imdb_id") or data.get("imdb_id") or "",
        "tvdb": str(external.get("tvdb_id") or ""),
        "poster": _image(data.get("poster_path"), "w500"),
        "fanart": _image(data.get("backdrop_path"), "w1280"),
        "landscape": _image(_pick_landscape(backdrops, language), "w1280"),
        "clearlogo": _image(_pick_logo(images.get("logos") or [], language), "w500"),
        "seasons": data.get("number_of_seasons") or 0,
        "episodes": data.get("number_of_episodes") or 0,
    }
    cache.set(cache_key, result, TTL)
    return result


def prefetch(pairs, deadline=None):
    """Load details for (kind, tmdb_id) pairs: cached ones in one query, the rest in parallel.

    With a ``deadline`` (seconds), lookups not finished by then are left to the service,
    which fetches them and reloads the widgets; the items show Floppy's own poster meanwhile.
    """
    if not enabled():
        return
    language = _language()
    wanted = {_details_key(kind, tmdb_id, language): (kind, str(tmdb_id))
              for kind, tmdb_id in pairs if tmdb_id}
    _memo.update(cache.get_many(wanted))
    missing = [pair for key, pair in wanted.items() if key not in _memo]
    if not missing:
        return
    from concurrent.futures import ThreadPoolExecutor, wait

    def load(pair):
        _memo[_details_key(pair[0], pair[1], language)] = details(*pair)

    pool = ThreadPoolExecutor(max_workers=8)
    futures = {pool.submit(load, pair): pair for pair in missing}
    _, not_done = wait(futures, timeout=deadline)
    # Lookups already running finish in the background; ones not started are dropped.
    pool.shutdown(wait=False)
    for future in not_done:
        future.cancel()
    if not_done:
        for _ in not_done:
            perf.add("tmdb_deferred")
        cache.queue_tmdb(futures[f] for f in not_done)


def fetch_pending(stop=None):
    """Service side: fetch artwork widgets did not wait for. True when anything new arrived."""
    pairs = cache.pending_tmdb()
    if not pairs or not enabled():
        return False
    from concurrent.futures import ThreadPoolExecutor

    def load(pair):
        if stop is not None and stop.is_set():
            return None
        return details(*pair)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(load, pairs))
    finished = [pair for pair, result in zip(pairs, results) if result is not None]
    cache.done_tmdb(finished)
    return any(results)

def _cached(key, ttl, fetch):
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        data = fetch()
    except LOOKUP_ERRORS as exc:
        common.log("TMDb request failed for {}: {}".format(key, exc))
        return None
    cache.set(key, data, ttl)
    return data


def search(kind, query):
    """TMDb search for 'collection' or 'person'."""
    if not enabled() or not query:
        return []
    lang = _language()
    data = _cached(
        "tmdb:search:{}:{}:{}".format(kind, lang, query.lower()), SEARCH_TTL,
        lambda: _get("search/{}".format(kind),
                     {"query": query, "language": lang, "include_adult": "false"}))
    return (data or {}).get("results") or []


def collection_parts(collection_id):
    if not enabled() or not collection_id:
        return []
    lang = _language()
    data = _cached("tmdb:collection:{}:{}".format(collection_id, lang), TTL,
                   lambda: _get("collection/{}".format(collection_id), {"language": lang}))
    return (data or {}).get("parts") or []


def person_credits(person_id):
    """A person's acting credits, most popular first, without talk/news shows."""
    if not enabled() or not person_id:
        return []
    lang = _language()
    data = _cached("tmdb:person:{}:{}".format(person_id, lang), TTL,
                   lambda: _get("person/{}/combined_credits".format(person_id), {"language": lang}))
    cast = [c for c in (data or {}).get("cast") or []
            if not set(c.get("genre_ids") or []) & {10763, 10767}]
    cast.sort(key=lambda c: c.get("popularity") or 0, reverse=True)
    return cast


def to_entry(result, media_type):
    """Turn a TMDb movie/tv result into the add-on's entry dict."""
    movie = media_type == "movie"
    date = (result.get("release_date") if movie else result.get("first_air_date")) or ""
    try:
        year = int(date[:4]) if date else None
    except ValueError:
        year = None
    return {
        "kind": "movie" if movie else "tvshow",
        "tmdb": str(result.get("id") or ""),
        "imdb": "",
        "tvdb": "",
        "source": "tmdb",
        "media_id": str(result.get("id") or ""),
        "title": result.get("title") or result.get("name") or "",
        "plot": result.get("overview") or "",
        "poster": _image(result.get("poster_path"), "w500"),
        "premiered": date,
        "year": year,
        "rating": result.get("vote_average") or 0,
    }