from __future__ import annotations

import re
from typing import Any

from omajelly.common import ConfigurationError, ResponseError, clean_text
from omajelly.constants import ITEM_ID_PATTERN, MAX_TOKEN_BYTES

ITEM_ID_RE = re.compile(r"^" + ITEM_ID_PATTERN + r"$")
TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{8," + str(MAX_TOKEN_BYTES) + r"}")


def valid_item_id(value: Any, *, required: bool = True) -> str:
    item_id = str(value or "").strip()
    if not item_id:
        if required:
            raise ConfigurationError("A Jellyfin item id is required")
        return ""
    if not ITEM_ID_RE.fullmatch(item_id):
        raise ConfigurationError("The Jellyfin item id is invalid")
    return item_id


def optional_item_id(value: Any) -> str:
    try:
        return valid_item_id(value, required=False)
    except ConfigurationError:
        return ""


def valid_token(value: Any) -> str:
    token = str(value or "")
    if not TOKEN_RE.fullmatch(token):
        raise ConfigurationError("The Jellyfin token has an invalid format")
    return token


def valid_client_id(value: Any) -> str:
    client_id = clean_text(value, 128)
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", client_id):
        raise ConfigurationError("The saved Jellyfin client identifier is invalid")
    return client_id


def is_item_id(value: Any) -> bool:
    return bool(ITEM_ID_RE.fullmatch(str(value or "")))


def require_item_id(value: Any, message: str) -> str:
    item_id = str(value or "").strip()
    if not ITEM_ID_RE.fullmatch(item_id):
        raise ResponseError(message)
    return item_id
