from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from omajelly.client import HttpMethod, JellyfinClient
from omajelly.common import (
    ConfigurationError,
    ResponseError,
    clean_text,
    finite_integer,
)
from omajelly.constants import MAX_SUBTITLE_BYTES, MAX_SUBTITLE_RESULTS, SCHEMA_VERSION
from omajelly.ids import valid_item_id


def subtitle_language(value: Any) -> str:
    language = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z]{2}", language):
        raise ConfigurationError("Subtitle search language must use two letters")
    return language


def subtitle_format(value: Any) -> str:
    format_name = str(value or "srt").strip().lower()
    if format_name not in {"ass", "smi", "srt", "ssa", "sub", "vtt"}:
        raise ConfigurationError("Invalid Jellyfin subtitle format")
    return format_name


def subtitle_flag(value: Any) -> bool:
    return value is True or finite_integer(value) == 1


def subtitle_display_text(value: Any, maximum: int) -> str:
    return re.sub(r"[{}\\]", "", clean_text(value, maximum))


def search_subtitles(
    client: JellyfinClient, rating_key: str, language: str
) -> dict[str, Any]:
    rating_key = valid_item_id(rating_key)
    language = subtitle_language(language)
    document = client.request_json(
        "/Items/" + rating_key + "/RemoteSearch/Subtitles/" + language
    )
    if not isinstance(document, list) or len(document) > MAX_SUBTITLE_RESULTS * 4:
        raise ResponseError("Jellyfin returned an invalid subtitle search result")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in document:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("Id") or "")
        if not key or key in seen or len(key) > 256 or "/" in key or "\\" in key:
            continue
        seen.add(key)
        try:
            format_name = subtitle_format(raw.get("Format") or "srt")
        except ConfigurationError:
            format_name = "srt"
        items.append(
            {
                "key": key,
                "label": subtitle_display_text(
                    raw.get("Name") or raw.get("Author") or "Subtitle", 160
                )
                or "Subtitle",
                "provider": subtitle_display_text(raw.get("Author"), 80),
                "format": format_name,
                "language": clean_text(raw.get("ThreeLetterISOLanguageName") or language, 12),
                "hearingImpaired": subtitle_flag(raw.get("IsHearingImpaired")),
                "forced": subtitle_flag(raw.get("IsForced")),
                "perfectMatch": subtitle_flag(raw.get("IsHashMatch")),
                "score": max(0, finite_integer(raw.get("CommunityRating"))),
            }
        )
        if len(items) >= MAX_SUBTITLE_RESULTS:
            break
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ratingKey": rating_key,
        "language": language,
        "items": items,
    }


def open_private_output_directory(path: str) -> int:
    if not path.startswith("/tmp/omajelly-player-") or len(path) > 512:
        raise ConfigurationError("Invalid player subtitle directory")
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ConfigurationError(
            "The player subtitle directory is unavailable"
        ) from error
    details = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise ConfigurationError("The player subtitle directory is unsafe")
    return descriptor


def download_subtitle(
    client: JellyfinClient,
    rating_key: str,
    stream_key: str,
    format_name: str,
    output_directory: str,
) -> dict[str, str]:
    rating_key = valid_item_id(rating_key)
    key = str(stream_key or "")
    if not key or len(key) > 256 or "/" in key or "\\" in key:
        raise ConfigurationError("Invalid Jellyfin subtitle result")
    format_name = subtitle_format(format_name)
    directory = open_private_output_directory(output_directory)
    try:
        response = client.open(
            "/Items/" + rating_key + "/RemoteSearch/Subtitles/" + key,
            method=HttpMethod.POST,
        )
        try:
            length = finite_integer(response.headers.get("Content-Length"), -1)
            if length > MAX_SUBTITLE_BYTES:
                raise ResponseError("Jellyfin subtitle exceeded the size limit")
            payload = response.read(MAX_SUBTITLE_BYTES + 1)
        finally:
            response.close()
        if not payload or len(payload) > MAX_SUBTITLE_BYTES:
            raise ResponseError("Jellyfin subtitle exceeded the size limit")
        if b"\x00" in payload[:4096]:
            raise ResponseError("Jellyfin returned an invalid subtitle file")
        safe_key = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:64]
        filename = "subtitle-" + safe_key + "." + format_name
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(filename, flags, 0o600, dir_fd=directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
    except OSError as error:
        raise ConfigurationError("Could not save the selected subtitle") from error
    finally:
        os.close(directory)
    return {"path": str(Path(output_directory) / filename)}
