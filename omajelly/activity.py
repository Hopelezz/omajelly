from __future__ import annotations

import datetime as dt
import os
import urllib.parse
from pathlib import Path
from typing import Any

from omajelly.client import JellyfinClient
from omajelly.common import (
    ResponseError,
    atomic_json_write,
    clean_text,
    isoformat,
    read_json_file,
    utc_now,
)
from omajelly.constants import (
    MAX_ACTIVITY_ITEMS,
    MAX_CACHE_BYTES,
    MAX_ITEMS,
    SCHEMA_VERSION,
    STALE_SECONDS,
)
from omajelly.ids import is_item_id, optional_item_id
from omajelly.media_items import (
    extract_items,
    format_episode_code,
    item_type,
    normalize_continue_item,
    normalize_media_item,
    sort_items_by_watch_state,
    to_public_item,
    ticks_to_ms,
    user_data,
)


def cache_home() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "omajelly"


def _query(values: dict[str, Any]) -> str:
    return urllib.parse.urlencode(values, doseq=True)


def recent_snapshot(
    client: JellyfinClient, config: dict[str, Any], now: dt.datetime | None = None
) -> dict[str, Any]:
    checked_at = now or utc_now()
    user_id = config["userId"]
    continue_rows = extract_items(
        client.request_json(
            "/Users/"
            + user_id
            + "/Items/Resume?"
            + _query(
                {
                    "MediaTypes": "Video",
                    "Limit": MAX_ACTIVITY_ITEMS,
                    "Fields": "DateCreated,UserData,ParentIndexNumber,IndexNumber,SeriesId,SeriesName,ProductionYear,RunTimeTicks",
                }
            )
        )
    )
    continue_items: list[dict[str, Any]] = []
    seen_continue: set[str] = set()
    for row in continue_rows:
        item = normalize_continue_item(row, checked_at)
        if item is None or not isinstance(row, dict):
            continue
        if item_type(row) == "Episode":
            group = "show:" + str(row.get("SeriesId") or row.get("SeriesName") or "").lower()
        else:
            group = "movie:" + str(row.get("Id") or "")
        if group in seen_continue:
            continue
        seen_continue.add(group)
        continue_items.append(item)
        if len(continue_items) >= MAX_ACTIVITY_ITEMS:
            break

    continuation: dict[str, dict[str, str]] = {}
    for candidate in continue_rows:
        if not isinstance(candidate, dict) or item_type(candidate) != "Episode":
            continue
        show_key = str(candidate.get("SeriesId") or "")
        rating_key = str(candidate.get("Id") or "")
        if not is_item_id(show_key) or not is_item_id(rating_key):
            continue
        code = format_episode_code(
            candidate.get("ParentIndexNumber"), candidate.get("IndexNumber")
        )
        data = user_data(candidate)
        prefix = "Resume " if ticks_to_ms(data.get("PlaybackPositionTicks")) > 0 else "Next "
        if show_key not in continuation:
            continuation[show_key] = {
                "ratingKey": rating_key,
                "hint": clean_text(prefix + (code or "episode"), 80),
            }

    added_rows = extract_items(
        client.request_json(
            "/Users/"
            + user_id
            + "/Items?"
            + _query(
                {
                    "SortBy": "DateCreated",
                    "SortOrder": "Descending",
                    "IncludeItemTypes": "Movie,Episode",
                    "Recursive": "true",
                    "Limit": 80,
                    "Fields": "DateCreated,UserData,ParentIndexNumber,IndexNumber,SeriesId,SeriesName,ProductionYear,RunTimeTicks",
                }
            )
        ),
        maximum=80,
    )
    movie_normalized = [
        value
        for value in (normalize_media_item(item, checked_at) for item in added_rows)
        if value is not None and value["kind"] == "movie"
    ]
    movie_normalized.sort(key=lambda item: item["addedEpoch"], reverse=True)
    movie_items = [to_public_item(item) for item in movie_normalized[:MAX_ACTIVITY_ITEMS]]
    sort_items_by_watch_state(movie_items)

    series_normalized = [
        value
        for value in (normalize_media_item(item, checked_at) for item in added_rows)
        if value is not None and value["kind"] == "show"
    ]
    series_normalized.sort(key=lambda item: item["addedEpoch"], reverse=True)
    seen: set[str] = set()
    series_items: list[dict[str, Any]] = []
    for item in series_normalized:
        if item["group"] in seen:
            continue
        seen.add(item["group"])
        if item["kind"] == "show" and item["showKey"] in continuation:
            next_item = continuation[item["showKey"]]
            item["playbackRatingKey"] = next_item["ratingKey"]
            item["playbackHint"] = next_item["hint"]
        series_items.append(to_public_item(item))
        if len(series_items) >= MAX_ACTIVITY_ITEMS:
            break
    sort_items_by_watch_state(series_items)
    items = movie_items + series_items
    items.sort(key=lambda item: item["addedAt"], reverse=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "configured": True,
        "sourceState": "updated" if items or continue_items else "empty",
        "stale": False,
        "items": items,
        "continueItems": continue_items,
        "movieItems": movie_items,
        "seriesItems": series_items,
        "newCount": sum(1 for item in items if item["isNew"]),
        "lastSuccessAt": isoformat(checked_at),
        "error": "",
    }


def validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ResponseError("Saved Jellyfin data has an unsupported format")
    raw_items = value.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > MAX_ITEMS:
        raise ResponseError("Saved Jellyfin data has an invalid item list")

    def validate_items(source: Any, maximum: int = MAX_ITEMS) -> list[dict[str, Any]]:
        if not isinstance(source, list) or len(source) > maximum:
            raise ResponseError("Saved Jellyfin data has an invalid item list")
        validated: list[dict[str, Any]] = []
        for raw in source:
            item = validate_item(raw)
            if item is not None:
                validated.append(item)
        return validated

    def validate_item(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        key = str(raw.get("ratingKey") or "")
        playback_key = str(raw.get("playbackRatingKey") or key)
        kind = str(raw.get("kind") or "")
        state = str(raw.get("watchState") or "")
        added_at = str(raw.get("addedAt") or "")
        if (
            not is_item_id(key)
            or not is_item_id(playback_key)
            or kind not in {"movie", "show"}
            or state not in {"unwatched", "started", "watched"}
        ):
            return None
        try:
            dt.datetime.fromisoformat(added_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        title = clean_text(raw.get("title"))
        if not title:
            return None
        result = {
            "ratingKey": key,
            "kind": kind,
            "title": title,
            "subtitle": clean_text(raw.get("subtitle")),
            "addedAt": added_at,
            "addedLabel": clean_text(raw.get("addedLabel"), 80),
            "watchState": state,
            "isNew": raw.get("isNew") is True,
            "playbackRatingKey": playback_key,
            "playbackHint": clean_text(raw.get("playbackHint"), 80),
            "playable": raw.get("playable") is not False,
        }
        show_key = optional_item_id(raw.get("showKey"))
        if show_key:
            result["showKey"] = show_key
        return result

    items = validate_items(raw_items)
    continue_items = validate_items(value.get("continueItems", []), MAX_ACTIVITY_ITEMS)
    movie_items = validate_items(
        value.get("movieItems", [item for item in items if item["kind"] == "movie"]),
        MAX_ACTIVITY_ITEMS,
    )
    series_items = validate_items(
        value.get("seriesItems", [item for item in items if item["kind"] == "show"]),
        MAX_ACTIVITY_ITEMS,
    )
    last_success = str(value.get("lastSuccessAt") or "")
    try:
        dt.datetime.fromisoformat(last_success.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResponseError("Saved Jellyfin data has an invalid timestamp") from error
    return {
        "schemaVersion": SCHEMA_VERSION,
        "configured": True,
        "sourceState": "saved" if items else "empty",
        "stale": cache_is_stale(last_success),
        "items": items,
        "continueItems": continue_items,
        "movieItems": movie_items,
        "seriesItems": series_items,
        "newCount": sum(1 for item in items if item["isNew"]),
        "lastSuccessAt": last_success,
        "error": "",
    }


def cache_is_stale(timestamp_value: str, now: dt.datetime | None = None) -> bool:
    try:
        saved = dt.datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now or utc_now()) - saved > dt.timedelta(seconds=STALE_SECONDS)


def load_snapshot() -> dict[str, Any] | None:
    value = read_json_file(cache_home() / "recent.json", MAX_CACHE_BYTES)
    return None if value is None else validate_snapshot(value)


def save_snapshot(value: dict[str, Any]) -> None:
    stored = dict(value)
    stored.pop("error", None)
    atomic_json_write(cache_home() / "recent.json", stored, MAX_CACHE_BYTES)
