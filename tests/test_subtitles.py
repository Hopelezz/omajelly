from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omajelly import cli as cli_module
from omajelly import playback as playback_module
from omajelly import subtitles as subtitles_module
from omajelly.client import HttpMethod
from omajelly.common import ConfigurationError
from omajelly.playback import PlaybackMode
from tests.support import EP1, TOKEN, FakeClient


class ByteResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}
        self.status = 200
        self.closed = False

    def read(self, maximum: int) -> bytes:
        return self.payload[:maximum]

    def close(self) -> None:
        self.closed = True


class SubtitleTests(unittest.TestCase):
    def test_search_normalizes_bounded_jellyfin_results(self):
        client = FakeClient(
            {
                "/RemoteSearch/Subtitles/": [
                    {
                        "Id": "sub-700",
                        "Name": "English {unsafe}",
                        "Author": "OpenSubtitles",
                        "Format": "srt",
                        "ThreeLetterISOLanguageName": "eng",
                        "IsHearingImpaired": True,
                        "IsHashMatch": True,
                        "CommunityRating": 99,
                    },
                    {
                        "Id": "https://attacker.invalid/subtitle",
                        "Name": "Bad result",
                    },
                ]
            }
        )
        document = subtitles_module.search_subtitles(client, EP1, "EN")
        self.assertEqual(document["language"], "en")
        self.assertEqual(len(document["items"]), 1)
        item = document["items"][0]
        self.assertEqual(item["key"], "sub-700")
        self.assertEqual(item["label"], "English unsafe")
        self.assertTrue(item["hearingImpaired"])
        self.assertTrue(item["perfectMatch"])
        self.assertEqual(item["score"], 99)
        self.assertIn("/RemoteSearch/Subtitles/en", client.paths[0])

        with self.assertRaises(ConfigurationError):
            subtitles_module.search_subtitles(client, "../42", "en")
        with self.assertRaises(ConfigurationError):
            subtitles_module.search_subtitles(client, EP1, "english")

    def test_download_uses_post_and_private_player_directory(self):
        client = mock.Mock()
        response = ByteResponse(b"1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        client.open.return_value = response
        with tempfile.TemporaryDirectory(
            prefix="omajelly-player-", dir="/tmp"
        ) as directory:
            result = subtitles_module.download_subtitle(
                client,
                EP1,
                "sub-700",
                "srt",
                directory,
            )
            output = Path(result["path"])
            self.assertEqual(output.name, "subtitle-sub-700.srt")
            self.assertEqual(output.read_bytes(), response.payload)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(output.parent, Path(directory))
        client.open.assert_called_once()
        self.assertEqual(client.open.call_args.kwargs["method"], HttpMethod.POST)
        self.assertTrue(response.closed)

        with (
            tempfile.TemporaryDirectory() as unsafe_directory,
            self.assertRaises(ConfigurationError),
        ):
            subtitles_module.download_subtitle(
                client,
                EP1,
                "sub-700",
                "srt",
                unsafe_directory,
            )

        with self.assertRaises(ConfigurationError):
            subtitles_module.download_subtitle(
                client, EP1, "../secret", "srt", "/tmp/omajelly-player-x"
            )

    def test_player_arguments_load_search_script_without_a_token(self):
        args = playback_module.mpv_playlist_arguments(
            PlaybackMode.WINDOWED,
            [("http://127.0.0.1:32000/stream/item", 0, [])],
            "/tmp/omajelly-player-test/mpv.sock",
            None,
            "/plugin/assets/omajelly_subtitles.lua",
            "/plugin/bin/omajelly",
            [EP1],
            "nl",
            "/tmp/omajelly-player-test",
        )
        joined = " ".join(args)
        self.assertIn("--script=/plugin/assets/omajelly_subtitles.lua", args)
        self.assertIn("--script-opt=omajelly_subtitles-language=nl", args)
        self.assertIn("--script-opt=omajelly_subtitles-rating_keys=" + EP1, args)
        self.assertNotIn(TOKEN, joined)
        self.assertNotIn("X-Emby-Token", joined)

        parsed = cli_module.parser().parse_args(
            ["subtitle-search", "--rating-key", EP1, "--language", "en"]
        )
        self.assertEqual(parsed.command, "subtitle-search")
        self.assertEqual(parsed.language, "en")
