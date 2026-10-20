"""Optional TMDb lookups for fanart, landscape art, clear logos and missing details."""

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import cache, common

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/"
TTL = 14 * 24 * 3600
MISS_TTL = 24 * 3600
SEARCH_TTL = 24 * 3600


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
    url = "{}/{}?{}".format(API, path, urlencode(query))
    with urlopen(Request(url, headers=headers), timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def details(kind, tmdb_id):
    """Return a compact details/artwork dict for a movie or TV show, cached."""
    if not enabled() or not tmdb_id:
        return {}
    tmdb_type = "movie" if kind == "movie" else "tv"
    language = _language()
    cache_key = "tmdb:{}:{}:{}".format(tmdb_type, tmdb_id, language)
    hit = cache.get(cache_key)
    if hit is not None:
        return hit
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
    except (HTTPError, URLError, OSError, ValueError) as exc:
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


def prefetch(pairs):
    """Warm the cache for (kind, tmdb_id) pairs in parallel."""
    if not enabled():
        return
    unique = {(kind, str(tmdb_id)) for kind, tmdb_id in pairs if tmdb_id}
    if not unique:
        return
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda pair: details(*pair), unique))

def _cached(key, ttl, fetch):
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        data = fetch()
    except (HTTPError, URLError, OSError, ValueError) as exc:
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