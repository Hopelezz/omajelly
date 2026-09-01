from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    ResponseError,
    finite_integer,
    read_regular_file,
    run_bounded_output,
    run_no_output,
)
from omajelly.config import validate_window_geometry
from omajelly.constants import MAX_HYPR_BYTES, PLUGIN_ID, SCHEMA_VERSION

PLAYER_APP_ID = PLUGIN_ID + ".player"
PLAYER_RESET_MARGIN = 16


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


def hypr_bring_player_script(pid: int, workspace: int, x: int, y: int) -> str:
    if pid <= 0:
        raise ValueError("player PID must be positive")
    if workspace <= 0 or workspace > 1_000_000:
        raise ValueError("workspace must be positive")
    if abs(x) > 100_000 or abs(y) > 100_000:
        raise ValueError("player position is invalid")
    return (
        "local target=nil; "
        "for _,w in ipairs(hl.get_windows()) do "
        "if w.pid == " + str(pid) + " then target=w; break end end; "
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


def _process_parent_id(pid: int) -> int:
    if pid <= 0 or pid > 2_147_483_647:
        return -1
    try:
        payload = read_regular_file(Path("/proc") / str(pid) / "status", 16 * 1024)
    except (OSError, JellyfinError):
        return -1
    for line in payload.splitlines():
        if line.startswith(b"PPid:"):
            return finite_integer(line.removeprefix(b"PPid:").strip(), -1)
    return -1


def _is_omajelly_play_helper(pid: int) -> bool:
    if pid <= 0 or pid > 2_147_483_647:
        return False
    try:
        payload = read_regular_file(Path("/proc") / str(pid) / "cmdline", 16 * 1024)
    except (OSError, JellyfinError):
        return False
    arguments = [part for part in payload.split(b"\0") if part]
    if len(arguments) < 2:
        return False
    helpers = {
        str(Path(__file__).resolve().parents[1] / "bin" / "omajelly").encode(),
        str(
            Path.home()
            / ".config"
            / "omarchy"
            / "plugins"
            / PLUGIN_ID
            / "bin"
            / "omajelly"
        ).encode(),
    }
    if arguments[0] in helpers:
        return arguments[1] == b"play"
    return len(arguments) >= 3 and arguments[1] in helpers and arguments[2] == b"play"


def windowed_player_clients() -> list[dict[str, Any]]:
    clients = _hypr_json("clients")
    if not isinstance(clients, list) or len(clients) > 4096:
        raise ResponseError("Hyprland returned invalid window data")
    result: list[dict[str, Any]] = []
    for client in clients:
        if not isinstance(client, dict) or client.get("mapped") is not True:
            continue
        pid = finite_integer(client.get("pid"), -1)
        window_class = str(client.get("class") or "")
        initial_class = str(client.get("initialClass") or "")
        if (
            _is_omajelly_play_helper(_process_parent_id(pid))
            and (
                window_class in {"mpv", PLAYER_APP_ID}
                or initial_class in {"mpv", PLAYER_APP_ID}
            )
            and (
                client.get("title") == "Omajelly"
                or client.get("initialTitle") == "Omajelly"
            )
            and finite_integer(client.get("fullscreen"), -1) == 0
        ):
            result.append(client)
    return result


def windowed_player_active() -> bool:
    return bool(windowed_player_clients())


def bring_player_to_active_workspace() -> None:
    candidates = windowed_player_clients()
    if not candidates:
        raise ConfigurationError("No windowed Omajelly player is running")
    player = max(candidates, key=lambda value: finite_integer(value.get("pid"), -1))
    pid = finite_integer(player.get("pid"), -1)
    if pid <= 0 or pid > 2_147_483_647 or player.get("floating") is not True:
        raise ResponseError("Hyprland returned invalid Omajelly window data")
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
    script = hypr_bring_player_script(
        pid,
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
