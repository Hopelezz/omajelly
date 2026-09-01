from __future__ import annotations

import datetime as dt
from typing import Any

from omajelly.common import ResponseError, clean_text, finite_integer, isoformat
from omajelly.constants import MAX_ITEMS, NEW_AGE_DAYS
from omajelly.ids import optional_item_id


def parse_jellyfin_date(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def ticks_to_ms(value: Any) -> int:
    return max(0, finite_integer(value) // 10_000)


def ticks_to_seconds(value: Any) -> int:
    return max(0, finite_integer(value) // 10_000_000)


def format_episode_code(season_value: Any, episode_value: Any) -> str:
    season = finite_integer(season_value, -1)
    episode = finite_integer(episode_value, -1)
    season_code = "" if season < 0 else "S" + str(season).zfill(2)
    episode_code = "" if episode < 0 else "E" + str(episode).zfill(2)
    return season_code + episode_code


def user_data(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    data = item.get("UserData")
    return data if isinstance(data, dict) else {}


def derive_watch_state(item: dict[str, Any]) -> str:
    data = user_data(item)
    if data.get("Played") is True:
        return "watched"
    if finite_integer(data.get("PlaybackPositionTicks")) > 0:
        return "started"
    return "unwatched"


def format_added_label(added: dt.datetime, now: dt.datetime) -> str:
    local = added.astimezone()
    today = now.astimezone().date()
    if local.date() == today:
        return "Today · " + local.strftime("%H:%M")
    if local.date() == today - dt.timedelta(days=1):
        return "Yesterday"
    return local.strftime(
        "%d %b" if local.year == now.astimezone().year else "%d %b %Y"
    ).lstrip("0")


def format_played_label(value: Any, now: dt.datetime) -> str:
    viewed = parse_jellyfin_date(value)
    if viewed is None:
        return ""
    seconds = max(0, int((now - viewed).total_seconds()))
    if seconds < 60:
        return "Played just now"
    if seconds < 60 * 60:
        return "Played " + str(max(1, seconds // 60)) + "m ago"
    if seconds < 24 * 60 * 60:
        return "Played " + str(seconds // (60 * 60)) + "h ago"
    if seconds < 7 * 24 * 60 * 60:
        return "Played " + str(seconds // (24 * 60 * 60)) + "d ago"
    return "Played " + format_added_label(viewed, now)


def item_type(item: dict[str, Any]) -> str:
    return str(item.get("Type") or item.get("type") or "")


def normalize_media_item(item: Any, now: dt.datetime) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    raw_kind = item_type(item)
    if raw_kind not in {"Movie", "Episode"}:
        return None
    rating_key = optional_item_id(item.get("Id"))
    if not rating_key:
        return None
    added = parse_jellyfin_date(item.get("DateCreated") or item.get("PremiereDate"))
    if added is None:
        added = now
    episode = raw_kind == "Episode"
    title = clean_text(item.get("SeriesName") if episode else item.get("Name"))
    if not title:
        return None
    if episode:
        code = format_episode_code(item.get("ParentIndexNumber"), item.get("IndexNumber"))
        subtitle = " · ".join(
            part for part in ["Show", code, clean_text(item.get("Name"))] if part
        )
        show_key = optional_item_id(item.get("SeriesId"))
        group = "show:" + (show_key or title.lower())
        kind = "show"
    else:
        year = finite_integer(item.get("ProductionYear"), -1)
        subtitle = ("Movie · " + str(year)) if year > 0 else "Movie"
        group = "movie:" + rating_key
        kind = "movie"
        show_key = ""
    state = derive_watch_state(item)
    return {
        "ratingKey": rating_key,
        "group": group,
        "showKey": show_key,
        "kind": kind,
        "title": title,
        "subtitle": clean_text(subtitle),
        "addedAt": isoformat(added),
        "addedEpoch": int(added.timestamp()),
        "addedLabel": format_added_label(added, now),
        "watchState": state,
        "isNew": state == "unwatched"
        and now - added <= dt.timedelta(days=NEW_AGE_DAYS),
        "playbackRatingKey": rating_key,
        "playbackHint": "",
        "playable": True,
    }


def to_public_item(item: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in item.items()
        if key not in {"group", "addedEpoch"}
    }
    show_key = optional_item_id(public.get("showKey"))
    if show_key:
        public["showKey"] = show_key
    else:
        public.pop("showKey", None)
    return public


def normalize_continue_item(item: Any, now: dt.datetime) -> dict[str, Any] | None:
    normalized = normalize_media_item(item, now)
    if normalized is None:
        return None
    normalized["isNew"] = False
    data = user_data(item) if isinstance(item, dict) else {}
    normalized["addedLabel"] = format_played_label(
        data.get("LastPlayedDate")
        or (item.get("DateLastSaved") if isinstance(item, dict) else None),
        now,
    )
    offset = ticks_to_ms(data.get("PlaybackPositionTicks"))
    duration = ticks_to_ms(
        item.get("RunTimeTicks") if isinstance(item, dict) else 0
    )
    if offset > 0 and duration > 0:
        normalized["playbackHint"] = (
            "Resume " + str(min(99, round(offset * 100 / duration))) + "%"
        )
    elif normalized["kind"] == "show":
        normalized["playbackHint"] = "Next episode"
    return to_public_item(normalized)


def sort_items_by_watch_state(items: list[dict[str, Any]]) -> None:
    priority = {"started": 0, "unwatched": 1, "watched": 2}
    items.sort(key=lambda item: priority[item["watchState"]])


def extract_items(document: Any, *, maximum: int = MAX_ITEMS) -> list[Any]:
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict):
        rows = document.get("Items", [])
    else:
        raise ResponseError("Jellyfin returned an invalid item list")
    if not isinstance(rows, list) or len(rows) > maximum:
        raise ResponseError("Jellyfin returned an invalid item list")
    return rows


def browse_show_item(raw: Any, now: dt.datetime) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or item_type(raw) != "Series":
        return None
    rating_key = optional_item_id(raw.get("Id"))
    title = clean_text(raw.get("Name"))
    if not rating_key or not title:
        return None
    leaf_count = max(0, finite_integer(raw.get("RecursiveItemCount") or raw.get("ChildCount")))
    data = user_data(raw)
    unplayed = max(0, finite_integer(data.get("UnplayedItemCount")))
    played = max(0, leaf_count - unplayed) if leaf_count else 0
    if data.get("Played") is True or (leaf_count > 0 and unplayed == 0 and played > 0):
        state = "watched"
    elif finite_integer(data.get("PlaybackPositionTicks")) > 0 or played > 0:
        state = "started"
    else:
        state = "unwatched"
    added = parse_jellyfin_date(raw.get("DateCreated")) or now
    episode_label = (
        str(leaf_count) + (" episode" if leaf_count == 1 else " episodes")
        if leaf_count
        else "Show"
    )
    return {
        "ratingKey": rating_key,
        "kind": "show",
        "title": title,
        "subtitle": clean_text("Show · " + episode_label),
        "addedAt": isoformat(added),
        "addedLabel": "",
        "watchState": state,
        "isNew": False,
        "playbackRatingKey": rating_key,
        "playbackHint": "Open episodes",
        "playable": False,
        "showKey": rating_key,
    }


def browse_season_item(raw: Any, now: dt.datetime) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or item_type(raw) != "Season":
        return None
    rating_key = optional_item_id(raw.get("Id"))
    if not rating_key:
        return None
    index = finite_integer(raw.get("IndexNumber"), -1)
    name = clean_text(raw.get("Name"))
    if index == 0:
        title = name or "Specials"
    elif index > 0:
        title = name or ("Season " + str(index))
    else:
        title = name or "Season"
    leaf_count = max(
        0, finite_integer(raw.get("RecursiveItemCount") or raw.get("ChildCount"))
    )
    data = user_data(raw)
    unplayed = max(0, finite_integer(data.get("UnplayedItemCount")))
    played = max(0, leaf_count - unplayed) if leaf_count else 0
    if data.get("Played") is True or (leaf_count > 0 and unplayed == 0 and played > 0):
        state = "watched"
    elif played > 0:
        state = "started"
    else:
        state = "unwatched"
    added = parse_jellyfin_date(raw.get("DateCreated")) or now
    episode_label = (
        str(leaf_count) + (" episode" if leaf_count == 1 else " episodes")
        if leaf_count
        else "Season"
    )
    show_key = optional_item_id(raw.get("SeriesId"))
    return {
        "ratingKey": rating_key,
        "kind": "season",
        "title": title,
        "subtitle": clean_text(episode_label),
        "addedAt": isoformat(added),
        "addedLabel": "",
        "watchState": state,
        "isNew": False,
        "playbackRatingKey": rating_key,
        "playbackHint": "Open episodes",
        "playable": False,
        "showKey": show_key,
    }
