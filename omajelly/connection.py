from __future__ import annotations

import contextlib
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from omajelly.activity import cache_home, load_snapshot, recent_snapshot, save_snapshot
from omajelly.client import JellyfinClient, authenticate, validate_origin
from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    atomic_json_write,
    clean_text,
    read_regular_file,
    unlink_private_file,
)
from omajelly.config import (
    AUTH_MODE_PASSWORD,
    AUTH_MODE_TOKEN,
    SecretStore,
    config_home,
    load_config,
    new_client_identifier,
    save_config,
    valid_token,
    validate_config,
)
from omajelly.constants import (
    MAX_CACHE_BYTES,
    MAX_CONFIG_BYTES,
    MAX_ENV_BYTES,
    MAX_SETUP_BYTES,
    SCHEMA_VERSION,
)
from omajelly.ids import valid_item_id


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        payload = read_regular_file(path, MAX_ENV_BYTES, private=True).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError("The env file is not valid UTF-8") from error
    accepted = {
        "JELLYFIN_BASE_URL",
        "JELLYFIN_TOKEN",
        "JELLYFIN_USER_ID",
        "JELLYFIN_USERNAME",
        "JELLYFIN_PASSWORD",
    }
    values: dict[str, str] = {}
    for line in payload.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw = line.split("=", 1)
        name = name.strip()
        if name not in accepted:
            continue
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def _http_warning(server: str) -> str:
    if urllib.parse.urlsplit(server).scheme == "http":
        return (
            "Plain HTTP exposes Jellyfin traffic on the network; "
            "use it only on a trusted LAN."
        )
    return ""


def configure_from_env(path: Path, store: SecretStore | None = None) -> dict[str, Any]:
    values = parse_env_file(path)
    server = validate_origin(values.get("JELLYFIN_BASE_URL"))
    client_identifier = new_client_identifier()
    username = clean_text(values.get("JELLYFIN_USERNAME"), 128)
    password = values.get("JELLYFIN_PASSWORD", "")
    token = values.get("JELLYFIN_TOKEN", "")
    if username and password:
        token, user_id, user_name = authenticate(
            server, username, password, client_identifier
        )
        auth_mode = AUTH_MODE_PASSWORD
    else:
        try:
            token = valid_token(token)
        except ConfigurationError as error:
            raise ConfigurationError("JELLYFIN_TOKEN is missing or invalid") from error
        client = JellyfinClient(server, token, "", client_identifier=client_identifier)
        user = client.fetch_user()
        requested_user = values.get("JELLYFIN_USER_ID", "")
        if requested_user:
            user_id = valid_item_id(requested_user)
        else:
            user_id = user["id"]
        user_name = user["name"]
        auth_mode = AUTH_MODE_TOKEN
    client = JellyfinClient(server, token, user_id, client_identifier=client_identifier)
    libraries, discovered_user, server_name = client.discover()
    if discovered_user:
        user_id = discovered_user
    movies = [item["id"] for item in libraries if item["type"] == "movie"]
    shows = [item["id"] for item in libraries if item["type"] == "show"]
    config = validate_config(
        {
            "schemaVersion": SCHEMA_VERSION,
            "server": server,
            "movieSectionIds": movies,
            "tvSectionIds": shows,
            "userId": user_id,
            "userName": user_name,
            "serverName": server_name,
            "authMode": auth_mode,
            "clientIdentifier": client_identifier,
        }
    )
    (store or SecretStore()).store(token)
    save_config(config)
    return {
        "configured": True,
        "server": server,
        "serverName": server_name,
        "movieLibraries": [item for item in libraries if item["id"] in movies],
        "tvLibraries": [item for item in libraries if item["id"] in shows],
        "warning": _http_warning(server),
    }


def read_setup(stream: Any | None = None) -> dict[str, str]:
    source = stream or sys.stdin.buffer
    raw = source.readline(MAX_SETUP_BYTES + 1)
    if len(raw) > MAX_SETUP_BYTES:
        raise ConfigurationError("Setup input exceeded the size limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError("Setup input is not valid JSON") from error
    if not isinstance(value, dict) or set(value) - {
        "server",
        "token",
        "username",
        "password",
    }:
        raise ConfigurationError("Setup input is invalid")
    return {
        "server": str(value.get("server") or ""),
        "token": str(value.get("token") or ""),
        "username": str(value.get("username") or ""),
        "password": str(value.get("password") or ""),
    }


def connection_info(
    config: dict[str, Any] | None, libraries: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    if config is None:
        return {
            "server": "",
            "serverName": "",
            "movieLibraries": [],
            "seriesLibraries": [],
            "authMode": "",
        }
    values = libraries or []
    movies = [
        {"id": item["id"], "title": clean_text(item.get("title"), 128)}
        for item in values
        if item.get("type") == "movie" and item.get("id") in config["movieSectionIds"]
    ]
    shows = [
        {"id": item["id"], "title": clean_text(item.get("title"), 128)}
        for item in values
        if item.get("type") == "show" and item.get("id") in config["tvSectionIds"]
    ]
    if not values:
        movies = [{"id": item, "title": ""} for item in config["movieSectionIds"]]
        shows = [{"id": item, "title": ""} for item in config["tvSectionIds"]]
    return {
        "server": config["server"],
        "serverName": config.get("serverName") or config.get("userName") or "",
        "movieLibraries": movies,
        "seriesLibraries": shows,
        "authMode": config.get("authMode", AUTH_MODE_TOKEN),
    }


def with_connection(
    document: dict[str, Any],
    config: dict[str, Any] | None,
    libraries: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    value = dict(document)
    value["connection"] = connection_info(config, libraries)
    return value


def restore_file(path: Path, value: dict[str, Any] | None, maximum: int) -> None:
    if value is None:
        with contextlib.suppress(FileNotFoundError):
            unlink_private_file(path)
    else:
        atomic_json_write(path, value, maximum)


def persist_authenticated_session(
    server: str,
    token: str,
    user_id: str,
    user_name: str,
    auth_mode: str,
    client_identifier: str,
    store: SecretStore | None = None,
) -> dict[str, Any]:
    secret_store = store or SecretStore()
    saved_token = secret_store.lookup()
    old_config = load_config()
    client = JellyfinClient(server, token, user_id, client_identifier=client_identifier)
    libraries, discovered_user, server_name = client.discover()
    if discovered_user:
        user_id = discovered_user
    movies = [item["id"] for item in libraries if item["type"] == "movie"]
    shows = [item["id"] for item in libraries if item["type"] == "show"]
    config = validate_config(
        {
            "schemaVersion": SCHEMA_VERSION,
            "server": server,
            "movieSectionIds": movies,
            "tvSectionIds": shows,
            "userId": user_id,
            "userName": user_name,
            "serverName": server_name,
            "authMode": auth_mode,
            "clientIdentifier": client_identifier,
        }
    )
    snapshot = recent_snapshot(client, config)
    old_snapshot = load_snapshot()
    try:
        secret_store.store(token)
        save_config(config)
        save_snapshot(snapshot)
    except Exception:
        with contextlib.suppress(JellyfinError):
            if saved_token:
                secret_store.store(saved_token)
            elif token:
                secret_store.clear()
        with contextlib.suppress(JellyfinError, OSError):
            restore_file(config_home() / "config.json", old_config, MAX_CONFIG_BYTES)
        with contextlib.suppress(JellyfinError, OSError):
            restore_file(cache_home() / "recent.json", old_snapshot, MAX_CACHE_BYTES)
        raise
    return with_connection(snapshot, config, libraries)


def configure_connection(
    setup: dict[str, str],
    store: SecretStore | None = None,
) -> dict[str, Any]:
    secret_store = store or SecretStore()
    server = validate_origin(setup["server"])
    saved_token = secret_store.lookup()
    old_config = load_config()
    client_identifier = (
        old_config["clientIdentifier"] if old_config else new_client_identifier()
    )
    username = clean_text(setup.get("username"), 128)
    password = setup.get("password") or ""
    token = setup.get("token") or ""
    if username and password:
        token, user_id, user_name = authenticate(
            server, username, password, client_identifier
        )
        auth_mode = AUTH_MODE_PASSWORD
    else:
        requested_token = token or saved_token or ""
        if not requested_token:
            raise ConfigurationError("Enter a Jellyfin username and password, or an API key")
        token = valid_token(requested_token)
        probe = JellyfinClient(server, token, "", client_identifier=client_identifier)
        user = probe.fetch_user()
        user_id = user["id"]
        user_name = user["name"]
        auth_mode = AUTH_MODE_TOKEN
    return persist_authenticated_session(
        server, token, user_id, user_name, auth_mode, client_identifier, secret_store
    )


def clear_configuration(store: SecretStore | None = None) -> dict[str, Any]:
    from omajelly.quickconnect import clear_pending

    (store or SecretStore()).clear()
    clear_pending()
    for path in (config_home() / "config.json", cache_home() / "recent.json"):
        with contextlib.suppress(FileNotFoundError):
            unlink_private_file(path)
    return with_connection(status_document(), None)


def client_from_saved(
    store: SecretStore | None = None,
) -> tuple[JellyfinClient, dict[str, Any]]:
    config = load_config()
    if config is None:
        raise ConfigurationError("Omajelly is not configured")
    token = (store or SecretStore()).lookup()
    if not token:
        raise ConfigurationError(
            "No Jellyfin token was found in the desktop secret service"
        )
    return JellyfinClient(
        config["server"],
        token,
        config["userId"],
        client_identifier=config["clientIdentifier"],
    ), config


def status_document() -> dict[str, Any]:
    config = load_config()
    if config is None:
        return with_connection(
            {
                "schemaVersion": SCHEMA_VERSION,
                "configured": False,
                "sourceState": "unconfigured",
                "stale": True,
                "items": [],
                "continueItems": [],
                "movieItems": [],
                "seriesItems": [],
                "newCount": 0,
                "lastSuccessAt": "",
                "error": "",
            },
            None,
        )
    snapshot = load_snapshot()
    if snapshot is not None:
        return with_connection(snapshot, config)
    return with_connection(
        {
            "schemaVersion": SCHEMA_VERSION,
            "configured": True,
            "sourceState": "empty",
            "stale": True,
            "items": [],
            "continueItems": [],
            "movieItems": [],
            "seriesItems": [],
            "newCount": 0,
            "lastSuccessAt": "",
            "error": "",
        },
        config,
    )
