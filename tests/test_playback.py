from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omajelly import cli as cli_module
from omajelly import playback as playback_module
from omajelly import windowing as windowing_module
from omajelly.client import HttpMethod
from omajelly.common import ConfigurationError, ResponseError
from omajelly.config import (
    config_home,
    load_window_geometry,
    save_window_geometry,
    validate_window_geometry,
)
from omajelly.constants import MAX_HYPR_BYTES
from omajelly.playback import WatchState
from tests.support import EP1, TOKEN, USER


class JellyfinPlaybackTests(unittest.TestCase):
    def test_jellyfin_web_urls_open_in_an_app_window_without_the_token(self):
        config = {"server": "http://jellyfin:8096"}
        self.assertEqual(
            playback_module.jellyfin_web_url(config),
            "http://jellyfin:8096/web/",
        )
        self.assertEqual(
            playback_module.jellyfin_web_url(config, EP1),
            "http://jellyfin:8096/web/#/details?id=" + EP1,
        )
        self.assertNotIn(TOKEN, playback_module.jellyfin_web_url(config, EP1))
        with self.assertRaises(ConfigurationError):
            playback_module.jellyfin_web_url(config, "../42")

        with (
            mock.patch.object(cli_module, "load_config", return_value=config),
            mock.patch.object(cli_module, "launch_jellyfin_webapp") as launcher,
        ):
            self.assertEqual(cli_module.main(["open-web"]), 0)
        launcher.assert_called_once_with("http://jellyfin:8096/web/")

    def test_play_backend_web_opens_an_app_window_without_the_token(self):
        config = {"server": "http://jellyfin:8096"}
        url = playback_module.jellyfin_playback_url(config, EP1)
        self.assertEqual(
            url,
            "http://jellyfin:8096/web/#/details?id=" + EP1,
        )
        self.assertNotIn(TOKEN, url)
        with self.assertRaises(ConfigurationError):
            playback_module.jellyfin_playback_url(config, "../42")

        with (
            mock.patch.object(playback_module, "load_config", return_value=config),
            mock.patch(
                "omajelly.downloads.cached_media_path", return_value=None
            ),
            mock.patch.object(
                playback_module, "launch_jellyfin_webapp"
            ) as launcher,
            mock.patch.object(
                playback_module, "browser_window_addresses", return_value=frozenset()
            ),
            mock.patch.object(playback_module, "bring_player_to_active_workspace"),
        ):
            self.assertEqual(
                cli_module.main(
                    ["play", "--rating-key", EP1, "--backend", "web"]
                ),
                0,
            )
            self.assertEqual(
                cli_module.main(
                    [
                        "play",
                        "--rating-key",
                        EP1,
                        "--backend",
                        "web",
                        "--mode",
                        "fullscreen",
                    ]
                ),
                0,
            )
        self.assertEqual(
            launcher.call_args_list,
            [
                mock.call(url, None),
                mock.call(url, ["--start-fullscreen"]),
            ],
        )
        self.assertEqual(
            cli_module.parser().parse_args(["play", "--rating-key", EP1]).backend,
            playback_module.PlaybackBackend.WEB,
        )

    def test_open_web_uses_the_omarchy_webapp_launcher(self):
        config = {"server": "http://jellyfin:8096"}
        self.assertEqual(
            playback_module.jellyfin_web_url(config),
            "http://jellyfin:8096/web/",
        )
        self.assertEqual(
            playback_module.jellyfin_web_url(config, EP1),
            "http://jellyfin:8096/web/#/details?id=" + EP1,
        )
        with self.assertRaises(ConfigurationError):
            playback_module.jellyfin_web_url(config, "../42")

        with (
            mock.patch.object(cli_module, "load_config", return_value=config),
            mock.patch.object(cli_module, "launch_jellyfin_webapp") as launcher,
        ):
            self.assertEqual(cli_module.main(["open-web"]), 0)
        launcher.assert_called_once_with("http://jellyfin:8096/web/")
        client = mock.Mock()
        client.user_id = USER
        playback_module.set_watch_state(client, EP1, WatchState.WATCHED)
        self.assertEqual(
            client.request_empty.call_args.args[0],
            "/Users/" + USER + "/PlayedItems/" + EP1,
        )
        self.assertEqual(client.request_empty.call_args.kwargs["method"], HttpMethod.POST)

        playback_module.set_watch_state(client, EP1, WatchState.UNWATCHED)
        self.assertEqual(client.request_empty.call_args.kwargs["method"], HttpMethod.DELETE)

        with self.assertRaises(ConfigurationError):
            playback_module.set_watch_state(client, "../42", WatchState.WATCHED)
        with self.assertRaises(ConfigurationError):
            playback_module.set_watch_state(client, EP1, "maybe")

        command_client = mock.Mock()
        command_client.user_id = USER
        with mock.patch.object(
            cli_module, "client_from_saved", return_value=(command_client, {})
        ):
            self.assertEqual(
                cli_module.main(
                    ["mark", "--rating-key", EP1, "--state", "watched"]
                ),
                0,
            )
        command_client.request_empty.assert_called_once()

    def test_player_geometry_is_private_bounded_and_read_from_own_pid(self):
        geometry = {
            "schemaVersion": 1,
            "x": -20,
            "y": 140,
            "width": 960,
            "height": 540,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                clear=False,
            ),
        ):
            save_window_geometry(geometry)
            path = config_home() / "player-window.json"
            self.assertEqual(load_window_geometry(), geometry)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        clients = [
            {
                "pid": 12345,
                "mapped": True,
                "floating": True,
                "fullscreen": 0,
                "at": [2100, 1300],
                "size": [1120, 630],
                "title": "Untrusted title that is ignored",
            }
        ]
        with mock.patch.object(
            windowing_module,
            "run_bounded_output",
            return_value=(0, json.dumps(clients).encode("utf-8")),
        ) as command:
            self.assertEqual(
                windowing_module.read_hypr_geometry(12345),
                {
                    "schemaVersion": 1,
                    "x": 2100,
                    "y": 1300,
                    "width": 1120,
                    "height": 630,
                },
            )
        command.assert_called_once_with(
            ["hyprctl", "-j", "clients"], maximum=MAX_HYPR_BYTES, timeout=2
        )
        monitors = [{"x": 2048, "y": 1224, "width": 1920, "height": 1080}]
        with mock.patch.object(
            windowing_module,
            "run_bounded_output",
            return_value=(0, json.dumps(monitors).encode("utf-8")),
        ):
            self.assertTrue(
                windowing_module.geometry_is_visible(
                    {
                        "schemaVersion": 1,
                        "x": 2100,
                        "y": 1300,
                        "width": 1120,
                        "height": 630,
                    }
                )
            )
            self.assertFalse(
                windowing_module.geometry_is_visible(
                    {
                        "schemaVersion": 1,
                        "x": 90000,
                        "y": 90000,
                        "width": 1120,
                        "height": 630,
                    }
                )
            )
        with self.assertRaises(ResponseError):
            validate_window_geometry(
                {
                    "schemaVersion": 1,
                    "x": 0,
                    "y": 0,
                    "width": 1000000,
                    "height": 540,
                }
            )

    def test_bring_player_targets_the_jellyfin_webapp_on_the_focused_monitor(self):
        clients = [
            {
                "pid": 12345,
                "address": "0x222",
                "class": "chromium",
                "title": "Home - Jellyfin",
                "mapped": True,
                "floating": True,
                "fullscreen": 0,
            },
            {
                "pid": 12345,
                "address": "0x111",
                "class": "chrome-jellyfin__web_-Default",
                "title": "Episode - Jellyfin",
                "mapped": True,
                "floating": False,
                "fullscreen": 0,
            },
        ]
        monitors = [
            {
                "focused": True,
                "x": 2048,
                "y": 1224,
                "reserved": [0, 26, 0, 0],
                "activeWorkspace": {"id": 2, "name": "2"},
            }
        ]
        with (
            mock.patch.object(
                windowing_module,
                "load_config",
                return_value={"server": "http://jellyfin:8096"},
            ),
            mock.patch.object(
                windowing_module,
                "run_bounded_output",
                side_effect=[
                    (0, json.dumps(clients).encode("utf-8")),
                    (0, json.dumps(monitors).encode("utf-8")),
                ],
            ),
            mock.patch.object(
                windowing_module, "run_no_output", return_value=0
            ) as command,
        ):
            windowing_module.bring_player_to_active_workspace()
        script = command.call_args.args[0][2]
        self.assertIn("w.address == '0x111'", script)
        self.assertNotIn("w.pid ==", script)
        self.assertIn("workspace = '2'", script)
        self.assertIn("alter_zorder", script)

        with (
            mock.patch.object(
                windowing_module,
                "load_config",
                return_value={"server": "http://jellyfin:8096"},
            ),
            mock.patch.object(
                windowing_module,
                "run_bounded_output",
                return_value=(0, json.dumps(clients).encode("utf-8")),
            ),
        ):
            self.assertEqual(
                windowing_module.browser_window_addresses(),
                frozenset({"0x111", "0x222"}),
            )
            self.assertEqual(
                windowing_module.player_window_addresses(), frozenset({"0x111"})
            )
            with self.assertRaises(ConfigurationError):
                windowing_module.bring_player_to_active_workspace(
                    ignore_addresses=frozenset({"0x111"})
                )

        fullscreen_clients = [
            {
                "pid": 12345,
                "address": "0x111",
                "class": "chrome-jellyfin__web_-Default",
                "title": "Episode - Jellyfin",
                "mapped": True,
                "floating": False,
                "fullscreen": 2,
            }
        ]
        with (
            mock.patch.object(
                windowing_module,
                "load_config",
                return_value={"server": "http://jellyfin:8096"},
            ),
            mock.patch.object(
                windowing_module,
                "run_bounded_output",
                side_effect=[
                    (0, json.dumps(fullscreen_clients).encode("utf-8")),
                    (0, json.dumps(monitors).encode("utf-8")),
                ],
            ),
            mock.patch.object(
                windowing_module, "run_no_output", return_value=0
            ) as command,
        ):
            windowing_module.bring_player_to_active_workspace()
        script = command.call_args.args[0][2]
        self.assertIn("w.address == '0x111'", script)
        self.assertNotIn("relative = false", script)

        candidates_with_failed_page = [
            {
                "pid": 99999,
                "address": "0xdef",
                "class": "chrome-jellyfin__web_-Default",
                "title": "Page not found",
                "mapped": True,
                "fullscreen": 0,
                "focusHistoryID": 0,
            },
            {
                "pid": 12345,
                "address": "0xabc",
                "class": "chrome-jellyfin__web_-Default",
                "title": "Flowgate",
                "mapped": True,
                "fullscreen": 0,
                "focusHistoryID": 8,
            },
        ]
        with (
            mock.patch.object(
                windowing_module,
                "load_config",
                return_value={"server": "http://jellyfin:8096"},
            ),
            mock.patch.object(
                windowing_module,
                "run_bounded_output",
                side_effect=[
                    (0, json.dumps(candidates_with_failed_page).encode("utf-8")),
                    (0, json.dumps(monitors).encode("utf-8")),
                ],
            ),
            mock.patch.object(
                windowing_module, "run_no_output", return_value=0
            ) as command,
        ):
            windowing_module.bring_player_to_active_workspace()
        self.assertIn("w.address == '0xabc'", command.call_args.args[0][2])

        with (
            mock.patch.object(
                windowing_module,
                "load_config",
                return_value={"server": "http://jellyfin:8096"},
            ),
            mock.patch.object(
                windowing_module,
                "run_bounded_output",
                return_value=(0, b"[]"),
            ),
            self.assertRaises(ConfigurationError),
        ):
            windowing_module.bring_player_to_active_workspace()

    def test_cached_play_reports_progress_and_marks_watched(self):
        from omajelly.playback import PlaybackItem, PlaybackMode, play_cached_file
        from tests.support import MOVIE

        item = PlaybackItem(
            rating_key=MOVIE,
            media_type="movie",
            stream_path="/Videos/" + MOVIE + "/stream?Static=true&MediaSourceId=src",
            media_source_id="src",
            play_session_id="session",
            resume_seconds=0,
            duration_ms=100000,
            subtitle_paths=(),
        )
        client = mock.Mock()
        client.user_id = USER
        player = mock.Mock()
        player.pid = 42
        player.poll.side_effect = [None, 0]
        with tempfile.TemporaryDirectory() as directory:
            media = (
                Path(directory)
                / "cache"
                / "omajelly"
                / "downloads"
                / MOVIE
                / "media"
            )
            media.parent.mkdir(parents=True)
            media.write_bytes(b"video")
            with (
                mock.patch.dict(
                    os.environ,
                    {"XDG_CACHE_HOME": str(Path(directory) / "cache")},
                    clear=False,
                ),
                mock.patch.object(
                    playback_module, "client_from_saved", return_value=(client, {})
                ),
                mock.patch.object(
                    playback_module, "single_playback_item", return_value=item
                ),
                mock.patch.object(
                    playback_module.subprocess, "Popen", return_value=player
                ),
                mock.patch.object(
                    playback_module, "mpv_status", return_value=(95000, False, 0)
                ),
                mock.patch.object(playback_module.time, "sleep"),
            ):
                self.assertEqual(
                    play_cached_file(media, PlaybackMode.WINDOWED, MOVIE), 0
                )
        paths = [call.args[0] for call in client.request_json.call_args_list]
        self.assertTrue(any("/Sessions/Playing" in path for path in paths))
        self.assertTrue(any(path.endswith("/Sessions/Playing/Stopped") for path in paths))
        client.request_empty.assert_called_once()
        self.assertEqual(
            client.request_empty.call_args.args[0],
            "/Users/" + USER + "/PlayedItems/" + MOVIE,
        )
        self.assertEqual(
            client.request_empty.call_args.kwargs["method"], HttpMethod.POST
        )
