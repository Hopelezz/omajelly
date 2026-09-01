from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omajelly import common as common_module
from omajelly.common import ResponseError, atomic_json_write, read_json_file


class SecureLocalStateTests(unittest.TestCase):
    def test_atomic_write_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            redirected = root / "redirected"
            redirected.mkdir(mode=0o700)
            (root / "state").symlink_to(redirected, target_is_directory=True)

            with self.assertRaises(ResponseError):
                atomic_json_write(root / "state" / "config.json", {"ok": True}, 1024)

            self.assertFalse((redirected / "config.json").exists())

    def test_private_read_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            redirected = root / "redirected"
            redirected.mkdir(mode=0o700)
            target = redirected / "config.json"
            target.write_text('{"ok":true}\n', encoding="utf-8")
            target.chmod(0o600)
            (root / "state").symlink_to(redirected, target_is_directory=True)

            with self.assertRaises(ResponseError):
                read_json_file(root / "state" / "config.json", 1024)

    def test_atomic_write_rejects_unsafe_existing_parent_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "state"
            parent.mkdir()
            parent.chmod(0o777)

            with self.assertRaises(ResponseError):
                atomic_json_write(parent / "config.json", {"ok": True}, 1024)

            self.assertEqual(os.stat(parent).st_mode & 0o777, 0o777)
            self.assertFalse((parent / "config.json").exists())

    def test_private_read_rejects_exposed_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.json"
            target.write_text('{"ok":true}\n', encoding="utf-8")
            target.chmod(0o644)

            with self.assertRaises(ResponseError):
                read_json_file(target, 1024)

    def test_atomic_write_stays_bound_to_opened_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            held = root / "held"
            state.mkdir(mode=0o700)
            target = state / "config.json"
            real_open_parent = common_module.secure_parent_directory

            @contextlib.contextmanager
            def replace_path_after_open(path, *, create, private):
                with real_open_parent(path, create=create, private=private) as opened:
                    state.rename(held)
                    state.mkdir(mode=0o700)
                    yield opened

            with mock.patch.object(
                common_module,
                "secure_parent_directory",
                replace_path_after_open,
            ):
                atomic_json_write(target, {"destination": "held"}, 1024)

            self.assertEqual(
                read_json_file(held / "config.json", 1024),
                {"destination": "held"},
            )
            self.assertFalse((state / "config.json").exists())

    def test_private_read_stays_bound_to_opened_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            held = root / "held"
            state.mkdir(mode=0o700)
            target = state / "config.json"
            target.write_text('{"source":"held"}\n', encoding="utf-8")
            target.chmod(0o600)
            real_open_parent = common_module.secure_parent_directory

            @contextlib.contextmanager
            def replace_path_after_open(path, *, create, private):
                with real_open_parent(path, create=create, private=private) as opened:
                    state.rename(held)
                    state.mkdir(mode=0o700)
                    replacement = state / "config.json"
                    replacement.write_text(
                        '{"source":"replacement"}\n', encoding="utf-8"
                    )
                    replacement.chmod(0o600)
                    yield opened

            with mock.patch.object(
                common_module,
                "secure_parent_directory",
                replace_path_after_open,
            ):
                value = read_json_file(target, 1024)

            self.assertEqual(value, {"source": "held"})
