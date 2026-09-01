from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import urllib.parse
from enum import StrEnum
from typing import Any

from omajelly.client import JellyfinClient
from omajelly.common import (
    ConfigurationError,
    ResponseError,
    clean_text,
    finite_integer,
    stop_process_group,
    utc_now,
)
from omajelly.constants import (
    MAX_BROWSE_ITEMS,
    MAX_EPISODES_PER_SERIES,
    MAX_EXPANDED_SERIES,
    MAX_FZF_BYTES,
    MAX_SEARCH_CANDIDATES,
    MAX_SEARCH_PAGE_SIZE,
    MAX_SEARCH_REQUESTS,
    MAX_SEASONS_PER_SERIES,
    SCHEMA_VERSION,
)
from omajelly.ids import is_item_id, valid_item_id
from omajelly.media_items import (
    browse_season_item,
    browse_show_item,
    extract_items,
    item_type,
    normalize_media_item,
    to_public_item,
)


class BrowseKind(StrEnum):
    MOVIES = "movies"
    SHOWS = "shows"
    SEASONS = "seasons"
    EPISODES = "episodes"
    SEARCH = "search"


class SearchScope(StrEnum):
    MOVIES = "movies"
    SHOWS = "shows"


def browse_item(raw: Any, now: dt.datetime) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    raw_type = item_type(raw)
    if raw_type in {"Movie", "Episode"}:
        normalized = normalize_media_item(raw, now)
        if normalized is None:
            return None
        item = to_public_item(normalized)
        item["isNew"] = False
        item["addedLabel"] = ""
        item["playable"] = True
        return item
    if raw_type == "Season":
        return browse_season_item(raw, now)
    if raw_type != "Series":
        return None
    return browse_show_item(raw, now)


def _query(values: dict[str, Any]) -> str:
    return urllib.parse.urlencode(values, doseq=True)


def paged_library_rows(
    client: JellyfinClient,
    user_id: str,
    include_types: str,
    parent_ids: list[str],
    maximum: int,
    request_budget: list[int],
    *,
    recursive: bool = True,
    extra: dict[str, Any] | None = None,
) -> list[Any]:
    rows: list[Any] = []
    parents = parent_ids or [""]
    for parent in parents:
        start = 0
        while len(rows) < maximum and request_budget[0] > 0:
            size = min(MAX_SEARCH_PAGE_SIZE, maximum - len(rows))
            parameters: dict[str, Any] = {
                "IncludeItemTypes": include_types,
                "Recursive": "true" if recursive else "false",
                "StartIndex": start,
                "Limit": size,
                "SortBy": "SortName",
                "SortOrder": "Ascending",
                "Fields": "DateCreated,UserData,ParentIndexNumber,IndexNumber,SeriesId,SeriesName,ProductionYear,RunTimeTicks,RecursiveItemCount,ChildCount",
            }
            if parent:
                parameters["ParentId"] = parent
            if extra:
                parameters.update(extra)
            request_budget[0] -= 1
            document = client.request_json(
                "/Users/" + user_id + "/Items?" + _query(parameters)
            )
            page = extract_items(document, maximum=size)
            rows.extend(page)
            total = max(
                len(page),
                finite_integer(
                    document.get("TotalRecordCount") if isinstance(document, dict) else 0,
                    len(page),
                ),
            )
            start += len(page)
            if not page or start >= total:
                break
    return rows


def fallback_fuzzy_rank(
    items: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    tokens = [token for token in re.split(r"\s+", query.casefold()) if token]

    def score(item: dict[str, Any]) -> tuple[int, int, str] | None:
        haystack = (
            str(item.get("title") or "") + " " + str(item.get("subtitle") or "")
        ).casefold()
        total_gap = 0
        first = len(haystack)
        for token in tokens:
            cursor = -1
            positions: list[int] = []
            for character in token:
                cursor = haystack.find(character, cursor + 1)
                if cursor < 0:
                    return None
                positions.append(cursor)
            first = min(first, positions[0])
            total_gap += positions[-1] - positions[0] + 1 - len(token)
        return total_gap, first, haystack

    scored = [(value, item) for item in items if (value := score(item)) is not None]
    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored]


def fzf_rank(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not items or not query:
        return items
    lines: list[bytes] = []
    size = 0
    for index, item in enumerate(items):
        searchable = clean_text(
            str(item.get("title") or "") + " " + str(item.get("subtitle") or ""), 600
        )
        line = (str(index) + "\t" + searchable + "\n").encode("utf-8")
        if size + len(line) > MAX_FZF_BYTES:
            break
        lines.append(line)
        size += len(line)
    if shutil.which("fzf") is None:
        return fallback_fuzzy_rank(items[: len(lines)], query)
    process = subprocess.Popen(
        [
            "fzf",
            "--filter",
            query,
            "--ignore-case",
            "--delimiter",
            "\t",
            "--nth",
            "2..",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(b"".join(lines), timeout=3)
    except subprocess.TimeoutExpired:
        stop_process_group(process)
        return fallback_fuzzy_rank(items[: len(lines)], query)
    if len(output) > size:
        raise ResponseError("fzf returned an invalid search result")
    ranked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_line in output.splitlines():
        raw_index = raw_line.split(b"\t", 1)[0]
        try:
            index = int(raw_index)
        except ValueError:
            continue
        if 0 <= index < len(items) and index not in seen:
            seen.add(index)
            ranked.append(items[index])
    return ranked


def season_query(value: str) -> tuple[str, int | None, int | None]:
    match = re.search(r"(?i)(?:^|\s)s(\d{1,3})(?:e(\d{0,3}))?(?=\s|$)", value)
    if match is None:
        return value, None, None
    title_query = (value[: match.start()] + " " + value[match.end() :]).strip()
    return (
        title_query,
        int(match.group(1)),
        int(match.group(2)) if match.group(2) else None,
    )


def search_document(
    client: JellyfinClient,
    config: dict[str, Any],
    query: str,
    offset: int,
    limit: int,
    scope: SearchScope,
) -> dict[str, Any]:
    if not isinstance(scope, SearchScope):
        raise ConfigurationError("Search scope must be movies or shows")
    title_query, season_number, episode_number = season_query(query)
    if scope is SearchScope.SHOWS and season_number is not None and not title_query:
        raise ConfigurationError("Add a show name before the season code")
    request_budget = [MAX_SEARCH_REQUESTS]
    user_id = config["userId"]
    now = utc_now()
    if scope is SearchScope.MOVIES:
        movie_rows = paged_library_rows(
            client,
            user_id,
            "Movie",
            config["movieSectionIds"],
            MAX_SEARCH_CANDIDATES,
            request_budget,
        )
        movies = [
            value
            for value in (browse_item(row, now) for row in movie_rows)
            if value is not None
        ]
        ranked = fzf_rank(movies, query)
    else:
        show_rows = paged_library_rows(
            client,
            user_id,
            "Series",
            config["tvSectionIds"],
            MAX_SEARCH_CANDIDATES,
            request_budget,
            recursive=True,
        )
        shows = [
            value
            for value in (browse_item(row, now) for row in show_rows)
            if value is not None
        ]
        if season_number is None:
            ranked = fzf_rank(shows, query)
        else:
            matching_shows = fzf_rank(shows, title_query)[:MAX_EXPANDED_SERIES]
            episode_rows: list[tuple[int, int, int, dict[str, Any]]] = []
            for show_rank, show in enumerate(matching_shows):
                key = str(show.get("ratingKey") or "")
                if not is_item_id(key):
                    continue
                leaves = paged_library_rows(
                    client,
                    user_id,
                    "Episode",
                    [key],
                    MAX_EPISODES_PER_SERIES,
                    request_budget,
                    extra={"SortBy": "ParentIndexNumber,IndexNumber"},
                )
                for raw in leaves:
                    if not isinstance(raw, dict):
                        continue
                    if finite_integer(raw.get("ParentIndexNumber"), -1) != season_number:
                        continue
                    if (
                        episode_number is not None
                        and finite_integer(raw.get("IndexNumber"), -1) != episode_number
                    ):
                        continue
                    item = browse_item(raw, now)
                    if item is not None:
                        episode_rows.append(
                            (
                                show_rank,
                                finite_integer(raw.get("ParentIndexNumber")),
                                finite_integer(raw.get("IndexNumber")),
                                item,
                            )
                        )
            episode_rows.sort(
                key=lambda row: (row[0], row[1], row[2], row[3]["title"].casefold())
            )
            ranked = [item for _, _, _, item in episode_rows]
    total = len(ranked)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "search",
        "scope": scope.value,
        "query": query,
        "offset": offset,
        "limit": limit,
        "total": total,
        "items": ranked[offset : offset + limit],
    }


def season_browse_document(
    client: JellyfinClient,
    config: dict[str, Any],
    parent_rating_key: str,
    query: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    parent_rating_key = valid_item_id(parent_rating_key)
    request_budget = [MAX_SEARCH_REQUESTS]
    rows = paged_library_rows(
        client,
        config["userId"],
        "Season",
        [parent_rating_key],
        MAX_SEASONS_PER_SERIES,
        request_budget,
        recursive=False,
        extra={"SortBy": "IndexNumber,SortName"},
    )
    now = utc_now()
    seasons: list[tuple[int, dict[str, Any]]] = []
    for raw in rows:
        item = browse_item(raw, now)
        if item is None:
            continue
        index = (
            finite_integer(raw.get("IndexNumber"), -1)
            if isinstance(raw, dict)
            else -1
        )
        seasons.append((index, item))
    seasons.sort(key=lambda row: (row[0] < 0, row[0], row[1]["title"].casefold()))
    ranked = [item for _, item in seasons]
    if query:
        ranked = fzf_rank(ranked, query)
    total = len(ranked)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "seasons",
        "query": query,
        "offset": offset,
        "limit": limit,
        "total": total,
        "items": ranked[offset : offset + limit],
    }


def episode_browse_document(
    client: JellyfinClient,
    config: dict[str, Any],
    parent_rating_key: str,
    query: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    parent_rating_key = valid_item_id(parent_rating_key)
    request_budget = [MAX_SEARCH_REQUESTS]
    rows = paged_library_rows(
        client,
        config["userId"],
        "Episode",
        [parent_rating_key],
        MAX_EPISODES_PER_SERIES,
        request_budget,
        extra={"SortBy": "ParentIndexNumber,IndexNumber"},
    )
    title_query, season_number, episode_number = season_query(query)
    episodes: list[tuple[int, int, dict[str, Any]]] = []
    now = utc_now()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        season = finite_integer(raw.get("ParentIndexNumber"), -1)
        episode = finite_integer(raw.get("IndexNumber"), -1)
        if season_number is not None and season != season_number:
            continue
        if episode_number is not None and episode != episode_number:
            continue
        item = browse_item(raw, now)
        if item is not None:
            episodes.append((season, episode, item))
    episodes.sort(key=lambda row: (row[0], row[1], row[2]["title"].casefold()))
    ranked = [item for _, _, item in episodes]
    if title_query:
        ranked = fzf_rank(ranked, title_query)
    total = len(ranked)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "episodes",
        "query": query,
        "offset": offset,
        "limit": limit,
        "total": total,
        "items": ranked[offset : offset + limit],
    }


def browse_document(
    client: JellyfinClient,
    config: dict[str, Any],
    kind: BrowseKind,
    query: str,
    offset: int,
    limit: int,
    parent_rating_key: str = "",
    search_scope: SearchScope = SearchScope.MOVIES,
) -> dict[str, Any]:
    if not isinstance(kind, BrowseKind):
        raise ConfigurationError(
            "Browse kind must be movies, shows, seasons, episodes, or search"
        )
    query = clean_text(query, 80)
    if offset < 0 or offset > 100000 or limit < 1 or limit > MAX_BROWSE_ITEMS:
        raise ConfigurationError("Invalid Jellyfin browse page")
    if kind is BrowseKind.SEARCH:
        if not query:
            raise ConfigurationError("Search requires a query")
        return search_document(client, config, query, offset, limit, search_scope)
    if kind is BrowseKind.SEASONS:
        return season_browse_document(
            client, config, parent_rating_key, query, offset, limit
        )
    if kind is BrowseKind.EPISODES:
        return episode_browse_document(
            client, config, parent_rating_key, query, offset, limit
        )
    include_types = "Movie" if kind is BrowseKind.MOVIES else "Series"
    sections = (
        config["movieSectionIds"]
        if kind is BrowseKind.MOVIES
        else config["tvSectionIds"]
    )
    extra: dict[str, Any] = {
        "StartIndex": offset,
        "Limit": limit,
        "SortBy": "SortName",
        "SortOrder": "Ascending",
        "Fields": "DateCreated,UserData,ParentIndexNumber,IndexNumber,SeriesId,SeriesName,ProductionYear,RunTimeTicks,RecursiveItemCount,ChildCount",
        "IncludeItemTypes": include_types,
        "Recursive": "true",
    }
    if query:
        extra["SearchTerm"] = query
    documents: list[Any] = []
    if sections:
        for section in sections:
            extra["ParentId"] = section
            extra["StartIndex"] = offset
            documents.append(
                client.request_json(
                    "/Users/" + config["userId"] + "/Items?" + _query(extra)
                )
            )
    else:
        extra.pop("ParentId", None)
        documents.append(
            client.request_json("/Users/" + config["userId"] + "/Items?" + _query(extra))
        )
    raw_rows: list[Any] = []
    total = 0
    for document in documents:
        rows = extract_items(document, maximum=MAX_BROWSE_ITEMS)
        raw_rows.extend(rows)
        total += max(
            len(rows),
            finite_integer(
                document.get("TotalRecordCount") if isinstance(document, dict) else 0,
                len(rows),
            ),
        )
    normalized = [
        value
        for value in (browse_item(row, utc_now()) for row in raw_rows)
        if value is not None
    ]
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for item in normalized:
        if item["ratingKey"] in seen:
            continue
        seen.add(item["ratingKey"])
        items.append(item)
        if len(items) >= limit:
            break
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind.value,
        "query": query,
        "offset": offset,
        "limit": limit,
        "total": total,
        "items": items,
    }
