# Omajelly

Omajelly puts Jellyfin on the Omarchy bar. It is a Jellyfin port of [Omaplex](https://github.com/pjgeutjens/omarchy-omaplex): compact Continue / Added / Movies / Shows lists, a fullscreen Browse All overlay, and local `mpv` playback that reports progress back to the server.

Click a row to stream it through `mpv`. Choose Windowed for a floating, movable window or Fullscreen before playback. Windowed mode remembers its last compositor position and size. Press `O` to open the same item in Jellyfin Web. Press `P`, or click the Jellyfin glyph beside the live-status badge, to open Jellyfin Web itself.

Connection settings has an **Auto-play next episode** toggle. It is off by default. When it is on, episode playback continues with the next episode in the series after the current episode ends. Closing the player stops the queue. Movie playback remains single-item.

Browse All opens a separate fullscreen Omarchy panel. It searches and pages through the complete movie or show library. Shows stay in the list as folders: opening a show expands its seasons in place, then a season expands its episodes. Only one show and one season are open at a time.

`mpv` keeps its built-in on-screen controller and default keyboard bindings. Use Space for pause, the arrow keys to seek, `#` to choose an audio track, `J` to choose a subtitle track, and `F` to toggle fullscreen. Press `Ctrl+J` to search Jellyfin's remote subtitle results in an mpv menu.

## Requirements

- Omarchy Quattro with the schema version 1 plugin API
- Python 3.11 or newer
- `secret-tool`, `mpv`, and `xdg-open`
- Optional: `fzf` for Browse All ranking; a bounded built-in fuzzy matcher is used when it is unavailable
- A Jellyfin server the machine can reach

## Install

```bash
omarchy plugin add https://github.com/hopelezz/omajelly.git --enable
```

That clones the repository into `~/.config/omarchy/plugins/io.github.hopelezz.omajelly` and enables it on the bar. Saved user plugin files and `shell.json` changes reload automatically. A manual rescan is also available:

```bash
omarchy-shell shell rescanPlugins
```

## First-run setup

Open the Jellyfin widget after installation. On first launch it opens Connection settings automatically:

1. Enter the Jellyfin base URL (`http://host:8096`, `https://host`, or a reverse-proxy path such as `http://media/jellyfin`). Do not use the `/web` client address.
2. Choose **Get a Quick Connect code**. This panel shows a short code and waits.
3. On a phone, TV, or browser that is already signed in to that same Jellyfin server, open **Quick Connect** (usually under the profile menu) and enter the code.
4. Or skip the code and use a username and password, or expand **Use an API key instead**. Those use **Test and save connection**.

The Quick Connect secret, password, and API key stay in the helper and the desktop secret service. They never land in QML, `shell.json`, cache, logs, URLs, or process arguments. When editing a working password or API key connection, leave those fields blank to keep the saved token.

Connection settings stores three preferences with the widget entry in `~/.config/omarchy/shell.json`. **Auto-play next episode** is disabled by default. **Subtitle search language** is a two-letter code and defaults to `en`. **Show new-item count** is on by default and controls the number beside the bar icon.

The server origin, user id, client identifier, and discovered library IDs go to `~/.config/omajelly/config.json`; the last windowed player rectangle goes to `player-window.json` in the same private directory. Removing credentials from Connection settings requires a confirmation click and clears saved authentication material and cached lists while retaining the player geometry preference.

Quick Connect has to be enabled on the Jellyfin server (Dashboard → General). This plugin only *creates* the code; a device that is already signed in to that server is what *approves* it.

Plain HTTP is allowed for a trusted LAN Jellyfin server. It exposes Jellyfin traffic to that LAN, so use HTTPS for untrusted networks.

### Optional `.env` import

For development or migration, the helper can import `JELLYFIN_` values shown in `.env.example`. The import rejects files readable by other users, so set mode `600` first.

```bash
chmod 600 /path/to/project/.env
~/.config/omarchy/plugins/io.github.hopelezz.omajelly/bin/omajelly \
  configure-from-env /path/to/project/.env
```

## Interaction

- Left click: open or close the panel
- Middle click: refresh
- Right click: open Connection settings
- Up/Down or J/K: move the selection cursor
- Enter or click: play the selected item, or expand a show/season folder
- X or click the watch-state badge: toggle the selected item between watched and unwatched
- , / . : move between Continue, Added, Movies, and Shows (H/L remain available to Omarchy for switching panels)
- /: search the rows in the current compact view
- T or the panel button: show or hide watched items
- C: Continue Watching
- A: combined Recently Added
- M: recently added movies
- S: recently added shows
- B or Browse All: open the fullscreen library browser
- ?: toggle the searchable keybindings view
- Footer settings button or right-click the bar icon: open Connection settings
- W: select Windowed playback
- F: select Fullscreen playback
- O: open the selected item in Jellyfin Web
- P or the Jellyfin glyph beside the live-status badge: open Jellyfin Web
- R: refresh the displayed Jellyfin data
- U or Scan all: discover libraries and request a library scan
- Escape: close the panel

The panel reads `~/.cache/omajelly/recent.json` before it contacts Jellyfin. A failed refresh keeps the last successful list and labels it offline.

`U` asks Jellyfin to refresh the library (`POST /Library/Refresh`). The UI reports that the scan was **accepted**, never that it has finished. After that, the plugin refreshes displayed data twice while the scan settles. Ordinary `R` remains a lightweight data refresh.

In Browse All, select Movies or Shows first, then `/` fuzzy-searches only that scope. J/K or ↑/↓ move the same selection cursor as the compact panel. M/S switch the unfiltered scope. ← goes back (collapse a folder, then the previous page, then close). → opens the selected folder or goes to the next page. Escape matches back. Season syntax applies to Show searches: a query such as `Alone S01` expands matching shows into Season 1 episode results; `S01E03` can select one episode directly.

## Playback boundary

The helper resolves a Jellyfin `MediaSource`, starts a random loopback-only HTTP proxy, and runs `mpv` against that local URL. The helper adds `X-Emby-Token` only on the upstream request. This keeps the token out of `mpv` arguments while retaining Range requests for seeking.

Online subtitle search goes through Jellyfin remote search. Omajelly caps the result list at 40 and the downloaded subtitle at 8 MiB. The selected subtitle is written with mode `0600` inside the player's private temporary directory, loaded into mpv, and deleted when the player exits.

While mpv is open, the helper reports playback position to Jellyfin every ten seconds and once more when an item ends or the player closes. Reaching 90 percent marks that item watched, including each item completed in an automatic episode queue. The panel refreshes when playback ends.

The watch-state badge is also an action. Click it, or select a row and press `X`, to send Jellyfin a watched or unwatched update.

## Validation

```bash
./scripts/validate.sh
```

This runs Omarchy's plugin validator, `qmllint`, Python tests, and the Node tests for the QML data model.

## Removal

Close any player window first, then remove the widget through Omarchy Plugin Control or run:

```bash
omarchy plugin remove io.github.hopelezz.omajelly --yes
```

Removal does not delete saved server settings, cached lists, or secret-service entries. Prefer **Remove credentials** in Connection settings before uninstalling. For a manual reset after removal:

```bash
secret-tool clear service io.github.hopelezz.omajelly
rm -rf ~/.config/omajelly ~/.cache/omajelly
```

The plugin installs no service, privileged file, or Hyprland rule.

Omajelly reuses the QML layout and helper structure of Omaplex by Pieter Geutjens (MIT).
