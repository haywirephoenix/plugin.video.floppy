# Floppy for Kodi (plugin.video.floppy)

A Kodi add-on for your self-hosted [Floppy](https://github.com/dannyvfilms/Floppy) tracker. It turns your Floppy library into lists and widgets, browses shows with Floppy's own watched state, searches through Floppy, and can send your watch history and resume positions straight to Floppy, with no Trakt and no separate scrobbler.

Works standalone or as a widget source for any skin that supports custom widgets. Playback goes through any player add-on you point it at.

Needs Kodi 20 (Nexus) or newer and a Floppy instance with its API token.

[Download Latest Release](https://github.com/haywirephoenix/plugin.video.floppy/releases) · [Documentation (wiki)](https://github.com/haywirephoenix/plugin.video.floppy/wiki)

## Features

- **Lists for everything**: Continue Watching, Next Up, In Progress, watchlists, history, calendar, Discover rows, your Floppy lists and your Floppy home rows. Movies, TV and anime are available separately or combined.
- **Floppy watched state everywhere**: seasons and episodes show Floppy's watch progress, not Trakt's or Kodi's library.
- **Anime-aware**: shows tracked in Floppy's Anime library are read and marked in the right place.
- **Search through Floppy**: movies, shows, collections and people, with the same context menu as the widgets.
- **Play through any add-on**: browse to a plugin path or pick a TMDb Helper-style player file. TMDb Helper itself isn't needed.
- **Scrobbling built in**: plays, resume positions and Floppy's Now Playing card, sent with your API token.
- **Context menu actions**: mark watched or unwatched, mark a season or a whole show watched, watchlist, remove from Floppy, and remove from Continue Watching.

## Quick start

1. Install `plugin.video.floppy-x.x.x.zip` (Add-ons → Install from zip file, with **Unknown sources** on).
2. In the add-on's settings, enter your **Floppy address** and **API token**, then **Test connection**.
3. Under Playback → **Play items with**, choose how movies and episodes play.

## Documentation

| Page | What it covers |
|---|---|
| [Installation](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Installation) | Installing and connecting to Floppy, optional settings |
| [Browsing](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Browsing) | Menus, shows and seasons, the context menu, anime |
| [Widgets](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Widgets) | Every widget path, and keeping widgets up to date |
| [Search](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Search) | Search paths for skins |
| [Playback](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Playback) | Plugin paths, player files, custom URLs and placeholders |
| [Scrobbling and Resume](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Scrobbling-and-Resume) | Watch history, saved positions and resuming |
| [Skin Integration](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Skin-Integration) | ListItem properties and the play hand-off, for skin authors |
| [Troubleshooting](https://github.com/haywirephoenix/plugin.video.floppy/wiki/Troubleshooting) | Common problems and debug logging |
