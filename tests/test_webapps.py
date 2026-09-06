from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omajelly.common import ConfigurationError
from omajelly.config import config_home
from omajelly.constants import SCHEMA_VERSION
from omajelly.webapps import (
    WEBAPP_NAME,
    install_jellyfin_webapp,
    launch_jellyfin_webapp,
    mark_created_webapp,
    prepare_autoplay_extension,
    remove_created_jellyfin_webapp,
    webapp_status,
)
from tests.support import TOKEN

_LAUNCH_ARGV = [
    "systemd-run",
    "--user",
    "--collect",
    "--quiet",
    "--no-block",
    "--",
    "omarchy-launch-webapp",
    "http://jellyfin:8096/web/",
]


class WebappTests(unittest.TestCase):
    def test_install_uses_omarchy_app_window_without_the_token(self):
        config = {"server": "http://jellyfin:8096"}
        desktop = (
            "[Desktop Entry]\nName=Jellyfin\n"
            'Exec=omarchy-launch-webapp "http://jellyfin:8096/web/"\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            applications = Path(directory) / "share" / "applications"
            applications.mkdir(parents=True)
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(directory) / "config"),
                        "XDG_DATA_HOME": str(Path(directory) / "share"),
                    },
                    clear=False,
                ),
                mock.patch(
                    "omajelly.webapps.load_config", return_value=config
                ),
                mock.patch(
                    "omajelly.webapps.resolve_tool", side_effect=lambda name: name
                ),
                mock.patch("omajelly.webapps.run_no_output") as command,
                mock.patch("omajelly.webapps.launch_detached") as launcher,
            ):
                def fake_install(*args, **kwargs):
                    (applications / "Jellyfin.desktop").write_text(
                        desktop, encoding="utf-8"
                    )
                    return 0

                command.side_effect = fake_install
                result = install_jellyfin_webapp(launch=True)
                self.assertTrue(result["created"])
                self.assertTrue(result["launched"])
                self.assertTrue(result["createdByOmajelly"])
                argv = command.call_args.args[0]
                self.assertEqual(argv[0], "omarchy-webapp-install")
                self.assertEqual(argv[1], "Jellyfin")
                self.assertEqual(argv[2], "http://jellyfin:8096/web/")
                self.assertEqual(len(argv), 4)
                self.assertNotIn(TOKEN, " ".join(argv))
                self.assertNotIn("X-Emby-Token", " ".join(argv))
                launcher.assert_called_once_with(_LAUNCH_ARGV, env=mock.ANY)
                marker = json.loads(
                    (config_home() / "created-webapp.json").read_text(encoding="utf-8")
                )
                self.assertEqual(marker["name"], WEBAPP_NAME)
                self.assertEqual(marker["schemaVersion"], SCHEMA_VERSION)

    def test_install_upgrades_xdg_open_and_launches_app_window(self):
        config = {"server": "http://jellyfin:8096"}
        old = (
            "[Desktop Entry]\nName=Jellyfin\n"
            "Exec=xdg-open http://jellyfin:8096/web/\n"
        )
        upgraded = (
            "[Desktop Entry]\nName=Jellyfin\n"
            'Exec=omarchy-launch-webapp "http://jellyfin:8096/web/"\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            applications = Path(directory) / "share" / "applications"
            applications.mkdir(parents=True)
            desktop = applications / "Jellyfin.desktop"
            desktop.write_text(old, encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(directory) / "config"),
                        "XDG_DATA_HOME": str(Path(directory) / "share"),
                    },
                    clear=False,
                ),
                mock.patch(
                    "omajelly.webapps.load_config", return_value=config
                ),
                mock.patch(
                    "omajelly.webapps.resolve_tool", side_effect=lambda name: name
                ),
                mock.patch("omajelly.webapps.run_no_output") as command,
                mock.patch("omajelly.webapps.launch_detached") as launcher,
            ):
                mark_created_webapp(WEBAPP_NAME)

                def fake_install(*args, **kwargs):
                    desktop.write_text(upgraded, encoding="utf-8")
                    return 0

                command.side_effect = fake_install
                result = install_jellyfin_webapp(launch=True)
                self.assertTrue(result["created"])
                self.assertTrue(result["launched"])
                self.assertEqual(command.call_args.args[0][0], "omarchy-webapp-install")
                self.assertEqual(len(command.call_args.args[0]), 4)
                launcher.assert_called_once_with(_LAUNCH_ARGV, env=mock.ANY)

    def test_remove_only_deletes_a_webapp_omajelly_created(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.dict(
                    os.environ,
                    {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                    clear=False,
                ),
                mock.patch(
                    "omajelly.webapps.resolve_tool", side_effect=lambda name: name
                ),
                mock.patch("omajelly.webapps.run_no_output", return_value=0) as command,
            ):
                self.assertFalse(remove_created_jellyfin_webapp())
                command.assert_not_called()
                mark_created_webapp(WEBAPP_NAME)
                self.assertTrue(remove_created_jellyfin_webapp())
                argv = command.call_args.args[0]
                self.assertEqual(argv, ["omarchy-webapp-remove", "Jellyfin"])
                self.assertNotIn(TOKEN, " ".join(argv))
                self.assertFalse((config_home() / "created-webapp.json").exists())
                self.assertEqual(
                    command.call_args.kwargs["env"]["OMARCHY_REMOVE_NOTIFY"], "false"
                )

    def test_status_reports_missing_webapp(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(Path(directory) / "config"),
                    "XDG_DATA_HOME": str(Path(directory) / "share"),
                },
                clear=False,
            ), mock.patch("omajelly.webapps.load_config", return_value=None):
                self.assertEqual(
                    webapp_status(),
                    {"installed": False, "createdByOmajelly": False, "name": ""},
                )

    def test_launch_installs_the_webapp_before_opening_an_item(self):
        with (
            mock.patch("omajelly.webapps.install_jellyfin_webapp") as installer,
            mock.patch(
                "omajelly.webapps.resolve_tool",
                side_effect=lambda name: name,
            ),
            mock.patch(
                "omajelly.webapps.prepare_autoplay_extension",
                return_value=None,
            ),
            mock.patch("omajelly.webapps.launch_detached") as launcher,
        ):
            launch_jellyfin_webapp(
                "http://jellyfin:8096/web/#/details?id=12345678",
                ["--new-window"],
            )
        installer.assert_called_once_with()
        launcher.assert_called_once_with(
            [
                "systemd-run",
                "--user",
                "--collect",
                "--quiet",
                "--no-block",
                "--",
                "chromium",
                "--app=http://jellyfin:8096/web/#/details?id=12345678",
                "--new-window",
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--ozone-platform=x11",
            ],
            env=mock.ANY,
        )

    def test_autoplay_extension_matches_the_server_origin_without_the_token(self):
        url = "http://jellyfin:8096/web/#/details?id=" + TOKEN
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(Path(directory) / "config")},
                clear=False,
            ):
                extension = prepare_autoplay_extension(url)
                self.assertIsNotNone(extension)
                manifest = json.loads(
                    (extension / "manifest.json").read_text(encoding="utf-8")
                )
                matches = manifest["content_scripts"][0]["matches"]
                self.assertEqual(matches, ["http://jellyfin:8096/*"])
                self.assertNotIn(TOKEN, json.dumps(manifest))
                self.assertTrue((extension / "autoplay.js").is_file())

    def test_install_refuses_a_name_that_is_not_jellyfin(self):
        with self.assertRaises(ConfigurationError):
            mark_created_webapp("Evil/../path")
