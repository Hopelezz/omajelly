from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Any

from omajelly.client import validate_origin
from omajelly.common import (
    ConfigurationError,
    ResponseError,
    atomic_json_write,
    clean_text,
    read_json_file,
    run_bounded_output,
    run_no_output,
)
from omajelly.constants import (
    MAX_CONFIG_BYTES,
    MAX_GEOMETRY_BYTES,
    MAX_SECTIONS,
    MAX_TOKEN_BYTES,
    PLUGIN_ID,
    SCHEMA_VERSION,
)
from omajelly.ids import valid_client_id, valid_item_id, valid_token

AUTH_MODE_PASSWORD = "password"
AUTH_MODE_TOKEN = "token"
AUTH_MODE_QUICKCONNECT = "quickconnect"


def config_home() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "omajelly"


def section_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_SECTIONS:
        raise ConfigurationError("Jellyfin library selection is invalid")
    result: list[str] = []
    for raw in value:
        item = valid_item_id(raw)
        if item not in result:
            result.append(item)
    return result


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ConfigurationError("Omajelly is not configured")
    movies = section_ids(value.get("movieSectionIds") or [])
    shows = section_ids(value.get("tvSectionIds") or [])
    if not movies and not shows:
        raise ConfigurationError("Select at least one movie or TV library")
    user_id = valid_item_id(value.get("userId"))
    user_name = clean_text(value.get("userName"), 128)
    server_name = clean_text(value.get("serverName"), 128)
    auth_mode = str(value.get("authMode") or AUTH_MODE_TOKEN)
    if auth_mode not in {AUTH_MODE_PASSWORD, AUTH_MODE_TOKEN, AUTH_MODE_QUICKCONNECT}:
        raise ConfigurationError("The saved Jellyfin authentication method is invalid")
    client_identifier = valid_client_id(
        value.get("clientIdentifier") or secrets.token_hex(16)
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "server": validate_origin(value.get("server")),
        "movieSectionIds": movies,
        "tvSectionIds": shows,
        "userId": user_id,
        "userName": user_name,
        "serverName": server_name,
        "authMode": auth_mode,
        "clientIdentifier": client_identifier,
    }


def load_config() -> dict[str, Any] | None:
    value = read_json_file(config_home() / "config.json", MAX_CONFIG_BYTES)
    return None if value is None else validate_config(value)


def save_config(config: dict[str, Any]) -> None:
    atomic_json_write(
        config_home() / "config.json", validate_config(config), MAX_CONFIG_BYTES
    )


def new_client_identifier() -> str:
    return secrets.token_hex(16)


def validate_window_geometry(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ResponseError("Saved player geometry has an unsupported format")
    result: dict[str, int] = {"schemaVersion": SCHEMA_VERSION}
    limits = {
        "x": (-100000, 100000),
        "y": (-100000, 100000),
        "width": (160, 16384),
        "height": (90, 16384),
    }
    for name, (minimum, maximum) in limits.items():
        raw = value.get(name)
        if (
            isinstance(raw, bool)
            or not isinstance(raw, int)
            or raw < minimum
            or raw > maximum
        ):
            raise ResponseError("Saved player geometry is invalid")
        result[name] = raw
    return result


def load_window_geometry() -> dict[str, int] | None:
    value = read_json_file(config_home() / "player-window.json", MAX_GEOMETRY_BYTES)
    return None if value is None else validate_window_geometry(value)


def save_window_geometry(value: dict[str, int]) -> None:
    atomic_json_write(
        config_home() / "player-window.json",
        validate_window_geometry(value),
        MAX_GEOMETRY_BYTES,
    )


class SecretStore:
    attributes = ("service", PLUGIN_ID)
    label = "Omajelly token"
    maximum = MAX_TOKEN_BYTES
    description = "Jellyfin token"

    def validate(self, value: str) -> str:
        return valid_token(value)

    def lookup(self) -> str | None:
        try:
            return_code, output = run_bounded_output(
                ["secret-tool", "lookup", *self.attributes],
                maximum=self.maximum + 1,
                timeout=10,
            )
        except FileNotFoundError as error:
            raise ConfigurationError(
                "The desktop secret service is unavailable"
            ) from error
        if return_code != 0:
            return None
        try:
            token = output.decode("utf-8").rstrip("\n")
        except UnicodeDecodeError as error:
            raise ConfigurationError(
                "The saved " + self.description + " is invalid"
            ) from error
        if not token:
            return None
        try:
            return self.validate(token)
        except ConfigurationError as error:
            raise ConfigurationError(
                "The saved " + self.description + " is invalid"
            ) from error

    def store(self, token: str) -> None:
        token = self.validate(token)
        try:
            return_code = run_no_output(
                ["secret-tool", "store", "--label=" + self.label, *self.attributes],
                input_bytes=token.encode("utf-8"),
                timeout=15,
            )
        except FileNotFoundError as error:
            raise ConfigurationError(
                "The desktop secret service is unavailable"
            ) from error
        if return_code != 0:
            raise ConfigurationError(
                "The desktop secret service could not save the " + self.description
            )

    def clear(self) -> None:
        try:
            return_code = run_no_output(
                ["secret-tool", "clear", *self.attributes],
                timeout=10,
            )
        except FileNotFoundError as error:
            raise ConfigurationError(
                "The desktop secret service is unavailable"
            ) from error
        if return_code not in {0, 1}:
            raise ConfigurationError(
                "The desktop secret service could not clear the " + self.description
            )


class PendingQuickConnectStore(SecretStore):
    attributes = ("service", PLUGIN_ID, "kind", "pending-quick-connect")
    label = "Omajelly Quick Connect"
    maximum = 256
    description = "Quick Connect secret"

    def validate(self, value: str) -> str:
        secret = str(value or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]{8,256}", secret):
            raise ConfigurationError("The Quick Connect secret has an invalid format")
        return secret
