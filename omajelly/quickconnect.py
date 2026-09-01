from __future__ import annotations

import contextlib
import re
import time
import urllib.parse
from typing import Any

from omajelly.client import (
    HttpMethod,
    JellyfinClient,
    authenticate_with_quick_connect,
    validate_origin,
)
from omajelly.common import (
    AuthenticationError,
    ConfigurationError,
    JellyfinError,
    ResponseError,
    atomic_json_write,
    clean_text,
    read_json_file,
    unlink_private_file,
)
from omajelly.config import (
    AUTH_MODE_QUICKCONNECT,
    PendingQuickConnectStore,
    config_home,
    load_config,
    new_client_identifier,
)
from omajelly.constants import (
    MAX_PENDING_BYTES,
    PENDING_QUICK_CONNECT_SECONDS,
    SCHEMA_VERSION,
)


def valid_quick_connect_secret(value: Any) -> str:
    secret = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,256}", secret):
        raise ResponseError("Jellyfin returned an invalid Quick Connect secret")
    return secret


def pending_path():
    return config_home() / "quick-connect.json"


def validate_pending(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
        raise ConfigurationError("No Quick Connect sign-in is pending")
    if "secret" in value or "token" in value or "password" in value:
        raise ConfigurationError("The pending Quick Connect state is invalid")
    from omajelly.ids import valid_client_id

    server = validate_origin(value.get("server"))
    code = clean_text(value.get("code"), 16).replace(" ", "")
    client_identifier = valid_client_id(value.get("clientIdentifier"))
    created_at = int(value.get("createdAt") or 0)
    if not code.isdigit() or len(code) < 4 or len(code) > 8:
        raise ConfigurationError("The pending Quick Connect code is invalid")
    if abs(int(time.time()) - created_at) > PENDING_QUICK_CONNECT_SECONDS:
        raise ConfigurationError("Quick Connect expired; start a new sign-in")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "server": server,
        "code": code,
        "clientIdentifier": client_identifier,
        "createdAt": created_at,
    }


def load_pending() -> dict[str, str] | None:
    value = read_json_file(pending_path(), MAX_PENDING_BYTES)
    if value is None:
        return None
    return validate_pending(value)


def save_pending(value: dict[str, Any]) -> None:
    atomic_json_write(pending_path(), validate_pending(value), MAX_PENDING_BYTES)


def clear_pending(store: PendingQuickConnectStore | None = None) -> None:
    (store or PendingQuickConnectStore()).clear()
    with contextlib.suppress(FileNotFoundError, JellyfinError, OSError):
        unlink_private_file(pending_path())


def _initiate(client: JellyfinClient) -> dict[str, Any]:
    try:
        document = client.request_json(
            "/QuickConnect/Initiate", method=HttpMethod.POST, body={}
        )
    except AuthenticationError as error:
        raise ConfigurationError(
            "Quick Connect is disabled on this Jellyfin server"
        ) from error
    except ResponseError as error:
        detail = str(error)
        if "HTTP 405" in detail or "HTTP 404" in detail:
            try:
                document = client.request_json("/QuickConnect/Initiate")
            except AuthenticationError as inner:
                raise ConfigurationError(
                    "Quick Connect is disabled on this Jellyfin server"
                ) from inner
        elif "HTTP 401" in detail:
            raise ConfigurationError(
                "Quick Connect is disabled on this Jellyfin server"
            ) from error
        else:
            raise
    if not isinstance(document, dict):
        raise ResponseError("Jellyfin returned an invalid Quick Connect request")
    return document


def start_quick_connect(
    server: str,
    store: PendingQuickConnectStore | None = None,
) -> dict[str, Any]:
    origin = validate_origin(server)
    pending_store = store or PendingQuickConnectStore()
    clear_pending(pending_store)
    old_config = load_config()
    client_identifier = (
        old_config["clientIdentifier"] if old_config else new_client_identifier()
    )
    client = JellyfinClient(origin, "", "", client_identifier=client_identifier)
    document = _initiate(client)
    secret = valid_quick_connect_secret(document.get("Secret"))
    code = clean_text(document.get("Code"), 16).replace(" ", "")
    if not code.isdigit() or len(code) < 4 or len(code) > 8:
        raise ResponseError("Jellyfin returned an invalid Quick Connect code")
    pending_store.store(secret)
    try:
        save_pending(
            {
                "schemaVersion": SCHEMA_VERSION,
                "server": origin,
                "code": code,
                "clientIdentifier": client_identifier,
                "createdAt": int(time.time()),
            }
        )
    except Exception:
        clear_pending(pending_store)
        raise
    return {
        "state": "pending",
        "code": code,
    }


def poll_quick_connect(
    store: PendingQuickConnectStore | None = None,
    token_store: Any | None = None,
) -> dict[str, Any]:
    pending = load_pending()
    if pending is None:
        raise ConfigurationError("No Quick Connect sign-in is pending")
    pending_store = store or PendingQuickConnectStore()
    secret = pending_store.lookup()
    if not secret:
        clear_pending(pending_store)
        raise ConfigurationError("The pending Quick Connect secret is missing")
    client = JellyfinClient(
        pending["server"], "", "", client_identifier=pending["clientIdentifier"]
    )
    try:
        document = client.request_json(
            "/QuickConnect/Connect?" + urllib.parse.urlencode({"Secret": secret})
        )
    except AuthenticationError as error:
        raise ConfigurationError(
            "Quick Connect is disabled on this Jellyfin server"
        ) from error
    except ResponseError as error:
        if "HTTP 404" in str(error):
            clear_pending(pending_store)
            raise ConfigurationError(
                "Quick Connect expired; start a new sign-in"
            ) from error
        raise
    if not isinstance(document, dict):
        raise ResponseError("Jellyfin returned an invalid Quick Connect state")
    if document.get("Authenticated") is not True:
        return {"state": "pending", "code": pending["code"]}
    token, user_id, user_name = authenticate_with_quick_connect(
        pending["server"], secret, pending["clientIdentifier"]
    )
    from omajelly.connection import persist_authenticated_session

    result = persist_authenticated_session(
        pending["server"],
        token,
        user_id,
        user_name,
        AUTH_MODE_QUICKCONNECT,
        pending["clientIdentifier"],
        token_store,
    )
    clear_pending(pending_store)
    return result


def cancel_quick_connect(store: PendingQuickConnectStore | None = None) -> dict[str, str]:
    clear_pending(store)
    return {"state": "cancelled"}
