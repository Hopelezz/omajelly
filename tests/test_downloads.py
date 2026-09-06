from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omajelly.common import ConfigurationError
from omajelly.downloads import (
    DEFAULT_DOWNLOAD_CACHE_BYTES,
    downloads_document,
    media_path,
    queue_download,
    remove_download,
    set_download_limit,
    sync_downloads,
)
from omajelly.playback import PlaybackItem
from tests.support import MOVIE, TOKEN, movie


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200, length: int | None = None):
        self._payload = payload
        self._offset = 0
        self.status = status
        self.headers = {"Content-Length": str(len(payload) if length is None else length)}

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            chunk = self._payload[self._offset :]
            self._offset = len(self._payload)
            return chunk
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


class DownloadTests(unittest.TestCase):
    def test_queue_and_sync_keep_the_token_out_of_the_index(self):
        payload = b"jellyfin-media-bytes"
        item = movie(MOVIE, "Cached Film")
        playback = PlaybackItem(
            rating_key=MOVIE,
            media_type="movie",
            stream_path="/Videos/" + MOVIE + "/stream?Static=true&MediaSourceId=src",
            media_source_id="src",
            play_session_id="session",
            resume_seconds=0,
            duration_ms=1000,
            subtitle_paths=(),
        )
        client = mock.Mock()
        client.open.return_value = FakeResponse(payload)
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(directory) / "config"),
                        "XDG_CACHE_HOME": str(Path(directory) / "cache"),
                    },
                    clear=False,
                ),
                mock.patch(
                    "omajelly.downloads.client_from_saved",
                    return_value=(client, {"server": "http://jellyfin:8096"}),
                ),
                mock.patch("omajelly.downloads.fetch_item", return_value=item),
                mock.patch(
                    "omajelly.downloads.fetch_playback_info",
                    return_value={"MediaSources": [{"Id": "src", "Size": len(payload)}]},
                ),
                mock.patch(
                    "omajelly.downloads.playback_item_from_info",
                    return_value=playback,
                ),
            ):
                queued = queue_download(MOVIE)
                self.assertEqual(queued["items"][0]["ratingKey"], MOVIE)
                self.assertEqual(queued["items"][0]["downloadState"], "queued")
                self.assertEqual(queued["items"][0]["addedLabel"], "")
                self.assertEqual(queued["items"][0]["playbackHint"], "Queued")
                synced = sync_downloads()
                self.assertEqual(synced["items"][0]["downloadState"], "ready")
                self.assertEqual(synced["items"][0]["addedLabel"], "")
                self.assertEqual(synced["items"][0]["playbackHint"], "Ready")
                self.assertEqual(media_path(MOVIE).read_bytes(), payload)
                index = json.loads(
                    (
                        Path(directory)
                        / "config"
                        / "omajelly"
                        / "downloads.json"
                    ).read_text(encoding="utf-8")
                )
                dumped = json.dumps(index)
                self.assertNotIn(TOKEN, dumped)
                self.assertNotIn("X-Emby-Token", dumped)
                listed = downloads_document()
                self.assertEqual(listed["usedBytes"], len(payload))
                self.assertEqual(listed["maxBytes"], DEFAULT_DOWNLOAD_CACHE_BYTES)
                limited = set_download_limit(5)
                self.assertEqual(limited["maxBytes"], 5 * 1024 * 1024 * 1024)
                with self.assertRaises(ConfigurationError):
                    set_download_limit(3)
                removed = remove_download(MOVIE)
                self.assertEqual(removed["items"], [])
                self.assertFalse(media_path(MOVIE).exists())
