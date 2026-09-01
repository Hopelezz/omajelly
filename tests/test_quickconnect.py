from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from omajelly.client import HttpMethod
from omajelly.common import AuthenticationError, ConfigurationError, ResponseError
from omajelly.constants import SCHEMA_VERSION
from omajelly.quickconnect import (
    cancel_quick_connect,
    load_pending,
    poll_quick_connect,
    save_pending,
    start_quick_connect,
)
from tests.support import TOKEN, USER, FakeStore


COMPLETED = {
    "schemaVersion": SCHEMA_VERSION,
    "configured": True,
    "sourceState": "updated",
    "stale": False,
    "items": [],
    "continueItems": [],
    "movieItems": [],
    "seriesItems": [],
    "newCount": 0,
    "lastSuccessAt": "2026-08-24T12:00:00Z",
    "error": "",
    "connection": {
        "server": "http://jellyfin:8096",
        "serverName": "Living Room",
        "movieLibraries": [],
        "seriesLibraries": [],
        "authMode": "quickconnect",
    },
}


class QuickConnectTests(unittest.TestCase):
    def test_start_returns_code_and_never_exposes_secret(self):
        client = mock.Mock()
        client.request_json.return_value = {
            "Authenticated": False,
            "Secret": "qc-secret-stay-private",
            "Code": "847291",
        }
        store = FakeStore()
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                clear=False,
            ),
            mock.patch(
                "omajelly.quickconnect.JellyfinClient", return_value=client
            ),
        ):
            document = start_quick_connect("http://jellyfin:8096", store)
            pending = load_pending()
        dumped = json.dumps(document) + json.dumps(pending)
        self.assertEqual(document["state"], "pending")
        self.assertEqual(document["code"], "847291")
        self.assertEqual(set(document), {"state", "code"})
        self.assertEqual(store.token, "qc-secret-stay-private")
        self.assertEqual(pending["code"], "847291")
        self.assertNotIn("secret", pending)
        self.assertNotIn("qc-secret-stay-private", dumped)
        self.assertEqual(
            client.request_json.call_args.kwargs["method"], HttpMethod.POST
        )

    def test_poll_waits_then_completes_without_leaking_secret(self):
        pending_store = FakeStore("qc-secret-stay-private")
        token_store = FakeStore()
        client = mock.Mock()
        client.request_json.side_effect = [
            {"Authenticated": False, "Code": "847291"},
            {"Authenticated": True, "Code": "847291"},
        ]
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
            mock.patch(
                "omajelly.quickconnect.JellyfinClient", return_value=client
            ),
            mock.patch(
                "omajelly.quickconnect.authenticate_with_quick_connect",
                return_value=(TOKEN, USER, "demo"),
            ) as authenticate,
            mock.patch(
                "omajelly.connection.persist_authenticated_session",
                return_value=COMPLETED,
            ) as persist,
        ):
            save_pending(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "server": "http://jellyfin:8096",
                    "code": "847291",
                    "clientIdentifier": "omajellyclientid01",
                    "createdAt": int(time.time()),
                }
            )
            waiting = poll_quick_connect(pending_store, token_store)
            finished = poll_quick_connect(pending_store, token_store)
        self.assertEqual(waiting, {"state": "pending", "code": "847291"})
        self.assertNotIn("qc-secret-stay-private", json.dumps(waiting))
        self.assertEqual(finished["connection"]["authMode"], "quickconnect")
        self.assertNotIn("qc-secret-stay-private", json.dumps(finished))
        authenticate.assert_called_once()
        self.assertEqual(authenticate.call_args.args[1], "qc-secret-stay-private")
        persist.assert_called_once()
        self.assertIsNone(load_pending())
        self.assertTrue(pending_store.cleared)

    def test_cancel_clears_pending_secret(self):
        store = FakeStore("qc-secret-stay-private")
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                clear=False,
            ),
        ):
            save_pending(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "server": "http://jellyfin:8096",
                    "code": "111111",
                    "clientIdentifier": "omajellyclientid01",
                    "createdAt": int(time.time()),
                }
            )
            document = cancel_quick_connect(store)
            self.assertEqual(document["state"], "cancelled")
            self.assertIsNone(load_pending())
        self.assertTrue(store.cleared)

    def test_pending_state_rejects_embedded_secrets(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
            clear=False,
        ):
            from omajelly.common import atomic_json_write
            from omajelly.constants import MAX_PENDING_BYTES
            from omajelly.quickconnect import pending_path

            atomic_json_write(
                pending_path(),
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "server": "http://jellyfin:8096",
                    "code": "111111",
                    "clientIdentifier": "omajellyclientid01",
                    "createdAt": int(time.time()),
                    "secret": "qc-secret-stay-private",
                },
                MAX_PENDING_BYTES,
            )
            with self.assertRaises(ConfigurationError):
                load_pending()

    def test_initiate_falls_back_to_get_when_post_is_rejected(self):
        client = mock.Mock()
        client.request_json.side_effect = [
            ResponseError("Jellyfin returned HTTP 405"),
            {
                "Authenticated": False,
                "Secret": "qc-secret-stay-private",
                "Code": "123456",
            },
        ]
        store = FakeStore()
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                clear=False,
            ),
            mock.patch(
                "omajelly.quickconnect.JellyfinClient", return_value=client
            ),
        ):
            document = start_quick_connect("http://jellyfin:8096", store)
        self.assertEqual(document["code"], "123456")
        self.assertEqual(store.token, "qc-secret-stay-private")
        self.assertEqual(client.request_json.call_count, 2)
        self.assertEqual(
            client.request_json.call_args_list[1].args[0], "/QuickConnect/Initiate"
        )
        self.assertNotIn("method", client.request_json.call_args_list[1].kwargs)

    def test_disabled_quick_connect_is_a_configuration_error(self):
        client = mock.Mock()
        client.request_json.side_effect = AuthenticationError("rejected")
        store = FakeStore()
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                clear=False,
            ),
            mock.patch(
                "omajelly.quickconnect.JellyfinClient", return_value=client
            ),
        ):
            with self.assertRaises(ConfigurationError) as ctx:
                start_quick_connect("http://jellyfin:8096", store)
        self.assertIn("disabled", str(ctx.exception).lower())
        self.assertIsNone(store.token)
