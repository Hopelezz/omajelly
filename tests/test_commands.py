from __future__ import annotations

import unittest
from unittest import mock

from omajelly import commands as commands_module
from omajelly.client import HttpMethod
from omajelly.commands import command_refresh, scan_libraries
from tests.support import MOVIE_LIB, SHOW_LIB, USER


class JellyfinCommandTests(unittest.TestCase):
    def test_refresh_backfills_and_returns_the_server_name(self):
        client = mock.Mock()
        client.fetch_server_name.return_value = "Living Room"
        config = {
            "schemaVersion": 1,
            "server": "http://jellyfin:8096",
            "serverName": "",
            "movieSectionIds": [MOVIE_LIB],
            "tvSectionIds": [SHOW_LIB],
            "userId": USER,
            "userName": "demo",
            "authMode": "token",
            "clientIdentifier": "omajellyclientid01",
        }
        snapshot = {
            "schemaVersion": 1,
            "configured": True,
            "sourceState": "updated",
            "stale": False,
            "items": [],
            "continueItems": [],
            "movieItems": [],
            "seriesItems": [],
            "newCount": 0,
            "lastSuccessAt": "2026-08-25T12:00:00Z",
            "error": "",
        }
        with (
            mock.patch.object(
                commands_module, "client_from_saved", return_value=(client, config)
            ),
            mock.patch.object(
                commands_module, "recent_snapshot", return_value=snapshot
            ),
            mock.patch.object(commands_module, "save_config") as save_config,
            mock.patch.object(commands_module, "save_snapshot"),
            mock.patch.object(commands_module, "print_json") as print_json,
        ):
            self.assertEqual(command_refresh(), 0)
        self.assertEqual(save_config.call_args.args[0]["serverName"], "Living Room")
        self.assertEqual(
            print_json.call_args.args[0]["connection"]["serverName"],
            "Living Room",
        )

    def test_scan_posts_library_refresh_and_reports_accepted(self):
        client = mock.Mock()
        client.discover.return_value = (
            [
                {"id": MOVIE_LIB, "type": "movie", "title": "Films"},
                {"id": SHOW_LIB, "type": "show", "title": "Television"},
            ],
            USER,
            "Living Room",
        )
        result = scan_libraries(client)
        self.assertEqual(result["accepted"], True)
        self.assertEqual(result["sectionCount"], 2)
        self.assertEqual(result["movieSections"], 1)
        self.assertEqual(result["seriesSections"], 1)
        client.request_empty.assert_called_once_with(
            "/Library/Refresh", method=HttpMethod.POST
        )
