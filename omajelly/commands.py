from __future__ import annotations

import json
from typing import Any

from omajelly.activity import recent_snapshot, save_snapshot
from omajelly.client import HttpMethod, JellyfinClient
from omajelly.common import (
    JellyfinError,
    ResponseError,
    clean_text,
    isoformat,
    utc_now,
    wall_deadline,
)
from omajelly.config import save_config
from omajelly.connection import client_from_saved, status_document, with_connection
from omajelly.constants import MAX_CACHE_BYTES, MAX_SECTIONS


def print_json(value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_CACHE_BYTES:
        raise ResponseError("Jellyfin output exceeded the size limit")
    print(payload)


def command_refresh() -> int:
    try:
        with wall_deadline(25, "Jellyfin refresh exceeded twenty-five seconds"):
            client, config = client_from_saved()
            if not config["serverName"]:
                try:
                    server_name = client.fetch_server_name()
                    if server_name:
                        config = {**config, "serverName": server_name}
                        save_config(config)
                except (JellyfinError, OSError):
                    pass
            snapshot = recent_snapshot(client, config)
        save_snapshot(snapshot)
        print_json(with_connection(snapshot, config))
        return 0
    except JellyfinError as error:
        saved = status_document()
        saved["sourceState"] = "offline" if saved["items"] else saved["sourceState"]
        saved["stale"] = True
        saved["error"] = clean_text(error, 220)
        print_json(saved)
        return 1


def scan_libraries(client: JellyfinClient) -> dict[str, Any]:
    libraries, _, _ = client.discover()
    if len(libraries) > MAX_SECTIONS:
        raise ResponseError("Jellyfin returned an invalid library list")
    if not libraries:
        from omajelly.common import ConfigurationError

        raise ConfigurationError("Jellyfin has no movie or show libraries to scan")
    client.request_empty("/Library/Refresh", method=HttpMethod.POST)
    return {
        "accepted": True,
        "sectionCount": len(libraries),
        "movieSections": sum(1 for item in libraries if item["type"] == "movie"),
        "seriesSections": sum(1 for item in libraries if item["type"] == "show"),
        "requestedAt": isoformat(utc_now()),
    }


def command_scan() -> int:
    with wall_deadline(25, "Jellyfin library scan exceeded twenty-five seconds"):
        client, _ = client_from_saved()
        result = scan_libraries(client)
    print_json(result)
    return 0
