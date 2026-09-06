from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any

from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    ResponseError,
    finite_integer,
    run_bounded_output,
    run_no_output,
)
from omajelly.config import load_config, validate_window_geometry
from omajelly.constants import MAX_HYPR_BYTES, SCHEMA_VERSION

_BROWSER_CLASS_MARKERS = (
    "chromium",
    "google-chrome",
    "chrome",
    "brave",
    "vivaldi",
    "microsoft-edge",
    "msedge",
    "opera",
    "helium",
)

PLAYER_RESET_MARGIN = 16
_HYPR_ADDRESS = re.compile(r"^0x[0-9A-Fa-f]{1,16}$")


def valid_hypr_address(value: Any) -> str:
    address = str(value or "")
    if not _HYPR_ADDRESS.fullmatch(address):
        raise ResponseError("Hyprland returned invalid Omajelly window data")
    return address


def hypr_fullscreen_script(pid: int) -> str:
    if pid <= 0:
        raise ValueError("player PID must be positive")
    return (
        "local target=nil; "
        "for _,w in ipairs(hl.get_windows()) do "
        "if w.pid == " + str(pid) + " then target=w; break end end; "
        "if not target then error('missing') end; "
        "hl.dispatch(hl.dsp.focus({ window = target })); "
        "hl.dispatch(hl.dsp.window.fullscreen_state({ internal = 2, client = 2 })); "
        "return 'ok'"
    )


def ensure_hypr_fullscreen(pid: int) -> None:
    script = hypr_fullscreen_script(pid)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            return_code = run_no_output(["hyprctl", "eval", script], timeout=0.75)
        except FileNotFoundError:
            return
        if return_code == 0:
            return
        time.sleep(0.1)


def hypr_geometry_script(pid: int, geometry: dict[str, int]) -> str:
    if pid <= 0:
        raise ValueError("player PID must be positive")
    value = validate_window_geometry(geometry)
    return (
        "local target=nil; "
        "for _,w in ipairs(hl.get_windows()) do "
        "if w.pid == " + str(pid) + " then target=w; break end end; "
        "if not target then error('missing') end; "
        "hl.dispatch(hl.dsp.window.resize({ x = "
        + str(value["width"])
        + ", y = "
        + str(value["height"])
        + ", relative = false, window = target })); "
        "hl.dispatch(hl.dsp.window.move({ x = "
        + str(value["x"])
        + ", y = "
        + str(value["y"])
        + ", relative = false, window = target })); "
        "return 'ok'"
    )


def hypr_bring_player_script(address: str, workspace: int, x: int, y: int) -> str:
    target = valid_hypr_address(address)
    if workspace <= 0 or workspace > 1_000_000:
        raise ValueError("workspace must be positive")
    if abs(x) > 100_000 or abs(y) > 100_000:
        raise ValueError("player position is invalid")
    return (
        "local target=nil; "
        "for _,w in ipairs(hl.get_windows()) do "
        "if w.address == '"
        + target
        + "' then target=w; break end end; "
        "if not target then error('missing') end; "
        "hl.dispatch(hl.dsp.window.move({ workspace = '"
        + str(workspace)
        + "', follow = false, window = target })); "
        "hl.dispatch(hl.dsp.window.move({ x = "
        + str(x)
        + ", y = "
        + str(y)
        + ", relative = false, window = target })); "
        "hl.dispatch(hl.dsp.focus({ window = target })); "
        "hl.dispatch(hl.dsp.window.alter_zorder({ window = target, mode = 'top' })); "
        "return 'ok'"
    )


def hypr_focus_player_script(address: str, workspace: int) -> str:
    target = valid_hypr_address(address)
    if workspace <= 0 or workspace > 1_000_000:
        raise ValueError("workspace must be positive")
    return (
        "local target=nil; "
        "for _,w in ipairs(hl.get_windows()) do "
        "if w.address == '"
        + target
        + "' then target=w; break end end; "
        "if not target then error('missing') end; "
        "hl.dispatch(hl.dsp.window.move({ workspace = '"
        + str(workspace)
        + "', follow = false, window = target })); "
        "hl.dispatch(hl.dsp.focus({ window = target })); "
        "hl.dispatch(hl.dsp.window.alter_zorder({ window = target, mode = 'top' })); "
        "return 'ok'"
    )


def _hypr_json(name: str) -> Any:
    if name not in {"clients", "monitors"}:
        raise ValueError("unsupported Hyprland query")
    try:
        return_code, output = run_bounded_output(
            ["hyprctl", "-j", name], maximum=MAX_HYPR_BYTES, timeout=2
        )
    except FileNotFoundError as error:
        raise ConfigurationError("Hyprland is unavailable") from error
    if return_code != 0:
        raise ConfigurationError("Hyprland is unavailable")
    try:
        return json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResponseError("Hyprland returned invalid window data") from error


def _browser_class_blob(client: dict[str, Any]) -> str:
    return (
        str(client.get("class") or "") + " " + str(client.get("initialClass") or "")
    ).lower()


def _window_title_blob(client: dict[str, Any]) -> str:
    return (
        str(client.get("title") or "") + " " + str(client.get("initialTitle") or "")
    ).lower()


def _is_standalone_app_class(class_blob: str, host: str) -> bool:
    if "chrome-" not in class_blob:
        return False
    if host and len(host) >= 3:
        folded = host.replace(".", "-")
        if host in class_blob or folded in class_blob:
            return True
    return "jellyfin" in class_blob


def is_jellyfin_webapp_window(client: dict[str, Any], server: str) -> bool:
    if not isinstance(client, dict) or client.get("mapped") is not True:
        return False
    class_blob = _browser_class_blob(client)
    if not any(marker in class_blob for marker in _BROWSER_CLASS_MARKERS):
        return False
    parsed = urllib.parse.urlparse(server)
    host = (parsed.hostname or "").lower()
    if not _is_standalone_app_class(class_blob, host):
        return False
    path = (parsed.path or "").strip("/").split("/")[0].lower()
    title_blob = _window_title_blob(client)
    haystack = class_blob + " " + title_blob
    host_folded = host.replace(".", "-")
    if host and len(host) >= 3 and (host in haystack or host_folded in haystack):
        return True
    if path and len(path) >= 3 and path in haystack.replace("-", "_"):
        return True
    return "jellyfin" in title_blob or "jellyfin" in class_blob


def windowed_player_clients() -> list[dict[str, Any]]:
    config = load_config()
    if config is None:
        return []
    server = str(config["server"])
    clients = _hypr_json("clients")
    if not isinstance(clients, list) or len(clients) > 4096:
        raise ResponseError("Hyprland returned invalid window data")
    result: list[dict[str, Any]] = []
    for client in clients:
        if is_jellyfin_webapp_window(client, server):
            result.append(client)
    return result


def windowed_player_active() -> bool:
    return bool(windowed_player_clients())


def _client_address(client: dict[str, Any]) -> str:
    try:
        return valid_hypr_address(client.get("address"))
    except ResponseError:
        return ""


def mapped_browser_clients() -> list[dict[str, Any]]:
    clients = _hypr_json("clients")
    if not isinstance(clients, list) or len(clients) > 4096:
        raise ResponseError("Hyprland returned invalid window data")
    result: list[dict[str, Any]] = []
    for client in clients:
        if not isinstance(client, dict) or client.get("mapped") is not True:
            continue
        if any(
            marker in _browser_class_blob(client) for marker in _BROWSER_CLASS_MARKERS
        ):
            result.append(client)
    return result


def browser_window_addresses() -> frozenset[str]:
    result: set[str] = set()
    for client in mapped_browser_clients():
        address = _client_address(client)
        if address:
            result.add(address)
    return frozenset(result)


def player_window_addresses() -> frozenset[str]:
    result: set[str] = set()
    for client in windowed_player_clients():
        address = _client_address(client)
        if address:
            result.add(address)
    return frozenset(result)


def _webapp_window_priority(client: dict[str, Any]) -> tuple[int, int]:
    title = _window_title_blob(client)
    is_failed_page = "page not found" in title or "not found" in title
    focus_history = finite_integer(client.get("focusHistoryID"), 1_000_000)
    return (1 if is_failed_page else 0, focus_history)


def bring_player_to_active_workspace(
    *, ignore_addresses: frozenset[str] | None = None
) -> None:
    candidates = windowed_player_clients()
    if ignore_addresses:
        candidates = [
            client
            for client in candidates
            if _client_address(client) not in ignore_addresses
        ]
    if not candidates:
        raise ConfigurationError("No Jellyfin webapp window is open")
    player = min(candidates, key=_webapp_window_priority)
    address = valid_hypr_address(player.get("address"))
    monitors = _hypr_json("monitors")
    if not isinstance(monitors, list) or len(monitors) > 64:
        raise ResponseError("Hyprland returned invalid monitor data")
    focused = next(
        (
            monitor
            for monitor in monitors
            if isinstance(monitor, dict) and monitor.get("focused") is True
        ),
        None,
    )
    if focused is None:
        raise ResponseError("Hyprland did not identify the active monitor")
    active_workspace = focused.get("activeWorkspace")
    reserved = focused.get("reserved")
    if (
        not isinstance(active_workspace, dict)
        or not isinstance(reserved, list)
        or len(reserved) != 4
    ):
        raise ResponseError("Hyprland returned invalid monitor data")
    workspace = finite_integer(active_workspace.get("id"), -1)
    monitor_x = finite_integer(focused.get("x"), 100_001)
    monitor_y = finite_integer(focused.get("y"), 100_001)
    left = finite_integer(reserved[0], -1)
    top = finite_integer(reserved[1], -1)
    if (
        workspace <= 0
        or workspace > 1_000_000
        or abs(monitor_x) > 100_000
        or abs(monitor_y) > 100_000
        or left < 0
        or top < 0
        or left > 10_000
        or top > 10_000
    ):
        raise ResponseError("Hyprland returned invalid monitor data")
    if finite_integer(player.get("fullscreen"), 0) != 0:
        script = hypr_focus_player_script(address, workspace)
    else:
        script = hypr_bring_player_script(
            address,
            workspace,
            monitor_x + left + PLAYER_RESET_MARGIN,
            monitor_y + top + PLAYER_RESET_MARGIN,
        )
    try:
        return_code = run_no_output(["hyprctl", "eval", script], timeout=2)
    except FileNotFoundError as error:
        raise ConfigurationError("Hyprland is unavailable") from error
    if return_code != 0:
        raise ResponseError("Could not move the Omajelly player")


def geometry_is_visible(geometry: dict[str, int]) -> bool:
    value = validate_window_geometry(geometry)
    try:
        return_code, output = run_bounded_output(
            ["hyprctl", "-j", "monitors"], maximum=MAX_HYPR_BYTES, timeout=2
        )
    except (FileNotFoundError, JellyfinError):
        return False
    if return_code != 0:
        return False
    try:
        monitors = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(monitors, list) or len(monitors) > 64:
        return False
    right = value["x"] + value["width"]
    bottom = value["y"] + value["height"]
    for monitor in monitors:
        if not isinstance(monitor, dict):
            continue
        x = finite_integer(monitor.get("x"), 100001)
        y = finite_integer(monitor.get("y"), 100001)
        width = finite_integer(monitor.get("width"), 0)
        height = finite_integer(monitor.get("height"), 0)
        if width <= 0 or height <= 0 or width > 100000 or height > 100000:
            continue
        overlap_width = max(0, min(right, x + width) - max(value["x"], x))
        overlap_height = max(0, min(bottom, y + height) - max(value["y"], y))
        if overlap_width >= min(64, value["width"]) and overlap_height >= min(
            64, value["height"]
        ):
            return True
    return False


def restore_hypr_geometry(pid: int, geometry: dict[str, int]) -> None:
    if not geometry_is_visible(geometry):
        return
    script = hypr_geometry_script(pid, geometry)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            return_code = run_no_output(["hyprctl", "eval", script], timeout=0.75)
        except FileNotFoundError:
            return
        if return_code == 0:
            return
        time.sleep(0.1)


def read_hypr_geometry(pid: int) -> dict[str, int] | None:
    if pid <= 0:
        return None
    try:
        return_code, output = run_bounded_output(
            ["hyprctl", "-j", "clients"], maximum=MAX_HYPR_BYTES, timeout=2
        )
    except (FileNotFoundError, JellyfinError):
        return None
    if return_code != 0:
        return None
    try:
        clients = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(clients, list) or len(clients) > 4096:
        return None
    for client in clients:
        if not isinstance(client, dict) or finite_integer(client.get("pid"), -1) != pid:
            continue
        position = client.get("at")
        size = client.get("size")
        if (
            client.get("mapped") is not True
            or client.get("floating") is not True
            or finite_integer(client.get("fullscreen"), -1) != 0
            or not isinstance(position, list)
            or len(position) != 2
            or not isinstance(size, list)
            or len(size) != 2
        ):
            return None
        try:
            return validate_window_geometry(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "x": int(position[0]),
                    "y": int(position[1]),
                    "width": int(size[0]),
                    "height": int(size[1]),
                }
            )
        except (TypeError, ValueError, OverflowError, JellyfinError):
            return None
    return None
