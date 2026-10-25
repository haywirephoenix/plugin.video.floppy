"""Browse video add-ons to pick the plugin path movies or episodes play through.

Kodi's own path setting only lists media sources and drives, not plugins, so this walks
add-on directories over JSON-RPC instead.
"""

import json

import xbmc
import xbmcgui

from . import common

_SETTING = {"movie": "movie_plugin_path", "episode": "episode_plugin_path"}
_HEADING = {"movie": "Movie path", "episode": "Episode path"}


def _rpc(method, params):
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(request))).get("result") or {}
    except ValueError:
        return {}


def _addons():
    result = _rpc("Addons.GetAddons", {"type": "xbmc.addon.video", "content": "video",
                                       "enabled": True, "properties": ["name", "thumbnail"]})
    addons = [a for a in result.get("addons") or [] if a.get("addonid") != common.ADDON_ID]
    return sorted(addons, key=lambda a: (a.get("name") or "").lower())


def _list(path):
    result = _rpc("Files.GetDirectory", {"directory": path, "media": "video",
                                         "properties": ["thumbnail"]})
    return result.get("files") or []


def _item(label, thumb=""):
    li = xbmcgui.ListItem(label, offscreen=True)
    if thumb:
        li.setArt({"thumb": thumb, "icon": thumb})
    return li


def browse(heading):
    """Return the chosen plugin path, or None when cancelled."""
    dialog = xbmcgui.Dialog()
    while True:
        addons = _addons()
        if not addons:
            dialog.ok(heading, "No video add-ons are installed.")
            return None
        items = [_item(a.get("name") or a["addonid"], a.get("thumbnail")) for a in addons]
        choice = dialog.select(heading, items, useDetails=True)
        if choice < 0:
            return None
        trail = ["plugin://{}/".format(addons[choice]["addonid"])]
        while trail:
            path = trail[-1]
            files = _list(path)
            folders = [f for f in files if f.get("filetype") == "directory"]
            playable = [f for f in files if f.get("filetype") != "directory"]
            labels = ["[B]Use this path[/B]", ".."]
            labels += ["{}  >".format(f.get("label") or "") for f in folders]
            labels += [f.get("label") or "" for f in playable]
            choice = dialog.select("{}: {}".format(heading, path), labels)
            if choice < 0:
                return None
            if choice == 0:
                return path
            if choice == 1:
                trail.pop()
                continue
            picked = (folders + playable)[choice - 2]
            if picked.get("filetype") == "directory":
                trail.append(picked["file"])
            else:
                return picked["file"]


def pick(kind):
    kind = kind if kind in _SETTING else "movie"
    addon = common.addon()
    path = browse(_HEADING[kind])
    if path is not None:
        addon.setSetting(_SETTING[kind], path)
        common.notify("{} set".format(_HEADING[kind]))
    # The settings window closed to run this; reopen it so the new value shows.
    addon.openSettings()
