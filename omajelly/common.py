import contextlib
import datetime as dt
import json
import os
import re
import secrets
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from omajelly.constants import (
    MAX_FIELD,
)


class JellyfinError(Exception):
    pass


class ConfigurationError(JellyfinError):
    pass


class AuthenticationError(JellyfinError):
    pass


class ResponseError(JellyfinError):
    pass


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def clean_text(value: Any, maximum: int = MAX_FIELD) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:maximum]


def finite_integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def stop_process_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=0.5)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=0.5)


@contextlib.contextmanager
def wall_deadline(seconds: int, message: str):
    def expired(signum: int, frame: Any) -> None:
        raise ResponseError(message)

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def run_no_output(
    command: list[str], *, input_bytes: bytes | None = None, timeout: float = 10
) -> int:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        if input_bytes is not None and process.stdin is not None:
            process.stdin.write(input_bytes)
            process.stdin.close()
        return process.wait(timeout=timeout)
    except (BrokenPipeError, subprocess.TimeoutExpired):
        stop_process_group(process)
        return -1


def launch_detached(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def run_bounded_output(
    command: list[str], *, maximum: int, timeout: float
) -> tuple[int, bytes]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if process.stdout is None:
        stop_process_group(process)
        raise ConfigurationError("Could not read the desktop secret service")
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    selector = selectors.DefaultSelector()
    selector.register(descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    payload = bytearray()
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stop_process_group(process)
                raise ConfigurationError("The desktop secret service timed out")
            for key, _ in selector.select(min(0.2, remaining)):
                try:
                    chunk = os.read(key.fd, min(4096, maximum + 1 - len(payload)))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                payload.extend(chunk)
                if len(payload) > maximum:
                    stop_process_group(process)
                    raise ConfigurationError(
                        "The desktop secret service returned too much data"
                    )
        remaining = max(0.0, deadline - time.monotonic())
        try:
            return process.wait(timeout=remaining), bytes(payload)
        except subprocess.TimeoutExpired as error:
            stop_process_group(process)
            raise ConfigurationError("The desktop secret service timed out") from error
    finally:
        selector.close()
        process.stdout.close()


def _directory_open_flags() -> int:
    try:
        return os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    except AttributeError as error:
        raise ResponseError("Secure local state access is unavailable") from error


def _validate_directory(
    descriptor: int,
    name: str,
    *,
    system_owner: int,
    private: bool = False,
) -> None:
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise ResponseError(name + " is not a directory")
    owner = os.geteuid()
    mode = stat.S_IMODE(details.st_mode)
    if details.st_uid not in {system_owner, owner}:
        raise ResponseError(name + " has an unsafe owner")
    if private:
        if details.st_uid != owner or mode != 0o700:
            raise ResponseError(name + " is not a private directory")
        return
    writable_by_others = mode & 0o022
    sticky_directory = bool(mode & stat.S_ISVTX)
    if writable_by_others and not sticky_directory:
        raise ResponseError(name + " has unsafe permissions")


@contextlib.contextmanager
def secure_parent_directory(path: Path, *, create: bool, private: bool):
    absolute = Path(os.path.abspath(os.fspath(path)))
    filename = absolute.name
    if not filename or filename in {".", ".."}:
        raise ResponseError("The local state path is invalid")
    flags = _directory_open_flags()
    try:
        descriptor = os.open("/", flags)
    except OSError as error:
        raise ResponseError("The filesystem root could not be opened safely") from error
    try:
        system_owner = os.fstat(descriptor).st_uid
        _validate_directory(descriptor, "/", system_owner=system_owner)
        components = absolute.parent.parts[1:]
        for index, component in enumerate(components):
            final = index == len(components) - 1
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                except OSError as error:
                    raise ResponseError(
                        component + " could not be created safely"
                    ) from error
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as error:
                    raise ResponseError(
                        component + " could not be opened safely"
                    ) from error
            except OSError as error:
                raise ResponseError(
                    component + " could not be opened safely"
                ) from error
            try:
                _validate_directory(
                    child,
                    component,
                    system_owner=system_owner,
                    private=private and final,
                )
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        if private and not components:
            _validate_directory(
                descriptor, "/", system_owner=system_owner, private=True
            )
        yield descriptor, filename
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(descriptor, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("The local state write did not make progress")
        offset += written


def atomic_json_write(path: Path, value: dict[str, Any], maximum: int) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(payload) > maximum:
        raise ResponseError("Jellyfin data exceeded the local size limit")
    with secure_parent_directory(path, create=True, private=True) as (
        parent,
        filename,
    ):
        descriptor = -1
        temporary = ""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        for _ in range(16):
            temporary = "." + filename + "." + secrets.token_hex(16)
            try:
                descriptor = os.open(temporary, flags, 0o600, dir_fd=parent)
                break
            except FileExistsError:
                continue
            except OSError as error:
                raise ResponseError(
                    filename + " could not be created safely"
                ) from error
        if descriptor < 0:
            raise ResponseError(filename + " could not create a unique temporary file")
        try:
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            ):
                raise ResponseError(filename + " temporary file is unsafe")
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary,
                filename,
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            temporary = ""
            os.fsync(parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)


def read_regular_file(path: Path, maximum: int, *, private: bool = False) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK
    try:
        flags |= os.O_CLOEXEC | os.O_NOFOLLOW
    except AttributeError as error:
        raise ResponseError("Secure local state access is unavailable") from error
    with secure_parent_directory(path, create=False, private=private) as (
        parent,
        filename,
    ):
        try:
            descriptor = os.open(filename, flags, dir_fd=parent)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise ResponseError(filename + " could not be opened safely") from error
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise ResponseError(filename + " is not a regular file")
            mode = stat.S_IMODE(details.st_mode)
            if details.st_uid not in {0, os.geteuid()} or mode & 0o022:
                raise ResponseError(filename + " has unsafe ownership or permissions")
            if private and (details.st_uid != os.geteuid() or mode & 0o077):
                raise ResponseError(filename + " is not a private file")
            if details.st_size > maximum:
                raise ResponseError(filename + " exceeded its size limit")
            payload = os.read(descriptor, maximum + 1)
            if len(payload) > maximum:
                raise ResponseError(filename + " exceeded its size limit")
            return payload
        finally:
            os.close(descriptor)


def unlink_private_file(path: Path) -> None:
    with secure_parent_directory(path, create=False, private=True) as (
        parent,
        filename,
    ):
        try:
            os.unlink(filename, dir_fd=parent)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise ResponseError(filename + " could not be removed safely") from error
        os.fsync(parent)


def read_json_file(path: Path, maximum: int) -> Any:
    try:
        payload = read_regular_file(path, maximum, private=True)
    except FileNotFoundError:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResponseError(path.name + " is not valid JSON") from error
