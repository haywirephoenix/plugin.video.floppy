"""Shared helpers: settings, logging, paths and plugin URLs."""

import json
import os
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON_ID = "plugin.video.floppy"
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_ICON = ADDON.getAddonInfo("icon")
PROFILE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))

# Home window properties shared between the plugin and the service.
HOME = 10000
PROP_RELOAD = "floppy.widget_reload"
PROP_PENDING_PLAY = "floppy.pending_play"


def addon():
    """Return a fresh Addon object so settings changed at runtime are seen."""
    return xbmcaddon.Addon(ADDON_ID)


def setting(key, default=""):
    value = addon().getSetting(key)
    return value if value != "" else default


def setting_int(key, default=0):
    try:
        return int(addon().getSetting(key))
    except (TypeError, ValueError):
        return default


def setting_bool(key, default=False):
    value = addon().getSetting(key)
    if value == "":
        return default
    return value.lower() == "true"


def log(message, level=xbmc.LOGDEBUG):
    if level == xbmc.LOGDEBUG and setting_bool("debug"):
        level = xbmc.LOGINFO
    xbmc.log("[{}] {}".format(ADDON_ID, message), level)


def notify(message, heading=None, time_ms=4000):
    xbmcgui.Dialog().notification(heading or ADDON_NAME, message, ADDON_ICON, time_ms)


def ensure_profile_dir():
    if not os.path.isdir(PROFILE_DIR):
        os.makedirs(PROFILE_DIR, exist_ok=True)
    return PROFILE_DIR


def plugin_url(**params):
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return "plugin://{}/?{}".format(ADDON_ID, urlencode(clean))


def home_property(name, value=None):
    window = xbmcgui.Window(HOME)
    if value is None:
        return window.getProperty(name)
    window.setProperty(name, value)
    return value


def clear_home_property(name):
    xbmcgui.Window(HOME).clearProperty(name)


def set_json_property(name, data):
    home_property(name, json.dumps(data))


def get_json_property(name):
    raw = home_property(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def bump_widget_reload():
    """Change the reload token that widget paths can include to force a refresh."""
    import time

    home_property(PROP_RELOAD, str(int(time.time())))


def widget_reload_time():
    """When Floppy data last changed (seconds), as signalled by this add-on or TMDb Helper."""
    try:
        return int(home_property(PROP_RELOAD) or 0)
    except ValueError:
        return 0
