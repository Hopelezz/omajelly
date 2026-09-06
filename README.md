# Omajelly

Omajelly puts Jellyfin on the Omarchy bar. It is a Jellyfin port of [Omaplex](https://github.com/pjgeutjens/omarchy-omaplex): compact Continue / Added / Movies / Shows lists, a fullscreen Browse All overlay, and Jellyfin Web playback in a standalone app window.

Click a row to open the selected item in Jellyfin Web. Omajelly verifies that the standalone Jellyfin webapp exists before it launches the item. Enable **Use local mpv player** only when you deliberately want the built-in player. Press `O` to open that item's details in the Jellyfin webapp. Press `P`, or click the Jellyfin glyph beside the live-status badge, to open Jellyfin Web as a standalone app.

Jellyfin Web is the default. Each selected title opens in a new standalone Chromium `--app` window via `omarchy-launch-webapp`, and Omajelly brings that window to the active workspace. Before the launch, it verifies or creates the Omarchy Jellyfin launcher using the saved server origin. Sign in once in that window; Omajelly never puts the saved token in a URL, desktop file, or process argument.

Browse All opens a separate fullscreen Omarchy panel. It searches and pages through the complete movie or show library. Shows stay in the list as folders: a closed show or season uses a right chevron, an open one uses a down chevron. Opening a show expands its seasons in place, then a season expands its episodes. Only one show and one season are open at a time.

## Requirements

- Omarchy Quattro with the schema version 1 plugin API
- Python 3.11 or newer
- `secret-tool`, `mpv`, `chromium`, and `omarchy-launch-webapp`
- Optional: `omarchy-webapp-install` / `omarchy-webapp-remove` for the Jellyfin launcher Omajelly creates on first play
- Optional: `fzf` for Browse All ranking; a bounded built-in fuzzy matcher is used when it is unavailable
- A Jellyfin server the machine can reach

## Install

```bash
omarchy plugin add https://github.com/Hopelezz/omajelly.git --enable
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

Connection settings stores widget preferences in `~/.config/omarchy/shell.json`. **Show new-item count** is on by default. Jellyfin Web is the default player. **Use local mpv player** is off by default.

The server origin, user id, client identifier, and discovered library IDs go to `~/.config/omajelly/config.json`. Removing credentials from Connection settings requires a confirmation click and clears saved authentication material, cached lists, and the download cache.

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
- Enter, Space, or click: play the selected item, or expand a show/season folder
- X or click the watch-state badge: toggle watched and unwatched. On Downloads, X or REMOVE drops the selected title.
- ←/→, , / ., or [ / ]: move between Continue, Added, Movies, Shows, and Downloads
- Tab: switch Omarchy bar panels
- /: search the rows in the current compact view
- T or the panel button: show or hide watched items
- C: Continue Watching
- A: combined Recently Added
- M: recently added movies
- S: recently added shows
- D: download list
- Y: add the selected title to the download list. On Downloads, Y also removes it.
- B or Browse All: open the fullscreen library browser
- ?: toggle the searchable keybindings view
- Footer settings button or right-click the bar icon: open Connection settings
- W: select Windowed local playback (available only when **Use local mpv player** is on)
- F: select Fullscreen local playback (available only when **Use local mpv player** is on)
- The external-link button: bring the player window to this workspace
- O: open the selected item's details in the Jellyfin webapp
- P or the Jellyfin glyph beside the live-status badge: open Jellyfin Web
- R: refresh the displayed Jellyfin data
- U or Scan all: discover libraries and request a library scan
- Escape: collapse an open season or show, then close the panel

The panel reads `~/.cache/omajelly/recent.json` before it contacts Jellyfin. A failed refresh keeps the last successful list and labels it offline.

Every 15 minutes, the plugin rediscovers movie and show libraries and asks Jellyfin to refresh them (`POST /Library/Refresh`). The UI reports that the scan was **accepted**, never that it has finished. After that, the plugin refreshes displayed data twice while the scan settles. `U` triggers the same process immediately; ordinary `R` remains a lightweight data refresh.

In Browse All, select Movies, Shows, or Downloads, then `/` searches that list. **SAVE** queues a title; **REMOVE** or **Y**/**X** drops it. J/K or ↑/↓ move the same selection cursor as the compact panel. M/S/D switch the unfiltered scope. ← goes back (collapse a folder, then the previous page, then close). → opens the selected folder or goes to the next page. N/P change pages without opening a folder. Escape matches back. Season syntax applies to Show searches: a query such as `Alone S01` expands matching shows into Season 1 episode results; `S01E03` can select one episode directly.

## Playback boundary

Play uses Jellyfin Web by default. The built-in mpv fallback is an explicit opt-in. Its stream proxy and subtitles stay on loopback; the saved token never appears in QML, `shell.json`, cache, logs, URLs, or process arguments.

The web-first path verifies the Jellyfin launcher before opening the selected item's Jellyfin Web details page in a standalone Chromium `--app` window, not a browser tab. It opens a new app window for each selected title, so Chromium cannot reuse the home window and discard the item URL. Fullscreen requests also pass `--start-fullscreen`. The helper only passes the configured server origin and a validated item id. Playback, resume, subtitles, and next-episode autoplay stay in the web client.

Titles on the download list are fetched as original streams into `~/.cache/omajelly/downloads`. Settings choose a 5, 10, 20, or 40 GB cap. The helper resumes partial files, evicts the least recently played ready item when the cache is full, and never writes the token into the download index. A ready title plays from that cache with mpv even when Jellyfin Web is the default player.

The external-link button moves an existing player window onto the focused workspace.

The watch-state badge is also an action. Click it, or select a row and press `X`, to send Jellyfin a watched or unwatched update.

## Validation

```bash
./scripts/validate.sh
```

This runs Omarchy's plugin validator, `qmllint`, Python tests, and the Node tests for the QML data model.

## Removal

Close any Jellyfin webapp window first, then remove the widget through Omarchy Plugin Control or run:

```bash
omarchy plugin remove io.github.hopelezz.omajelly --yes
```

Removal does not delete saved server settings, cached lists, or secret-service entries. Prefer **Remove credentials** in Connection settings before uninstalling. That also removes a Jellyfin webapp *only if Omajelly created it*; a launcher you added yourself is left alone. For a manual reset after removal:

```bash
secret-tool clear service io.github.hopelezz.omajelly
rm -rf ~/.config/omajelly ~/.cache/omajelly
```

The plugin installs no service, privileged file, or Hyprland rule.

## License

Omajelly is MIT. See `LICENSE`. It reuses the QML layout and helper structure of Omaplex by Pieter Geutjens (MIT). Required tools are `secret-tool`, `mpv`, `chromium`, and `omarchy-launch-webapp`; `fzf` is optional.
