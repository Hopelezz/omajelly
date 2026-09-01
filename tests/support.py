from __future__ import annotations

from datetime import datetime, timezone

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

USER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1"
MOVIE_LIB = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb1"
SHOW_LIB = "ccccccccccccccccccccccccccccccc1"
MOVIE = "ddddddddddddddddddddddddddddddd1"
MOVIE_B = "ddddddddddddddddddddddddddddddd2"
MOVIE_C = "ddddddddddddddddddddddddddddddd3"
SHOW = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeee1"
SHOW_B = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeee2"
EP1 = "ffffffffffffffffffffffffffffff01"
EP2 = "ffffffffffffffffffffffffffffff02"
EP3 = "ffffffffffffffffffffffffffffff03"
EP4 = "ffffffffffffffffffffffffffffff04"
SEASON1 = "11111111111111111111111111111101"
SEASON2 = "11111111111111111111111111111102"
TOKEN = "JellyfinTokenStayPrivate"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def items(*rows):
    return {"Items": list(rows), "TotalRecordCount": len(rows)}


def movie(
    item_id: str,
    name: str,
    *,
    year: int = 2024,
    created=None,
    played: bool = False,
    position_ticks: int = 0,
    last_played=None,
    runtime_ticks: int = 100 * 10_000_000,
) -> dict:
    data = {
        "Played": played,
        "PlaybackPositionTicks": position_ticks,
        "UnplayedItemCount": 0,
    }
    if last_played is not None:
        data["LastPlayedDate"] = iso(last_played) if isinstance(last_played, datetime) else last_played
    return {
        "Id": item_id,
        "Type": "Movie",
        "Name": name,
        "ProductionYear": year,
        "DateCreated": iso(created or NOW),
        "RunTimeTicks": runtime_ticks,
        "UserData": data,
    }


def episode(
    item_id: str,
    series_name: str,
    *,
    series_id: str = SHOW,
    season: int = 1,
    index: int = 1,
    title: str = "Episode",
    created=None,
    played: bool = False,
    position_ticks: int = 0,
    last_played=None,
    runtime_ticks: int = 100 * 10_000_000,
) -> dict:
    data = {
        "Played": played,
        "PlaybackPositionTicks": position_ticks,
        "UnplayedItemCount": 0,
    }
    if last_played is not None:
        data["LastPlayedDate"] = iso(last_played) if isinstance(last_played, datetime) else last_played
    return {
        "Id": item_id,
        "Type": "Episode",
        "Name": title,
        "SeriesName": series_name,
        "SeriesId": series_id,
        "ParentIndexNumber": season,
        "IndexNumber": index,
        "DateCreated": iso(created or NOW),
        "RunTimeTicks": runtime_ticks,
        "UserData": data,
    }


def season(
    item_id: str,
    name: str,
    *,
    series_id: str = SHOW,
    index: int = 1,
    leaf_count: int = 10,
    unplayed: int = 7,
    created=None,
) -> dict:
    return {
        "Id": item_id,
        "Type": "Season",
        "Name": name,
        "SeriesId": series_id,
        "IndexNumber": index,
        "RecursiveItemCount": leaf_count,
        "ChildCount": leaf_count,
        "DateCreated": iso(created or NOW),
        "UserData": {
            "Played": unplayed == 0 and leaf_count > 0,
            "PlaybackPositionTicks": 0,
            "UnplayedItemCount": unplayed,
        },
    }


def series(
    item_id: str,
    name: str,
    *,
    leaf_count: int = 10,
    unplayed: int = 7,
    created=None,
) -> dict:
    return {
        "Id": item_id,
        "Type": "Series",
        "Name": name,
        "RecursiveItemCount": leaf_count,
        "ChildCount": leaf_count,
        "DateCreated": iso(created or NOW),
        "UserData": {
            "Played": unplayed == 0 and leaf_count > 0,
            "PlaybackPositionTicks": 0,
            "UnplayedItemCount": unplayed,
        },
    }


class FakeClient:
    def __init__(self, responses, user_id=USER, token=TOKEN):
        self.responses = responses
        self.paths = []
        self.user_id = user_id
        self.token = token

    def request_json(self, path, **kwargs):
        self.paths.append(path)
        for needle, response in self.responses.items():
            if needle in path:
                if callable(response):
                    return response(path, **kwargs)
                return response
        raise AssertionError("unexpected path: " + path)

    def request_empty(self, path, **kwargs):
        self.paths.append(path)

    def open(self, path, **kwargs):
        self.paths.append(path)
        raise AssertionError("unexpected open: " + path)

    def discover(self):
        views = self.request_json("/Users/" + self.user_id + "/Views")
        rows = views.get("Items", []) if isinstance(views, dict) else views
        libraries = []
        for raw in rows:
            collection = str(raw.get("CollectionType") or "").lower()
            if collection == "movies":
                kind = "movie"
            elif collection in {"tvshows", "tv"}:
                kind = "show"
            else:
                continue
            libraries.append(
                {"id": raw["Id"], "type": kind, "title": raw.get("Name") or ""}
            )
        return libraries, self.user_id, "Living Room"


class FakeStore:
    def __init__(self, token=None):
        self.token = token
        self.stored = []
        self.cleared = False

    def lookup(self):
        return self.token

    def store(self, token):
        self.token = token
        self.stored.append(token)

    def clear(self):
        self.token = None
        self.cleared = True
