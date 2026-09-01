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
from omajelly.constants import MAX_HYPR_BYTES, PLUGIN_ID
from omajelly.playback import PlaybackItem, PlaybackMode, TimelineState, WatchState
from tests.support import EP1, EP2, EP3, MOVIE, SHOW, TOKEN, USER, FakeClient


def playback_info(source_id: str = "source1") -> dict:
    return {
        "PlaySessionId": "session1",
        "MediaSources": [
            {
                "Id": source_id,
                "RunTimeTicks": 300 * 10_000_000,
                "MediaStreams": [
                    {"Type": "Audio", "Index": 0, "Codec": "aac"},
                    {"Type": "Subtitle", "Index": 1, "Codec": "srt"},
                ],
            }
        ],
    }


def playable_item(item_id: str, item_type: str = "Episode", series_id: str = SHOW) -> dict:
    document = {
        "Id": item_id,
        "Type": item_type,
        "RunTimeTicks": 300 * 10_000_000,
        "UserData": {"PlaybackPositionTicks": 125 * 10_000_000, "Played": False},
    }
    if item_type == "Episode":
        document["SeriesId"] = series_id
    return document


class JellyfinPlaybackTests(unittest.TestCase):
    def test_mpv_argv_is_loopback_only_and_never_contains_the_token(self):
        client = FakeClient(
            {
                "/PlaybackInfo": playback_info(),
                "/Items/" + EP1: playable_item(EP1),
            }
        )
        item = playback_module.single_playback_item(client, EP1)
        self.assertTrue(item.stream_path.startswith("/Videos/" + EP1 + "/stream?"))
        self.assertIn("MediaSourceId=source1", item.stream_path)
        self.assertEqual(item.resume_seconds, 125)
        self.assertTrue(item.subtitle_paths[0].startswith("/Videos/" + EP1 + "/"))
        self.assertNotIn(TOKEN, item.stream_path)
        self.assertNotIn(client.token, item.stream_path)

        args = playback_module.mpv_playlist_arguments(
            PlaybackMode.WINDOWED,
            [
                (
                    "http://127.0.0.1:32100/stream/random",
                    125,
                    ["http://127.0.0.1:32100/subtitle/random/0"],
                )
            ],
        )
        joined = " ".join(args)
        self.assertNotIn(TOKEN, joined)
        self.assertNotIn("X-Emby-Token", joined)
        self.assertIn("--autofit=960x540", args)
        self.assertNotIn("--wayland-app-id=" + PLUGIN_ID + ".player", args)
        self.assertIn("--osc=yes", args)
        self.assertIn("http://127.0.0.1:32100/stream/random", args)
        for argument in args:
            if argument.startswith("http"):
                self.assertTrue(argument.startswith("http://127.0.0.1:"))

        queue_args = playback_module.mpv_playlist_arguments(
            PlaybackMode.WINDOWED,
            [
                ("http://127.0.0.1:32100/stream/random/0", 125, []),
                (
                    "http://127.0.0.1:32100/stream/random/1",
                    0,
                    ["http://127.0.0.1:32100/subtitle/random/1"],
                ),
            ],
        )
        self.assertEqual(queue_args.count("--{"), 2)
        self.assertLess(
            queue_args.index("http://127.0.0.1:32100/stream/random/0"),
            queue_args.index("http://127.0.0.1:32100/stream/random/1"),
        )
        fullscreen = playback_module.mpv_playlist_arguments(
            PlaybackMode.FULLSCREEN, [("http://127.0.0.1:32100/stream/random", 0, [])]
        )
        self.assertIn("--fullscreen", fullscreen)
        self.assertIn("--wayland-app-id=" + PLUGIN_ID + ".player", fullscreen)
        geometry = {
            "schemaVersion": 1,
            "x": 2100,
            "y": 1300,
            "width": 1120,
            "height": 630,
        }
        restored = playback_module.mpv_playlist_arguments(
            PlaybackMode.WINDOWED,
            [("http://127.0.0.1:32100/stream/random", 0, [])],
            window_geometry=geometry,
        )
        self.assertIn("--geometry=1120x630", restored)
        self.assertNotIn("--autofit=960x540", restored)
        geometry_script = windowing_module.hypr_geometry_script(12345, geometry)
        self.assertIn("w.pid == 12345", geometry_script)
        self.assertNotIn(TOKEN, geometry_script)

    def test_auto_play_next_uses_later_episodes_and_skips_movies(self):
        client = FakeClient(
            {
                "/PlaybackInfo": playback_info(),
                "/Shows/" + SHOW + "/Episodes": {
                    "Items": [
                        playable_item(EP1),
                        playable_item(EP2),
                        playable_item(EP3),
                    ]
                },
                "/Items/" + EP1: playable_item(EP1),
                "/Items/" + EP2: playable_item(EP2),
                "/Items/" + EP3: playable_item(EP3),
                "/Items/" + MOVIE: playable_item(MOVIE, "Movie"),
            }
        )
        queued = playback_module.queued_playback_items(client, EP2)
        self.assertEqual([item.rating_key for item in queued], [EP2, EP3])

        movie_only = playback_module.queued_playback_items(client, MOVIE)
        self.assertEqual([item.rating_key for item in movie_only], [MOVIE])

        parsed = cli_module.parser().parse_args(
            [
                "play",
                "--rating-key",
                EP2,
                "--mode",
                "windowed",
                "--auto-play-next",
            ]
        )
        self.assertTrue(parsed.auto_play_next)

    def test_finishing_item_reports_stop_and_marks_watched_at_ninety_percent(self):
        item = PlaybackItem(
            rating_key=EP1,
            media_type="episode",
            stream_path="/Videos/" + EP1 + "/stream?Static=true&MediaSourceId=source1",
            media_source_id="source1",
            play_session_id="session1",
            resume_seconds=0,
            duration_ms=300_000,
            subtitle_paths=(),
        )
        client = mock.Mock()
        client.user_id = USER
        playback_module.finish_playback_item(client, item, 270_000)
        json_paths = [call.args[0] for call in client.request_json.call_args_list]
        empty_paths = [call.args[0] for call in client.request_empty.call_args_list]
        self.assertTrue(any(path.endswith("/Sessions/Playing/Stopped") for path in json_paths))
        self.assertEqual(empty_paths, ["/Users/" + USER + "/PlayedItems/" + EP1])
        self.assertEqual(client.request_empty.call_args.kwargs["method"], HttpMethod.POST)

        client.reset_mock()
        playback_module.finish_playback_item(client, item, 120_000)
        self.assertEqual(client.request_empty.call_count, 0)
        self.assertTrue(
            client.request_json.call_args.args[0].endswith("/Sessions/Playing/Stopped")
        )

    def test_watch_state_updates_use_played_items_and_validate_inputs(self):
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

    def test_jellyfin_web_urls_support_home_and_item_deep_links(self):
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
            mock.patch.object(cli_module, "launch_detached") as launcher,
        ):
            self.assertEqual(cli_module.main(["open-web"]), 0)
        launcher.assert_called_once_with(
            ["xdg-open", "http://jellyfin:8096/web/"]
        )

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

    def test_bring_player_targets_exact_app_on_focused_monitor(self):
        clients = [
            {
                "pid": 12345,
                "class": PLUGIN_ID + ".player",
                "title": "Omajelly",
                "mapped": True,
                "floating": True,
                "fullscreen": 0,
            },
            {
                "pid": 99999,
                "class": "mpv",
                "title": "Unrelated player",
                "mapped": True,
                "floating": True,
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
                "run_bounded_output",
                side_effect=[
                    (0, json.dumps(clients).encode("utf-8")),
                    (0, json.dumps(monitors).encode("utf-8")),
                ],
            ),
            mock.patch.object(
                windowing_module, "run_no_output", return_value=0
            ) as command,
            mock.patch.object(
                windowing_module,
                "_is_omajelly_play_helper",
                side_effect=lambda pid: pid == 54321,
            ),
            mock.patch.object(
                windowing_module,
                "_process_parent_id",
                side_effect=lambda pid: 54321 if pid == 12345 else 1,
            ),
        ):
            windowing_module.bring_player_to_active_workspace()
        script = command.call_args.args[0][2]
        self.assertIn("w.pid == 12345", script)
        self.assertIn("workspace = '2'", script)

        with (
            mock.patch.object(
                windowing_module,
                "run_bounded_output",
                return_value=(0, b"[]"),
            ),
            self.assertRaises(ConfigurationError),
        ):
            windowing_module.bring_player_to_active_workspace()
