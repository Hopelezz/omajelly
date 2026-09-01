from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omajelly.browse import BrowseKind, SearchScope, browse_document
from omajelly.commands import command_refresh, command_scan, print_json
from omajelly.common import (
    ConfigurationError,
    JellyfinError,
    clean_text,
    launch_detached,
    wall_deadline,
)
from omajelly.config import load_config
from omajelly.connection import (
    clear_configuration,
    client_from_saved,
    configure_connection,
    configure_from_env,
    read_setup,
    status_document,
    with_connection,
)
from omajelly.quickconnect import (
    cancel_quick_connect,
    poll_quick_connect,
    start_quick_connect,
)
from omajelly.playback import (
    PlaybackMode,
    WatchState,
    jellyfin_web_url,
    play,
    set_watch_state,
)
from omajelly.subtitles import download_subtitle, search_subtitles
from omajelly.windowing import bring_player_to_active_workspace, windowed_player_active


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="omajelly")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("refresh")
    commands.add_parser("scan")
    commands.add_parser("bring-player")
    commands.add_parser("player-window-status")
    commands.add_parser("configure")
    commands.add_parser("clear-configuration")
    quick_start = commands.add_parser("quick-connect-start")
    quick_start.add_argument("--server", required=True)
    commands.add_parser("quick-connect-poll")
    commands.add_parser("quick-connect-cancel")
    browse = commands.add_parser("browse")
    browse.add_argument(
        "--kind", type=BrowseKind, choices=tuple(BrowseKind), required=True
    )
    browse.add_argument("--query", default="")
    browse.add_argument("--offset", type=int, default=0)
    browse.add_argument("--limit", type=int, default=40)
    browse.add_argument("--parent-rating-key", default="")
    browse.add_argument(
        "--search-scope",
        type=SearchScope,
        choices=tuple(SearchScope),
        default=SearchScope.MOVIES,
    )
    configure = commands.add_parser("configure-from-env")
    configure.add_argument("env_file")
    play_command = commands.add_parser("play")
    play_command.add_argument("--rating-key", required=True)
    play_command.add_argument(
        "--mode",
        type=PlaybackMode,
        choices=tuple(PlaybackMode),
        default=PlaybackMode.WINDOWED,
    )
    play_command.add_argument("--auto-play-next", action="store_true")
    play_command.add_argument("--subtitle-language", default="en")
    subtitle_search = commands.add_parser("subtitle-search")
    subtitle_search.add_argument("--rating-key", required=True)
    subtitle_search.add_argument("--language", required=True)
    subtitle_download = commands.add_parser("subtitle-download")
    subtitle_download.add_argument("--rating-key", required=True)
    subtitle_download.add_argument("--subtitle-key", required=True)
    subtitle_download.add_argument("--format", required=True)
    subtitle_download.add_argument("--output-directory", required=True)
    mark_command = commands.add_parser("mark")
    mark_command.add_argument("--rating-key", required=True)
    mark_command.add_argument(
        "--state", type=WatchState, choices=tuple(WatchState), required=True
    )
    web = commands.add_parser("open-web")
    web.add_argument("--rating-key", default="")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "status":
            print_json(status_document())
            return 0
        if args.command == "refresh":
            return command_refresh()
        if args.command == "scan":
            return command_scan()
        if args.command == "bring-player":
            bring_player_to_active_workspace()
            return 0
        if args.command == "player-window-status":
            print_json({"active": windowed_player_active()})
            return 0
        if args.command == "configure":
            setup = read_setup()
            with wall_deadline(30, "Jellyfin setup exceeded thirty seconds"):
                print_json(configure_connection(setup))
            return 0
        if args.command == "quick-connect-start":
            with wall_deadline(20, "Quick Connect could not be started"):
                print_json(start_quick_connect(args.server))
            return 0
        if args.command == "quick-connect-poll":
            with wall_deadline(20, "Quick Connect check timed out"):
                print_json(poll_quick_connect())
            return 0
        if args.command == "quick-connect-cancel":
            print_json(cancel_quick_connect())
            return 0
        if args.command == "clear-configuration":
            print_json(clear_configuration())
            return 0
        if args.command == "browse":
            with wall_deadline(20, "Jellyfin browse exceeded twenty seconds"):
                client, config = client_from_saved()
                print_json(
                    browse_document(
                        client,
                        config,
                        args.kind,
                        args.query,
                        args.offset,
                        args.limit,
                        args.parent_rating_key,
                        args.search_scope,
                    )
                )
            return 0
        if args.command == "configure-from-env":
            with wall_deadline(25, "Jellyfin setup exceeded twenty-five seconds"):
                print_json(configure_from_env(Path(args.env_file)))
            return 0
        if args.command == "play":
            return play(
                args.rating_key,
                args.mode,
                args.auto_play_next,
                args.subtitle_language,
            )
        if args.command == "subtitle-search":
            with wall_deadline(20, "Jellyfin subtitle search exceeded twenty seconds"):
                client, _ = client_from_saved()
                print_json(search_subtitles(client, args.rating_key, args.language))
            return 0
        if args.command == "subtitle-download":
            with wall_deadline(20, "Jellyfin subtitle download exceeded twenty seconds"):
                client, _ = client_from_saved()
                print_json(
                    download_subtitle(
                        client,
                        args.rating_key,
                        args.subtitle_key,
                        args.format,
                        args.output_directory,
                    )
                )
            return 0
        if args.command == "mark":
            with wall_deadline(10, "Jellyfin watch-state update exceeded ten seconds"):
                client, _ = client_from_saved()
                set_watch_state(client, args.rating_key, args.state)
            return 0
        if args.command == "open-web":
            config = load_config()
            if config is None:
                raise ConfigurationError("Omajelly is not configured")
            url = jellyfin_web_url(config, args.rating_key)
            try:
                launch_detached(["xdg-open", url])
            except FileNotFoundError as error:
                raise ConfigurationError("xdg-open is unavailable") from error
            return 0
        raise ConfigurationError("Unknown command")
    except JellyfinError as error:
        print(clean_text(error, 220), file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - CLI boundary hides internal tracebacks
        print("The Jellyfin helper failed unexpectedly", file=sys.stderr)
        return 2
