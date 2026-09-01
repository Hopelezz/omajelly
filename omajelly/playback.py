from __future__ import annotations

import contextlib
import http.server
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from omajelly.client import HttpMethod, JellyfinClient
from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    ResponseError,
    clean_text,
    finite_integer,
    wall_deadline,
)
from omajelly.config import (
    load_window_geometry,
    save_window_geometry,
    validate_window_geometry,
)
from omajelly.connection import client_from_saved
from omajelly.constants import MAX_PLAY_QUEUE_ITEMS, PLUGIN_ID
from omajelly.ids import is_item_id, valid_item_id
from omajelly.media_items import item_type, ticks_to_ms, ticks_to_seconds, user_data
from omajelly.subtitles import subtitle_language
from omajelly.windowing import (
    ensure_hypr_fullscreen,
    read_hypr_geometry,
    restore_hypr_geometry,
)


class PlaybackMode(StrEnum):
    WINDOWED = "windowed"
    FULLSCREEN = "fullscreen"


class TimelineState(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"


class WatchState(StrEnum):
    WATCHED = "watched"
    UNWATCHED = "unwatched"


@dataclass(frozen=True, slots=True)
class PlaybackItem:
    rating_key: str
    media_type: str
    stream_path: str
    media_source_id: str
    play_session_id: str
    resume_seconds: int
    duration_ms: int
    subtitle_paths: tuple[str, ...]


def _stream_path(item_id: str, media_source_id: str) -> str:
    query = urllib.parse.urlencode(
        {"Static": "true", "MediaSourceId": media_source_id}
    )
    return "/Videos/" + item_id + "/stream?" + query


def playback_item_from_info(
    item: dict[str, Any], playback: dict[str, Any]
) -> PlaybackItem:
    rating_key = valid_item_id(item.get("Id"))
    media_type = item_type(item)
    if media_type == "Episode":
        kind = "episode"
    elif media_type == "Movie":
        kind = "movie"
    else:
        raise ResponseError("Jellyfin returned unsupported playable media")
    sources = playback.get("MediaSources")
    if not isinstance(sources, list) or not sources or not isinstance(sources[0], dict):
        raise ResponseError("Jellyfin returned no playable media")
    source = sources[0]
    media_source_id = str(source.get("Id") or "")
    if not media_source_id or len(media_source_id) > 128:
        raise ResponseError("Jellyfin returned an invalid media source")
    play_session_id = str(playback.get("PlaySessionId") or secrets.token_hex(8))
    subtitle_paths: list[str] = []
    streams = source.get("MediaStreams")
    if isinstance(streams, list):
        for stream in streams[:64]:
            if not isinstance(stream, dict) or str(stream.get("Type") or "") != "Subtitle":
                continue
            index = finite_integer(stream.get("Index"), -1)
            if index < 0:
                continue
            codec = str(stream.get("Codec") or "srt").lower()
            if codec not in {"ass", "smi", "srt", "ssa", "sub", "vtt"}:
                codec = "srt"
            path = (
                "/Videos/"
                + rating_key
                + "/"
                + urllib.parse.quote(media_source_id, safe="")
                + "/Subtitles/"
                + str(index)
                + "/Stream."
                + codec
            )
            subtitle_paths.append(path)
            if len(subtitle_paths) >= 16:
                break
    data = user_data(item)
    return PlaybackItem(
        rating_key=rating_key,
        media_type=kind,
        stream_path=_stream_path(rating_key, media_source_id),
        media_source_id=media_source_id,
        play_session_id=play_session_id,
        resume_seconds=ticks_to_seconds(data.get("PlaybackPositionTicks")),
        duration_ms=ticks_to_ms(item.get("RunTimeTicks") or source.get("RunTimeTicks")),
        subtitle_paths=tuple(subtitle_paths),
    )


def fetch_item(client: JellyfinClient, item_id: str) -> dict[str, Any]:
    document = client.request_json(
        "/Users/"
        + client.user_id
        + "/Items/"
        + item_id
        + "?Fields=MediaSources,UserData,ParentIndexNumber,IndexNumber,SeriesId,RunTimeTicks"
    )
    if not isinstance(document, dict):
        raise ResponseError("Jellyfin returned no playable metadata")
    return document


def fetch_playback_info(client: JellyfinClient, item_id: str) -> dict[str, Any]:
    document = client.request_json(
        "/Items/"
        + item_id
        + "/PlaybackInfo?"
        + urllib.parse.urlencode({"UserId": client.user_id})
    )
    if not isinstance(document, dict):
        raise ResponseError("Jellyfin returned no playable media")
    return document


def single_playback_item(client: JellyfinClient, rating_key: str) -> PlaybackItem:
    rating_key = valid_item_id(rating_key)
    item = fetch_item(client, rating_key)
    info = fetch_playback_info(client, rating_key)
    result = playback_item_from_info(item, info)
    if result.rating_key != rating_key:
        raise ResponseError("Jellyfin returned the wrong playable item")
    return result


def queued_playback_items(
    client: JellyfinClient, rating_key: str
) -> list[PlaybackItem]:
    first = single_playback_item(client, rating_key)
    if first.media_type != "episode":
        return [first]
    item = fetch_item(client, rating_key)
    series_id = str(item.get("SeriesId") or "")
    if not is_item_id(series_id):
        return [first]
    document = client.request_json(
        "/Shows/"
        + series_id
        + "/Episodes?"
        + urllib.parse.urlencode(
            {
                "UserId": client.user_id,
                "Fields": "UserData,RunTimeTicks,MediaSources,ParentIndexNumber,IndexNumber,SeriesId",
            }
        )
    )
    rows = document.get("Items", []) if isinstance(document, dict) else []
    if not isinstance(rows, list):
        return [first]
    start = -1
    for index, raw in enumerate(rows):
        if isinstance(raw, dict) and str(raw.get("Id") or "") == rating_key:
            start = index
            break
    if start < 0:
        return [first]
    result = [first]
    for raw in rows[start + 1 : start + MAX_PLAY_QUEUE_ITEMS]:
        if not isinstance(raw, dict) or item_type(raw) != "Episode":
            break
        episode_id = str(raw.get("Id") or "")
        if not is_item_id(episode_id):
            continue
        try:
            result.append(single_playback_item(client, episode_id))
        except JellyfinError:
            break
        if len(result) >= MAX_PLAY_QUEUE_ITEMS:
            break
    return result


def playback_items(
    client: JellyfinClient,
    rating_key: str,
    auto_play_next: bool,
) -> list[PlaybackItem]:
    if auto_play_next:
        try:
            return queued_playback_items(client, rating_key)
        except JellyfinError:
            pass
    return [single_playback_item(client, rating_key)]


def report_timeline(
    client: JellyfinClient,
    item: PlaybackItem,
    position_ms: int,
    state: TimelineState,
) -> None:
    ticks = max(0, position_ms) * 10_000
    body = {
        "ItemId": item.rating_key,
        "MediaSourceId": item.media_source_id,
        "PlaySessionId": item.play_session_id,
        "PositionTicks": ticks,
        "IsPaused": state is TimelineState.PAUSED,
        "IsMuted": False,
        "PlayMethod": "DirectStream",
        "CanSeek": True,
    }
    if state is TimelineState.STOPPED:
        path = "/Sessions/Playing/Stopped"
    elif state is TimelineState.PLAYING and position_ms <= item.resume_seconds * 1000:
        path = "/Sessions/Playing"
    else:
        path = "/Sessions/Playing/Progress"
    client.request_json(path, method=HttpMethod.POST, body=body)


def set_watch_state(
    client: JellyfinClient, rating_key: str, state: WatchState
) -> None:
    rating_key = valid_item_id(rating_key)
    if not isinstance(state, WatchState):
        raise ConfigurationError("Invalid Jellyfin watch state")
    path = "/Users/" + client.user_id + "/PlayedItems/" + rating_key
    if state is WatchState.WATCHED:
        client.request_empty(path, method=HttpMethod.POST)
    else:
        client.request_empty(path, method=HttpMethod.DELETE)


def mpv_status(socket_path: str) -> tuple[int, bool, int] | None:
    requests = (
        b'{"command":["get_property","time-pos"],"request_id":1}\n'
        b'{"command":["get_property","pause"],"request_id":2}\n'
        b'{"command":["get_property","playlist-pos"],"request_id":3}\n'
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            connection.connect(socket_path)
            connection.sendall(requests)
            payload = bytearray()
            while payload.count(b"\n") < 3 and len(payload) <= 8192:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                payload.extend(chunk)
    except (TimeoutError, FileNotFoundError, ConnectionRefusedError, OSError):
        return None
    if len(payload) > 8192:
        return None
    values: dict[int, Any] = {}
    for line in bytes(payload).splitlines()[:8]:
        try:
            document = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(document, dict) and document.get("error") == "success":
            values[finite_integer(document.get("request_id"), -1)] = document.get(
                "data"
            )
    try:
        seconds = float(values[1])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not (seconds >= 0 and seconds < 10**9):
        return None
    playlist_position = finite_integer(values.get(3), -1)
    if playlist_position < 0 or playlist_position >= MAX_PLAY_QUEUE_ITEMS:
        return None
    return int(seconds * 1000), values.get(2) is True, playlist_position


class ThreadedServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.request_slots = threading.BoundedSemaphore(4)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()


def proxy_handler(
    client: JellyfinClient, routes: dict[str, str]
) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_HEAD(self) -> None:
            self.proxy(HttpMethod.HEAD)

        def do_GET(self) -> None:
            self.proxy(HttpMethod.GET)

        def proxy(self, method: HttpMethod) -> None:
            expected_host = "127.0.0.1:" + str(self.server.server_address[1])
            if self.headers.get("Host", "") != expected_host or self.headers.get(
                "Origin"
            ):
                self.send_error(403)
                return
            parsed_path = urllib.parse.urlsplit(self.path)
            upstream_path = routes.get(parsed_path.path)
            if upstream_path is None or parsed_path.query:
                self.send_error(404)
                return
            range_header = self.headers.get("Range", "")
            if range_header and not re.fullmatch(
                r"bytes=\d*-\d*(?:,\d*-\d*)*", range_header
            ):
                self.send_error(416)
                return
            try:
                response = client.open(
                    upstream_path, method=method, range_header=range_header
                )
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                self.send_error(status if 400 <= status <= 599 else 502)
                return
            except JellyfinError:
                self.send_error(502)
                return
            try:
                self.send_response(int(getattr(response, "status", response.getcode())))
                for name in [
                    "Content-Type",
                    "Content-Length",
                    "Content-Range",
                    "Accept-Ranges",
                    "Last-Modified",
                    "ETag",
                ]:
                    value = response.headers.get(name)
                    if value:
                        self.send_header(name, clean_text(value, 512))
                self.send_header("Connection", "close")
                self.end_headers()
                if method is HttpMethod.GET:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                response.close()

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def mpv_playlist_arguments(
    mode: PlaybackMode,
    entries: list[tuple[str, int, list[str]]],
    ipc_socket: str = "",
    window_geometry: dict[str, int] | None = None,
    subtitle_script: str = "",
    helper_command: str = "",
    rating_keys: list[str] | None = None,
    subtitle_search_language: str = "en",
    subtitle_output_directory: str = "",
) -> list[str]:
    if not isinstance(mode, PlaybackMode):
        raise ConfigurationError("Playback mode must be windowed or fullscreen")
    if not entries or len(entries) > MAX_PLAY_QUEUE_ITEMS:
        raise ConfigurationError("Invalid Jellyfin playback queue")
    arguments = [
        "mpv",
        "--no-config",
        "--no-ytdl",
        "--really-quiet",
        "--keep-open=no",
        "--force-window=yes",
        "--osc=yes",
        "--input-default-bindings=yes",
        "--osd-level=1",
        "--title=Omajelly",
    ]
    if mode is PlaybackMode.FULLSCREEN:
        arguments.extend(
            [
                "--wayland-app-id=" + PLUGIN_ID + ".player",
                "--fullscreen",
            ]
        )
    elif window_geometry is not None:
        geometry = validate_window_geometry(window_geometry)
        arguments.append(
            "--geometry=" + str(geometry["width"]) + "x" + str(geometry["height"])
        )
    else:
        arguments.extend(["--autofit=960x540", "--geometry=50%:50%"])
    if ipc_socket:
        if not ipc_socket.startswith("/tmp/") or len(ipc_socket) > 512:
            raise ConfigurationError("Invalid player IPC path")
        arguments.append("--input-ipc-server=" + ipc_socket)
    subtitle_options = [
        subtitle_script,
        helper_command,
        ":".join(rating_keys or []),
        subtitle_output_directory,
    ]
    if any(subtitle_options):
        if not all(subtitle_options):
            raise ConfigurationError("Incomplete subtitle search configuration")
        if (
            not subtitle_script.startswith("/")
            or not helper_command.startswith("/")
            or len(subtitle_script) > 512
            or len(helper_command) > 512
            or not subtitle_output_directory.startswith("/tmp/omajelly-player-")
            or len(subtitle_output_directory) > 512
        ):
            raise ConfigurationError("Invalid subtitle search configuration")
        if len(rating_keys or []) != len(entries) or any(
            not is_item_id(key) for key in (rating_keys or [])
        ):
            raise ConfigurationError("Invalid subtitle search media identifiers")
        language = subtitle_language(subtitle_search_language)
        arguments.extend(
            [
                "--script=" + subtitle_script,
                "--script-opt=omajelly_subtitles-helper=" + helper_command,
                "--script-opt=omajelly_subtitles-rating_keys="
                + ":".join(rating_keys or []),
                "--script-opt=omajelly_subtitles-language=" + language,
                "--script-opt=omajelly_subtitles-output_directory="
                + subtitle_output_directory,
            ]
        )
    for url, resume_seconds, subtitle_urls in entries:
        if not url.startswith("http://127.0.0.1:") or len(url) > 1024:
            raise ConfigurationError("Invalid local playback URL")
        arguments.append("--{")
        if resume_seconds > 0:
            arguments.append("--start=" + str(resume_seconds))
        for subtitle_url in subtitle_urls[:16]:
            if (
                not subtitle_url.startswith("http://127.0.0.1:")
                or len(subtitle_url) > 1024
            ):
                raise ConfigurationError("Invalid local subtitle URL")
            arguments.append("--sub-file=" + subtitle_url)
        arguments.extend([url, "--}"])
    return arguments


def finish_playback_item(
    client: JellyfinClient, item: PlaybackItem, position_ms: int
) -> None:
    with contextlib.suppress(JellyfinError):
        report_timeline(client, item, position_ms, TimelineState.STOPPED)
    if item.duration_ms > 0 and position_ms >= int(item.duration_ms * 0.9):
        with contextlib.suppress(JellyfinError):
            set_watch_state(client, item.rating_key, WatchState.WATCHED)


def play(
    rating_key: str,
    mode: PlaybackMode,
    auto_play_next: bool = False,
    subtitle_search_language: str = "en",
) -> int:
    if not isinstance(mode, PlaybackMode):
        raise ConfigurationError("Playback mode must be windowed or fullscreen")
    language = subtitle_language(subtitle_search_language)
    with wall_deadline(20, "Jellyfin playback setup exceeded twenty seconds"):
        client, _config = client_from_saved()
        items = playback_items(client, rating_key, auto_play_next)
    nonce = secrets.token_urlsafe(24)
    routes: dict[str, str] = {}
    public_items: list[tuple[str, list[str]]] = []
    for item_index, item in enumerate(items):
        public_path = "/stream/" + nonce + "/" + str(item_index)
        routes[public_path] = item.stream_path
        subtitle_public_paths: list[str] = []
        for subtitle_index, subtitle_path in enumerate(item.subtitle_paths):
            subtitle_public_path = (
                "/subtitle/" + nonce + "/" + str(item_index) + "/" + str(subtitle_index)
            )
            routes[subtitle_public_path] = subtitle_path
            subtitle_public_paths.append(subtitle_public_path)
        public_items.append((public_path, subtitle_public_paths))
    server = ThreadedServer(("127.0.0.1", 0), proxy_handler(client, routes))
    port = int(server.server_address[1])
    thread = threading.Thread(
        target=server.serve_forever, name="jellyfin-stream-proxy", daemon=True
    )
    thread.start()
    local_origin = "http://127.0.0.1:" + str(port)
    entries = [
        (
            local_origin + public_path,
            item.resume_seconds,
            [local_origin + path for path in subtitle_paths],
        )
        for item, (public_path, subtitle_paths) in zip(items, public_items, strict=True)
    ]
    current_index = 0
    last_position_ms = items[0].resume_seconds * 1000
    saved_geometry: dict[str, int] | None = None
    if mode is PlaybackMode.WINDOWED:
        with contextlib.suppress(JellyfinError, OSError):
            saved_geometry = load_window_geometry()
    try:
        with tempfile.TemporaryDirectory(
            prefix="omajelly-player-", dir="/tmp"
        ) as ipc_directory:
            os.chmod(ipc_directory, 0o700)
            ipc_socket = str(Path(ipc_directory) / "mpv.sock")
            plugin_root = Path(__file__).resolve().parents[1]
            subtitle_script = str(plugin_root / "assets" / "omajelly_subtitles.lua")
            helper_command = str(plugin_root / "bin" / "omajelly")
            player = subprocess.Popen(
                mpv_playlist_arguments(
                    mode,
                    entries,
                    ipc_socket,
                    saved_geometry,
                    subtitle_script,
                    helper_command,
                    [item.rating_key for item in items],
                    language,
                    ipc_directory,
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if mode is PlaybackMode.FULLSCREEN:
                ensure_hypr_fullscreen(player.pid)
            elif saved_geometry is not None:
                restore_hypr_geometry(player.pid, saved_geometry)
            next_report = 0.0
            next_geometry_check = 0.0
            geometry_candidate: dict[str, int] | None = None
            geometry_stable_checks = 0
            latest_geometry: dict[str, int] | None = None
            return_code = player.poll()
            started: set[int] = set()
            while return_code is None:
                now = time.monotonic()
                status = mpv_status(ipc_socket)
                if status is not None:
                    position_ms, paused, playlist_position = status
                    if playlist_position < len(items):
                        if playlist_position != current_index:
                            finish_playback_item(
                                client, items[current_index], last_position_ms
                            )
                            current_index = playlist_position
                            next_report = 0.0
                        last_position_ms = position_ms
                        if now >= next_report:
                            with contextlib.suppress(JellyfinError):
                                if current_index not in started:
                                    report_timeline(
                                        client,
                                        items[current_index],
                                        last_position_ms,
                                        TimelineState.PLAYING,
                                    )
                                    started.add(current_index)
                                report_timeline(
                                    client,
                                    items[current_index],
                                    last_position_ms,
                                    TimelineState.PAUSED
                                    if paused
                                    else TimelineState.PLAYING,
                                )
                            next_report = now + 10
                if mode is PlaybackMode.WINDOWED and now >= next_geometry_check:
                    captured_geometry = read_hypr_geometry(player.pid)
                    if captured_geometry is not None:
                        latest_geometry = captured_geometry
                        if captured_geometry == geometry_candidate:
                            geometry_stable_checks += 1
                        else:
                            geometry_candidate = captured_geometry
                            geometry_stable_checks = 1
                        if (
                            geometry_stable_checks >= 2
                            and captured_geometry != saved_geometry
                        ):
                            try:
                                save_window_geometry(captured_geometry)
                                saved_geometry = captured_geometry
                            except (JellyfinError, OSError):
                                pass
                    next_geometry_check = now + 2
                time.sleep(0.5)
                return_code = player.poll()
            if (
                mode is PlaybackMode.WINDOWED
                and latest_geometry is not None
                and latest_geometry != saved_geometry
            ):
                with contextlib.suppress(JellyfinError, OSError):
                    save_window_geometry(latest_geometry)
            finish_playback_item(client, items[current_index], last_position_ms)
    except FileNotFoundError as error:
        raise ConfigurationError("mpv is not installed") from error
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if return_code != 0:
        raise ResponseError("mpv could not play this Jellyfin item")
    return return_code


def jellyfin_web_url(config: dict[str, Any], rating_key: str = "") -> str:
    origin = str(config["server"])
    if rating_key == "":
        return origin + "/web/"
    rating_key = valid_item_id(rating_key)
    return origin + "/web/#/details?id=" + urllib.parse.quote(rating_key, safe="")
