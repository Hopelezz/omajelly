from __future__ import annotations

import contextlib
import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any

from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    atomic_json_write,
    launch_detached,
    read_json_file,
    read_regular_file,
    run_no_output,
    unlink_private_file,
)
from omajelly.config import config_home, load_config
from omajelly.constants import MAX_CONFIG_BYTES, SCHEMA_VERSION

WEBAPP_NAME = "Jellyfin"
WEBAPP_INSTALLER = "omarchy-webapp-install"
WEBAPP_LAUNCHER = "omarchy-launch-webapp"
WEBAPP_REMOVER = "omarchy-webapp-remove"
WEBAPP_ICON = "applications-multimedia"
_LAUNCHERS = (WEBAPP_LAUNCHER, "xdg-open")
_OMARCHY_BIN = Path("/usr/share/omarchy/bin")
_URL_IN_EXEC = re.compile(r"https?://[^\s\"']+")
_JELLYFIN_BROWSER_FLAGS = (
    "--new-window",
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--ozone-platform=x11",
)
_AUTOPLAY_SCRIPT = (
    Path(__file__).resolve().parents[1] / "assets" / "jellyfin-web-autoplay" / "autoplay.js"
)


def applications_directory() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "applications"


def created_webapp_path() -> Path:
    return config_home() / "created-webapp.json"


def _desktop_payload(path: Path) -> str:
    try:
        payload = read_regular_file(path, MAX_CONFIG_BYTES)
    except (OSError, JellyfinError):
        return ""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _exec_line_is_webapp(line: str) -> bool:
    return line.startswith("Exec=") and any(launcher in line for launcher in _LAUNCHERS)


def _exec_urls(payload: str) -> list[str]:
    urls: list[str] = []
    for line in payload.splitlines()[:80]:
        if not _exec_line_is_webapp(line):
            continue
        for match in _URL_IN_EXEC.findall(line)[:4]:
            urls.append(match.rstrip("\\"))
    return urls


def _origins_match(app_url: str, server: str) -> bool:
    app = urllib.parse.urlparse(app_url)
    origin = urllib.parse.urlparse(server)
    if (app.scheme or "").lower() not in {"http", "https"}:
        return False
    if (app.hostname or "").lower() != (origin.hostname or "").lower():
        return False
    app_path = (app.path or "/").rstrip("/") or "/"
    origin_path = (origin.path or "/").rstrip("/") or "/"
    if origin_path == "/":
        return True
    return app_path == origin_path or app_path.startswith(origin_path + "/")


def _webapp_url(config: dict[str, Any]) -> str:
    return str(config["server"]) + "/web/"


def resolve_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for directory in (_OMARCHY_BIN, Path("/usr/bin")):
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise ConfigurationError(name + " is unavailable")


def graphical_env() -> dict[str, str]:
    environment = os.environ.copy()
    parts = [part for part in environment.get("PATH", "").split(":") if part]
    extra = str(_OMARCHY_BIN)
    if extra not in parts:
        parts.insert(0, extra)
    environment["PATH"] = ":".join(parts)
    return environment


def _transient_user_command(command: list[str]) -> list[str]:
    try:
        runner = resolve_tool("systemd-run")
    except ConfigurationError:
        return command
    return [
        runner,
        "--user",
        "--collect",
        "--quiet",
        "--no-block",
        "--",
        *command,
    ]


def _desktop_uses_app_window(path: str) -> bool:
    return WEBAPP_LAUNCHER in _desktop_payload(Path(path))


def _needs_webapp_install(found: dict[str, str] | None) -> bool:
    if found is None:
        return True
    return not _desktop_uses_app_window(found["path"])


def prepare_autoplay_extension(url: str) -> Path | None:
    if not _AUTOPLAY_SCRIPT.is_file():
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    directory = config_home() / "web-autoplay"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(_AUTOPLAY_SCRIPT, directory / "autoplay.js")
    atomic_json_write(
        directory / "manifest.json",
        {
            "manifest_version": 3,
            "name": "Omajelly autoplay",
            "version": "1.0",
            "content_scripts": [
                {
                    "matches": [parsed.scheme + "://" + parsed.netloc + "/*"],
                    "js": ["autoplay.js"],
                    "run_at": "document_idle",
                }
            ],
        },
        4096,
    )
    return directory


def launch_webapp(url: str, extra: list[str] | None = None) -> None:
    command = [resolve_tool(WEBAPP_LAUNCHER), url]
    if extra:
        command.extend(extra)
    _refuse_if_secret(command)
    try:
        launch_detached(_transient_user_command(command), env=graphical_env())
    except FileNotFoundError as error:
        raise ConfigurationError("omarchy-launch-webapp is unavailable") from error


def launch_jellyfin_webapp(url: str, extra: list[str] | None = None) -> None:
    install_jellyfin_webapp()
    command = [resolve_tool("chromium"), "--app=" + url]
    arguments = list(_JELLYFIN_BROWSER_FLAGS)
    if extra:
        arguments.extend(value for value in extra if value not in arguments)
    extension = prepare_autoplay_extension(url)
    if extension is not None:
        arguments.append("--load-extension=" + str(extension))
    command.extend(arguments)
    _refuse_if_secret(command)
    try:
        launch_detached(_transient_user_command(command), env=graphical_env())
    except FileNotFoundError as error:
        raise ConfigurationError("chromium is unavailable") from error


def _refuse_if_secret(command: list[str]) -> None:
    joined = " ".join(command)
    if "X-Emby-Token" in joined or "api_key=" in joined.lower():
        raise ConfigurationError(
            "Refusing a webapp command that would expose credentials"
        )


def created_webapp_name() -> str | None:
    value = read_json_file(created_webapp_path(), 2048)
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        return None
    name = str(value.get("name") or "")
    if name != WEBAPP_NAME:
        return None
    return name


def mark_created_webapp(name: str) -> None:
    if name != WEBAPP_NAME:
        raise ConfigurationError("Invalid webapp name")
    atomic_json_write(
        created_webapp_path(),
        {"schemaVersion": SCHEMA_VERSION, "name": name},
        2048,
    )


def clear_created_webapp_marker() -> None:
    with contextlib.suppress(FileNotFoundError):
        unlink_private_file(created_webapp_path())


def find_jellyfin_webapp(config: dict[str, Any] | None = None) -> dict[str, str] | None:
    if config is None:
        config = load_config()
    if config is None:
        return None
    server = str(config["server"])
    root = applications_directory()
    if not root.is_dir():
        return None
    try:
        paths = list(root.rglob("*.desktop"))
    except OSError:
        return None
    for path in paths[:256]:
        if not path.is_file():
            continue
        payload = _desktop_payload(path)
        if not any(launcher in payload for launcher in _LAUNCHERS):
            continue
        name = path.stem
        for line in payload.splitlines()[:40]:
            if line.startswith("Name="):
                name = line.removeprefix("Name=").strip() or name
                break
        urls = _exec_urls(payload)
        for url in urls:
            if _origins_match(url, server):
                return {"name": name[:80], "url": url[:2048], "path": str(path)}
        if name.casefold() == WEBAPP_NAME.casefold() and urls:
            return {
                "name": name[:80],
                "url": urls[0][:2048],
                "path": str(path),
            }
    return None


def webapp_status() -> dict[str, Any]:
    found = find_jellyfin_webapp()
    created = created_webapp_name() is not None
    return {
        "installed": found is not None,
        "createdByOmajelly": created,
        "name": "" if found is None else found["name"],
    }


def install_jellyfin_webapp(*, launch: bool = False) -> dict[str, Any]:
    config = load_config()
    if config is None:
        raise ConfigurationError("Omajelly is not configured")
    url = _webapp_url(config)
    found = find_jellyfin_webapp(config)
    created = False
    if _needs_webapp_install(found):
        try:
            command = [resolve_tool(WEBAPP_INSTALLER), WEBAPP_NAME, url, WEBAPP_ICON]
        except ConfigurationError as error:
            raise ConfigurationError("omarchy-webapp-install is unavailable") from error
        _refuse_if_secret(command)
        try:
            return_code = run_no_output(command, timeout=20, env=graphical_env())
        except FileNotFoundError as error:
            raise ConfigurationError("omarchy-webapp-install is unavailable") from error
        if return_code != 0:
            raise ConfigurationError("Could not create the Jellyfin webapp")
        found = find_jellyfin_webapp(config)
        if found is None:
            raise ConfigurationError("Could not create the Jellyfin webapp")
        mark_created_webapp(WEBAPP_NAME)
        created = True
    if launch:
        launch_webapp(url)
    return {
        "installed": True,
        "name": WEBAPP_NAME if found is None else found["name"],
        "created": created,
        "createdByOmajelly": created_webapp_name() is not None,
        "launched": launch,
    }


def remove_created_jellyfin_webapp() -> bool:
    name = created_webapp_name()
    if name is None:
        return False
    environment = graphical_env()
    environment["OMARCHY_REMOVE_NOTIFY"] = "false"
    try:
        command = [resolve_tool(WEBAPP_REMOVER), name]
    except ConfigurationError:
        command = [WEBAPP_REMOVER, name]
    _refuse_if_secret(command)
    return_code = -1
    try:
        return_code = run_no_output(command, timeout=15, env=environment)
    except FileNotFoundError:
        return_code = -1
    desktop = applications_directory() / (name + ".desktop")
    gone = not desktop.is_file()
    if return_code != 0 and not gone:
        return False
    clear_created_webapp_marker()
    return True
