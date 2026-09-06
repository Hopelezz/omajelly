from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import time
from pathlib import Path
from typing import Any

from omajelly.activity import cache_home
from omajelly.client import HttpMethod, JellyfinClient
from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    ResponseError,
    atomic_json_write,
    clean_text,
    finite_integer,
    isoformat,
    read_json_file,
    secure_parent_directory,
    unlink_private_file,
    utc_now,
)
from omajelly.config import config_home
from omajelly.connection import client_from_saved
from omajelly.constants import (
    DEFAULT_DOWNLOAD_CACHE_BYTES,
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_LIMIT_GIBIBYTES,
    DOWNLOAD_STREAM_TIMEOUT,
    MAX_DOWNLOAD_INDEX_BYTES,
    MAX_DOWNLOAD_ITEM_BYTES,
    MAX_DOWNLOAD_ITEMS,
    SCHEMA_VERSION,
)
from omajelly.ids import valid_item_id
from omajelly.media_items import normalize_media_item
from omajelly.playback import fetch_item, fetch_playback_info, playback_item_from_info

DOWNLOAD_STATES = ("queued", "downloading", "ready", "error")


def downloads_index_path() -> Path:
    return config_home() / "downloads.json"


def downloads_root() -> Path:
    return cache_home() / "downloads"


def item_directory(rating_key: str) -> Path:
    return downloads_root() / valid_item_id(rating_key)


def media_path(rating_key: str) -> Path:
    return item_directory(rating_key) / "media"


def part_path(rating_key: str) -> Path:
    return item_directory(rating_key) / "media.part"


@contextlib.contextmanager
def downloads_lock():
    path = downloads_index_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = path.with_name("downloads.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _empty_index() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "maxBytes": DEFAULT_DOWNLOAD_CACHE_BYTES,
        "usedBytes": 0,
        "items": [],
    }


def _public_item(raw: dict[str, Any]) -> dict[str, Any]:
    total = max(0, finite_integer(raw.get("totalBytes")))
    received = max(0, finite_integer(raw.get("bytes")))
    state = str(raw.get("state") or "queued")
    if state == "ready":
        hint = "Ready"
    elif state == "downloading" and total > 0:
        hint = str(min(99, int(received * 100 / total))) + "%"
    elif state == "error":
        hint = clean_text(raw.get("error") or "Download failed", 80)
    else:
        hint = "Queued"
    return {
        "ratingKey": raw["ratingKey"],
        "kind": raw["kind"],
        "title": raw["title"],
        "subtitle": raw["subtitle"],
        "addedAt": raw["addedAt"],
        "addedLabel": "",
        "watchState": "unwatched",
        "isNew": False,
        "playbackRatingKey": raw["ratingKey"],
        "playbackHint": hint,
        "playable": True,
        "downloadState": state,
    }


def _validate_index(value: Any) -> dict[str, Any]:
    if value is None:
        return _empty_index()
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ResponseError("Saved downloads have an unsupported format")
    max_bytes = finite_integer(value.get("maxBytes"), DEFAULT_DOWNLOAD_CACHE_BYTES)
    allowed = {gib * 1024 * 1024 * 1024 for gib in DOWNLOAD_LIMIT_GIBIBYTES}
    if max_bytes not in allowed:
        max_bytes = DEFAULT_DOWNLOAD_CACHE_BYTES
    rows = value.get("items")
    if not isinstance(rows, list) or len(rows) > MAX_DOWNLOAD_ITEMS:
        raise ResponseError("Saved downloads are invalid")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    used = 0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        rating_key = str(raw.get("ratingKey") or "")
        try:
            rating_key = valid_item_id(rating_key)
        except (ConfigurationError, ResponseError):
            continue
        if rating_key in seen:
            continue
        state = str(raw.get("state") or "queued")
        if state not in DOWNLOAD_STATES:
            state = "queued"
        kind = str(raw.get("kind") or "movie")
        if kind not in {"movie", "show"}:
            kind = "movie"
        item = {
            "ratingKey": rating_key,
            "kind": kind,
            "title": clean_text(raw.get("title"), 256),
            "subtitle": clean_text(raw.get("subtitle"), 256),
            "state": state,
            "error": clean_text(raw.get("error"), 160),
            "bytes": max(0, finite_integer(raw.get("bytes"))),
            "totalBytes": max(0, finite_integer(raw.get("totalBytes"))),
            "addedAt": str(raw.get("addedAt") or isoformat(utc_now())),
            "completedAt": str(raw.get("completedAt") or ""),
            "lastAccessAt": str(raw.get("lastAccessAt") or ""),
        }
        if not item["title"]:
            continue
        seen.add(rating_key)
        if state == "ready":
            path = media_path(rating_key)
            if path.is_file():
                item["bytes"] = path.stat().st_size
                used += item["bytes"]
            else:
                item["state"] = "queued"
                item["bytes"] = 0
        items.append(item)
        if len(items) >= MAX_DOWNLOAD_ITEMS:
            break
    return {
        "schemaVersion": SCHEMA_VERSION,
        "maxBytes": max_bytes,
        "usedBytes": used,
        "items": items,
    }


def load_index() -> dict[str, Any]:
    return _validate_index(read_json_file(downloads_index_path(), MAX_DOWNLOAD_INDEX_BYTES))


def save_index(index: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_index(index)
    atomic_json_write(downloads_index_path(), validated, MAX_DOWNLOAD_INDEX_BYTES)
    return validated


def _public_document(index: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "maxBytes": index["maxBytes"],
        "usedBytes": index["usedBytes"],
        "syncing": any(item["state"] == "downloading" for item in index["items"]),
        "items": [_public_item(item) for item in index["items"]],
    }


def downloads_document() -> dict[str, Any]:
    with downloads_lock():
        return _public_document(load_index())


def cached_media_path(rating_key: str) -> Path | None:
    rating_key = valid_item_id(rating_key)
    path = media_path(rating_key)
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    with downloads_lock():
        index = load_index()
        for item in index["items"]:
            if item["ratingKey"] == rating_key and item["state"] == "ready":
                item["lastAccessAt"] = isoformat(utc_now())
                save_index(index)
                return path
    return None


def _remove_files(rating_key: str) -> None:
    directory = item_directory(rating_key)
    for name in ("media", "media.part"):
        path = directory / name
        with contextlib.suppress(FileNotFoundError, ResponseError, OSError):
            unlink_private_file(path)
    with contextlib.suppress(OSError):
        directory.rmdir()


def _evict_for(index: dict[str, Any], needed: int) -> None:
    used = finite_integer(index.get("usedBytes"))
    maximum = finite_integer(index.get("maxBytes"), DEFAULT_DOWNLOAD_CACHE_BYTES)
    while used + needed > maximum:
        candidates = [
            item
            for item in index["items"]
            if item["state"] == "ready" and item["lastAccessAt"]
        ]
        candidates.sort(key=lambda item: item["lastAccessAt"])
        if not candidates:
            candidates = [item for item in index["items"] if item["state"] == "ready"]
            candidates.sort(key=lambda item: item.get("completedAt") or item["addedAt"])
        if not candidates:
            raise ConfigurationError("The download cache is full")
        victim = candidates[0]
        used -= victim["bytes"]
        _remove_files(victim["ratingKey"])
        index["items"] = [
            item for item in index["items"] if item["ratingKey"] != victim["ratingKey"]
        ]
        index["usedBytes"] = max(0, used)


def queue_download(rating_key: str) -> dict[str, Any]:
    rating_key = valid_item_id(rating_key)
    client, _config = client_from_saved()
    item = fetch_item(client, rating_key)
    normalized = normalize_media_item(item, utc_now())
    if normalized is None:
        raise ResponseError("Only movies and episodes can be downloaded")
    with downloads_lock():
        index = load_index()
        for existing in index["items"]:
            if existing["ratingKey"] == rating_key:
                return _public_document(index)
        if len(index["items"]) >= MAX_DOWNLOAD_ITEMS:
            raise ConfigurationError("The download list is full")
        index["items"].append(
            {
                "ratingKey": rating_key,
                "kind": normalized["kind"],
                "title": normalized["title"],
                "subtitle": normalized["subtitle"],
                "state": "queued",
                "error": "",
                "bytes": 0,
                "totalBytes": 0,
                "addedAt": isoformat(utc_now()),
                "completedAt": "",
                "lastAccessAt": "",
            }
        )
        save_index(index)
    return downloads_document()


def remove_download(rating_key: str) -> dict[str, Any]:
    rating_key = valid_item_id(rating_key)
    with downloads_lock():
        index = load_index()
        index["items"] = [
            item for item in index["items"] if item["ratingKey"] != rating_key
        ]
        save_index(index)
    _remove_files(rating_key)
    return downloads_document()


def _still_wanted(rating_key: str) -> bool:
    index = load_index()
    return any(item["ratingKey"] == rating_key for item in index["items"])


def _download_item(client: JellyfinClient, rating_key: str) -> None:
    item = fetch_item(client, rating_key)
    info = fetch_playback_info(client, rating_key)
    playback = playback_item_from_info(item, info)
    sources = info.get("MediaSources")
    total = 0
    if isinstance(sources, list) and sources and isinstance(sources[0], dict):
        total = max(0, finite_integer(sources[0].get("Size")))
    if total > MAX_DOWNLOAD_ITEM_BYTES:
        raise ConfigurationError("This title is larger than the download limit")
    destination = part_path(rating_key)
    with secure_parent_directory(destination, create=True, private=True):
        pass
    final = media_path(rating_key)
    start = destination.stat().st_size if destination.is_file() else 0
    range_header = "bytes=" + str(start) + "-" if start > 0 else ""
    response = client.open(
        playback.stream_path,
        method=HttpMethod.GET,
        range_header=range_header,
        timeout=DOWNLOAD_STREAM_TIMEOUT,
    )
    try:
        status = int(getattr(response, "status", response.getcode()))
        if start > 0 and status == 200:
            start = 0
            with contextlib.suppress(FileNotFoundError, OSError, ResponseError):
                unlink_private_file(destination)
        length = finite_integer(response.headers.get("Content-Length"))
        if status == 206 and start > 0 and length > 0:
            total = start + length
        elif length > 0 and total <= 0:
            total = length if start == 0 else start + length
        if total > MAX_DOWNLOAD_ITEM_BYTES:
            raise ConfigurationError("This title is larger than the download limit")
        with downloads_lock():
            index = load_index()
            _evict_for(index, max(total, start + 1) - start)
            for row in index["items"]:
                if row["ratingKey"] == rating_key:
                    row["state"] = "downloading"
                    row["error"] = ""
                    row["bytes"] = start
                    row["totalBytes"] = total
            save_index(index)
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
        descriptor = os.open(destination, flags, 0o600)
        try:
            os.lseek(descriptor, start, os.SEEK_SET)
            received = start
            last_write = time.monotonic()
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_DOWNLOAD_ITEM_BYTES:
                    raise ConfigurationError("This title is larger than the download limit")
                written = 0
                while written < len(chunk):
                    written += os.write(descriptor, chunk[written:])
                now = time.monotonic()
                if now - last_write >= 2:
                    if not _still_wanted(rating_key):
                        raise ConfigurationError("Download was removed")
                    with downloads_lock():
                        index = load_index()
                        for row in index["items"]:
                            if row["ratingKey"] == rating_key:
                                row["bytes"] = received
                                row["totalBytes"] = max(total, received)
                                row["state"] = "downloading"
                        save_index(index)
                    last_write = now
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        response.close()
    os.replace(destination, final)
    size = final.stat().st_size
    stamp = isoformat(utc_now())
    with downloads_lock():
        index = load_index()
        for row in index["items"]:
            if row["ratingKey"] == rating_key:
                row["state"] = "ready"
                row["error"] = ""
                row["bytes"] = size
                row["totalBytes"] = size
                row["completedAt"] = stamp
                row["lastAccessAt"] = stamp
        save_index(index)


def sync_downloads() -> dict[str, Any]:
    client, _config = client_from_saved()
    while True:
        with downloads_lock():
            index = load_index()
            nxt = next(
                (
                    item
                    for item in index["items"]
                    if item["state"] in {"queued", "downloading"}
                ),
                None,
            )
            if nxt is None:
                return _public_document(index)
            rating_key = nxt["ratingKey"]
            nxt["state"] = "downloading"
            nxt["error"] = ""
            save_index(index)
        try:
            _download_item(client, rating_key)
        except (JellyfinError, OSError, ConfigurationError) as error:
            with downloads_lock():
                index = load_index()
                for row in index["items"]:
                    if row["ratingKey"] == rating_key:
                        row["state"] = "error"
                        row["error"] = clean_text(error, 160)
                save_index(index)


def set_download_limit(gibibytes: int) -> dict[str, Any]:
    if gibibytes not in DOWNLOAD_LIMIT_GIBIBYTES:
        raise ConfigurationError("Choose a download cache of 5, 10, 20, or 40 GB")
    maximum = gibibytes * 1024 * 1024 * 1024
    with downloads_lock():
        index = load_index()
        index["maxBytes"] = maximum
        _evict_for(index, 0)
        save_index(index)
    return downloads_document()


def clear_downloads() -> None:
    with downloads_lock():
        index = load_index()
        empty = _empty_index()
        empty["maxBytes"] = index["maxBytes"]
        save_index(empty)
    root = downloads_root()
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
