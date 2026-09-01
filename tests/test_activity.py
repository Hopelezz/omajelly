from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from omajelly.activity import recent_snapshot, save_snapshot
from omajelly.common import (
    ResponseError,
    atomic_json_write,
    isoformat,
    read_regular_file,
)
from omajelly.config import save_config
from omajelly.connection import status_document
from omajelly.media_items import normalize_media_item
from tests.support import (
    EP1,
    EP2,
    EP3,
    MOVIE,
    MOVIE_B,
    MOVIE_C,
    MOVIE_LIB,
    NOW,
    SHOW,
    SHOW_LIB,
    USER,
    FakeClient,
    episode,
    items,
    movie,
)


class JellyfinActivityTests(unittest.TestCase):
    def test_normalizes_movie_and_watch_states(self):
        started = normalize_media_item(
            movie(
                MOVIE,
                "Dune: Part Two",
                year=2024,
                created=NOW - timedelta(days=2),
                position_ticks=120 * 10_000_000,
            ),
            NOW,
        )
        self.assertEqual(started["kind"], "movie")
        self.assertEqual(started["subtitle"], "Movie · 2024")
        self.assertEqual(started["watchState"], "started")
        self.assertFalse(started["isNew"])

        watched = normalize_media_item(
            movie(MOVIE_B, "Arrival", created=NOW, played=True),
            NOW,
        )
        self.assertEqual(watched["watchState"], "watched")
        self.assertFalse(watched["isNew"])

    def test_groups_recent_episodes_and_continue_watching(self):
        client = FakeClient(
            {
                "Items/Resume": items(
                    episode(
                        EP2,
                        "Continue show",
                        series_id=SHOW,
                        season=1,
                        index=3,
                        title="Episode",
                        created=NOW - timedelta(days=5),
                        position_ticks=30 * 10_000_000,
                        last_played=NOW - timedelta(hours=2),
                    ),
                    movie(
                        MOVIE_B,
                        "More recent viewing",
                        created=NOW - timedelta(days=10),
                        position_ticks=10 * 10_000_000,
                        last_played=NOW - timedelta(hours=1),
                    ),
                ),
                "IncludeItemTypes=Movie%2CEpisode": items(
                    movie(MOVIE, "Movie", created=NOW - timedelta(hours=2)),
                    episode(
                        EP3,
                        "Silo",
                        series_id=SHOW_LIB,
                        season=2,
                        index=2,
                        title="Order",
                        created=NOW - timedelta(hours=1),
                    ),
                    episode(
                        EP1,
                        "Silo",
                        series_id=SHOW_LIB,
                        season=2,
                        index=1,
                        title="The Engineer",
                        created=NOW - timedelta(hours=3),
                    ),
                ),
            }
        )
        snapshot = recent_snapshot(
            client,
            {
                "userId": USER,
                "movieSectionIds": [MOVIE_LIB],
                "tvSectionIds": [SHOW_LIB],
            },
            NOW,
        )
        self.assertEqual(
            [item["title"] for item in snapshot["items"]], ["Silo", "Movie"]
        )
        self.assertEqual(snapshot["items"][0]["subtitle"], "Show · S02E02 · Order")
        self.assertEqual(
            [item["ratingKey"] for item in snapshot["continueItems"]],
            [EP2, MOVIE_B],
        )
        self.assertEqual(snapshot["continueItems"][0]["playbackHint"], "Resume 30%")
        self.assertEqual(snapshot["continueItems"][1]["addedLabel"], "Played 1h ago")
        self.assertEqual(len(snapshot["movieItems"]), 1)
        self.assertEqual(len(snapshot["seriesItems"]), 1)
        self.assertEqual(snapshot["newCount"], 2)

    def test_new_requires_unwatched_and_thirty_day_window(self):
        recent = normalize_media_item(
            movie(MOVIE, "Recent", created=NOW - timedelta(days=30)),
            NOW,
        )
        old = normalize_media_item(
            movie(MOVIE_B, "Old", created=NOW - timedelta(days=31)),
            NOW,
        )
        self.assertTrue(recent["isNew"])
        self.assertFalse(old["isNew"])

    def test_unfinished_items_precede_newer_watched_items(self):
        client = FakeClient(
            {
                "Items/Resume": items(),
                "IncludeItemTypes=Movie%2CEpisode": items(
                    movie(MOVIE, "Newest watched", created=NOW, played=True),
                    movie(MOVIE_B, "Older unwatched", created=NOW - timedelta(days=1)),
                    movie(
                        MOVIE_C,
                        "Oldest started",
                        created=NOW - timedelta(days=2),
                        position_ticks=1000 * 10_000,
                    ),
                ),
            }
        )
        snapshot = recent_snapshot(
            client,
            {
                "userId": USER,
                "movieSectionIds": [MOVIE_LIB],
                "tvSectionIds": [],
            },
            NOW,
        )
        self.assertEqual(
            [item["watchState"] for item in snapshot["movieItems"]],
            ["started", "unwatched", "watched"],
        )

    def test_cache_is_atomic_private_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "recent.json"
            atomic_json_write(target, {"ok": True}, 1024)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")), {"ok": True}
            )
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            link = Path(directory) / "link.json"
            link.symlink_to(target)
            with self.assertRaises(ResponseError):
                read_regular_file(link, 1024)

    def test_saved_status_keeps_last_successful_items(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(Path(directory) / "config"),
                    "XDG_CACHE_HOME": str(Path(directory) / "cache"),
                },
                clear=False,
            ),
        ):
            save_config(
                {
                    "schemaVersion": 1,
                    "server": "http://jellyfin:8096",
                    "movieSectionIds": [MOVIE_LIB],
                    "tvSectionIds": [SHOW_LIB],
                    "userId": USER,
                    "userName": "demo",
                    "serverName": "Living Room",
                    "authMode": "token",
                    "clientIdentifier": "omajellyclientid01",
                }
            )
            snapshot = {
                "schemaVersion": 1,
                "configured": True,
                "sourceState": "updated",
                "stale": False,
                "items": [
                    {
                        "ratingKey": MOVIE,
                        "kind": "movie",
                        "title": "Saved",
                        "subtitle": "Movie",
                        "addedAt": isoformat(NOW),
                        "addedLabel": "Today",
                        "watchState": "unwatched",
                        "isNew": True,
                        "playbackRatingKey": MOVIE,
                        "playbackHint": "",
                    }
                ],
                "continueItems": [],
                "movieItems": [],
                "seriesItems": [],
                "newCount": 1,
                "lastSuccessAt": isoformat(NOW),
                "error": "",
            }
            save_snapshot(snapshot)
            status_doc = status_document()
            self.assertEqual(status_doc["items"][0]["title"], "Saved")
            self.assertEqual(status_doc["newCount"], 1)
