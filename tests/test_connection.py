from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omajelly import connection as connection_module
from omajelly.activity import cache_home, save_snapshot
from omajelly.client import JellyfinClient, validate_origin
from omajelly.common import AuthenticationError, ConfigurationError, ResponseError, isoformat
from omajelly.config import config_home, load_config, save_config, validate_config
from omajelly.connection import (
    clear_configuration,
    configure_connection,
    parse_env_file,
    read_setup,
)
from omajelly.constants import MAX_SETUP_BYTES
from tests.support import MOVIE_LIB, NOW, SHOW_LIB, TOKEN, USER, FakeStore


LIBRARIES = [
    {"id": MOVIE_LIB, "type": "movie", "title": "Movies"},
    {"id": SHOW_LIB, "type": "show", "title": "TV Shows"},
    {"id": "99999999999999999999999999999999", "type": "artist", "title": "Music"},
]
SNAPSHOT = {
    "schemaVersion": 1,
    "configured": True,
    "sourceState": "updated",
    "stale": False,
    "items": [],
    "continueItems": [],
    "movieItems": [],
    "seriesItems": [],
    "newCount": 0,
    "lastSuccessAt": isoformat(NOW),
    "error": "",
}
SAMPLE_CONFIG = {
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


class JellyfinConnectionTests(unittest.TestCase):
    def test_setup_input_is_bounded_and_strict(self):
        setup = read_setup(
            io.BytesIO(
                json.dumps(
                    {
                        "server": "http://jellyfin:8096",
                        "username": "demo",
                        "password": "secret",
                        "token": "",
                    }
                ).encode()
                + b"\n"
            )
        )
        self.assertEqual(setup["server"], "http://jellyfin:8096")
        self.assertEqual(setup["username"], "demo")
        self.assertEqual(setup["password"], "secret")
        with self.assertRaises(ConfigurationError):
            read_setup(io.BytesIO(b'{"server":"http://jellyfin:8096","extra":true}\n'))
        with self.assertRaises(ConfigurationError):
            read_setup(io.BytesIO(b"x" * (MAX_SETUP_BYTES + 1)))

    def test_configure_discovers_libraries_and_saves_secret(self):
        client = mock.Mock()
        client.fetch_user.return_value = {"id": USER, "name": "demo"}
        client.discover.return_value = (LIBRARIES, USER, "Living Room")
        store = FakeStore()
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
            mock.patch.object(connection_module, "JellyfinClient", return_value=client),
            mock.patch.object(
                connection_module, "recent_snapshot", return_value=SNAPSHOT
            ),
        ):
            document = configure_connection(
                {
                    "server": "http://jellyfin:8096",
                    "token": TOKEN,
                    "username": "",
                    "password": "",
                },
                store,
            )
            config = load_config()
        self.assertEqual(store.stored, [TOKEN])
        self.assertEqual(config["movieSectionIds"], [MOVIE_LIB])
        self.assertEqual(config["tvSectionIds"], [SHOW_LIB])
        self.assertEqual(config["serverName"], "Living Room")
        self.assertEqual(document["connection"]["authMode"], "token")
        self.assertNotIn(TOKEN, json.dumps(document))
        self.assertNotIn("secret", json.dumps(document))

    def test_configure_username_password_never_lands_in_config(self):
        client = mock.Mock()
        client.discover.return_value = (LIBRARIES, USER, "Living Room")
        store = FakeStore()
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
            mock.patch.object(
                connection_module,
                "authenticate",
                return_value=(TOKEN, USER, "demo"),
            ),
            mock.patch.object(connection_module, "JellyfinClient", return_value=client),
            mock.patch.object(
                connection_module, "recent_snapshot", return_value=SNAPSHOT
            ),
        ):
            document = configure_connection(
                {
                    "server": "http://jellyfin:8096",
                    "username": "demo",
                    "password": "hunter2",
                    "token": "",
                },
                store,
            )
            config = load_config()
        self.assertEqual(store.stored, [TOKEN])
        self.assertEqual(config["authMode"], "password")
        dumped = json.dumps(document) + json.dumps(config)
        self.assertNotIn("hunter2", dumped)
        self.assertNotIn(TOKEN, dumped)

    def test_failed_connection_test_keeps_existing_settings(self):
        store = FakeStore("existingToken_1234")
        client = mock.Mock()
        client.fetch_user.side_effect = AuthenticationError(
            "Jellyfin rejected the configured token"
        )
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
            save_config(SAMPLE_CONFIG)
            with (
                mock.patch.object(
                    connection_module, "JellyfinClient", return_value=client
                ),
                self.assertRaises(AuthenticationError),
            ):
                configure_connection(
                    {
                        "server": "http://jellyfin:8097",
                        "token": "badToken_12345",
                        "username": "",
                        "password": "",
                    },
                    store,
                )
            self.assertEqual(load_config(), SAMPLE_CONFIG)
        self.assertEqual(store.token, "existingToken_1234")
        self.assertEqual(store.stored, [])

    def test_clear_configuration_removes_files_and_secret(self):
        store = FakeStore(TOKEN)
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
            save_config(SAMPLE_CONFIG)
            save_snapshot(
                {
                    "schemaVersion": 1,
                    "configured": True,
                    "sourceState": "empty",
                    "stale": True,
                    "items": [],
                    "continueItems": [],
                    "movieItems": [],
                    "seriesItems": [],
                    "newCount": 0,
                    "lastSuccessAt": isoformat(NOW),
                    "error": "",
                }
            )
            document = clear_configuration(store)
            self.assertFalse((config_home() / "config.json").exists())
            self.assertFalse((cache_home() / "recent.json").exists())
        self.assertTrue(store.cleared)
        self.assertFalse(document["configured"])
        self.assertEqual(document["connection"]["server"], "")

    def test_config_rejects_web_client_url_and_bad_sections(self):
        self.assertEqual(validate_origin("http://media/jellyfin"), "http://media/jellyfin")
        self.assertEqual(
            validate_origin("http://media/jellyfin/"), "http://media/jellyfin"
        )
        with self.assertRaises(ConfigurationError):
            validate_origin("http://jellyfin:8096/web")
        with self.assertRaises(ConfigurationError):
            validate_origin("http://media/jellyfin/web")
        with self.assertRaises(ConfigurationError):
            validate_origin("http://user:pass@media/jellyfin")
        client = JellyfinClient("http://media/jellyfin", "", "")
        self.assertEqual(
            client.url("/QuickConnect/Initiate"),
            "http://media/jellyfin/QuickConnect/Initiate",
        )
        with self.assertRaises(ResponseError):
            client.url("/../secret")
        with self.assertRaises(ConfigurationError):
            validate_config(
                {
                    "schemaVersion": 1,
                    "server": "http://jellyfin:8096",
                    "movieSectionIds": ["../3"],
                    "tvSectionIds": [],
                    "userId": USER,
                }
            )

    def test_env_parser_does_not_execute_shell_text(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            marker = Path(directory) / "executed"
            env_file.write_text(
                "JELLYFIN_BASE_URL=http://jellyfin:8096\n"
                "JELLYFIN_TOKEN='safeToken_123456'\n"
                "JELLYFIN_USERNAME=demo\n"
                "UNRELATED=$(touch " + str(marker) + ")\n",
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            values = parse_env_file(env_file)
            self.assertEqual(values["JELLYFIN_TOKEN"], "safeToken_123456")
            self.assertFalse(marker.exists())
