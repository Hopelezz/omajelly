from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from enum import StrEnum
from typing import Any

from omajelly.common import (
    AuthenticationError,
    ConfigurationError,
    ResponseError,
    clean_text,
    finite_integer,
)
from omajelly.constants import (
    CLIENT_DEVICE,
    CLIENT_PRODUCT,
    CLIENT_VERSION,
    MAX_API_BYTES,
    MAX_SECTIONS,
    MAX_TOKEN_BYTES,
    REQUEST_TIMEOUT,
)
from omajelly.ids import valid_client_id, valid_item_id, valid_token


class HttpMethod(StrEnum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        raise ResponseError("Jellyfin tried to redirect an authenticated request")


def authorization_header(client_identifier: str, token: str = "") -> str:
    parts = [
        'Client="' + CLIENT_PRODUCT + '"',
        'Device="' + CLIENT_DEVICE + '"',
        'DeviceId="' + client_identifier + '"',
        'Version="' + CLIENT_VERSION + '"',
    ]
    if token:
        parts.append('Token="' + token + '"')
    return "MediaBrowser " + ", ".join(parts)


class JellyfinClient:
    def __init__(
        self,
        server: str,
        token: str,
        user_id: str,
        opener: Any | None = None,
        client_identifier: str = "omajelly",
    ) -> None:
        self.server = validate_origin(server)
        self.token = valid_token(token) if token else ""
        if token and len(token) > MAX_TOKEN_BYTES:
            raise ConfigurationError("The saved Jellyfin token is missing or invalid")
        self.user_id = valid_item_id(user_id) if user_id else ""
        self.client_identifier = valid_client_id(client_identifier)
        self.opener = opener or urllib.request.build_opener(RefuseRedirects())
        parsed = urllib.parse.urlsplit(self.server)
        self.base_path = parsed.path or ""
        self.origin = (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    def url(self, path: str) -> str:
        if not path.startswith("/") or path.startswith("//") or ".." in path:
            raise ResponseError("Refusing an invalid Jellyfin path")
        url = self.server + path
        if not url.startswith(self.server + "/"):
            raise ResponseError(
                "Refusing a Jellyfin request outside the configured origin"
            )
        parsed = urllib.parse.urlsplit(url)
        candidate = (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        if candidate != self.origin:
            raise ResponseError(
                "Refusing a Jellyfin request outside the configured origin"
            )
        if self.base_path and not parsed.path.startswith(self.base_path + "/"):
            raise ResponseError(
                "Refusing a Jellyfin request outside the configured origin"
            )
        return url

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": CLIENT_PRODUCT + "/" + CLIENT_VERSION,
            "Authorization": authorization_header(self.client_identifier, self.token),
        }
        if self.token:
            headers["X-Emby-Token"] = self.token
        if extra:
            headers.update(extra)
        return headers

    def open(
        self,
        path: str,
        *,
        method: HttpMethod = HttpMethod.GET,
        range_header: str = "",
        body: bytes | None = None,
        content_type: str = "",
    ) -> Any:
        if not isinstance(method, HttpMethod):
            raise ConfigurationError("Invalid Jellyfin HTTP method")
        extra: dict[str, str] = {}
        if range_header:
            extra["Range"] = range_header
        if content_type:
            extra["Content-Type"] = content_type
        request = urllib.request.Request(
            self.url(path),
            data=body,
            headers=self._headers(extra),
            method=method.value,
        )
        try:
            return self.opener.open(request, timeout=REQUEST_TIMEOUT)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                error.close()
                raise AuthenticationError(
                    "Jellyfin rejected the configured credentials"
                ) from error
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ResponseError("Jellyfin is unavailable") from error

    def request_json(
        self,
        path: str,
        *,
        method: HttpMethod = HttpMethod.GET,
        body: dict[str, Any] | None = None,
    ) -> Any:
        payload = None
        content_type = ""
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            content_type = "application/json"
        try:
            response = self.open(
                path, method=method, body=payload, content_type=content_type
            )
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise ResponseError("Jellyfin returned HTTP " + str(status)) from error
        try:
            length = finite_integer(response.headers.get("Content-Length"), -1)
            if length > MAX_API_BYTES:
                raise ResponseError("Jellyfin response exceeded the size limit")
            raw = response.read(MAX_API_BYTES + 1)
        finally:
            response.close()
        if len(raw) > MAX_API_BYTES:
            raise ResponseError("Jellyfin response exceeded the size limit")
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResponseError("Jellyfin returned malformed JSON") from error
        if not isinstance(value, (dict, list)):
            raise ResponseError("Jellyfin returned an invalid document")
        return value

    def request_empty(self, path: str, *, method: HttpMethod = HttpMethod.GET) -> None:
        try:
            response = self.open(path, method=method)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise ResponseError("Jellyfin returned HTTP " + str(status)) from error
        response.close()

    def fetch_server_name(self) -> str:
        info = self.request_json("/System/Info")
        if not isinstance(info, dict):
            raise ResponseError("Jellyfin returned an invalid server identity")
        return clean_text(info.get("ServerName"), 128)

    def fetch_user(self) -> dict[str, str]:
        document: Any
        if self.user_id:
            document = self.request_json("/Users/" + self.user_id)
        else:
            try:
                document = self.request_json("/Users/Me")
            except ResponseError:
                users = self.request_json("/Users")
                if isinstance(users, dict):
                    users = users.get("Items") or users.get("users") or []
                if not isinstance(users, list) or not users or not isinstance(
                    users[0], dict
                ):
                    raise ResponseError(
                        "Jellyfin returned no users for this API key"
                    )
                document = users[0]
        if not isinstance(document, dict):
            raise ResponseError("Jellyfin returned an invalid user")
        user_id = valid_item_id(document.get("Id"))
        name = clean_text(document.get("Name"), 128)
        return {"id": user_id, "name": name}

    def discover(self) -> tuple[list[dict[str, str]], str, str]:
        user = self.fetch_user()
        views = self.request_json("/Users/" + user["id"] + "/Views")
        items = views.get("Items", []) if isinstance(views, dict) else views
        if not isinstance(items, list) or len(items) > MAX_SECTIONS:
            raise ResponseError("Jellyfin returned an invalid library list")
        libraries: list[dict[str, str]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            collection = str(raw.get("CollectionType") or "").lower()
            if collection == "movies":
                kind = "movie"
            elif collection in {"tvshows", "tvshows".lower(), "tv"}:
                kind = "show"
            else:
                continue
            try:
                key = valid_item_id(raw.get("Id"))
            except ConfigurationError:
                continue
            libraries.append(
                {
                    "id": key,
                    "type": kind,
                    "title": clean_text(raw.get("Name"), 128)
                    or ("Movies" if kind == "movie" else "TV Shows"),
                }
            )
        return libraries, user["id"], self.fetch_server_name()


def authenticate(
    server: str,
    username: str,
    password: str,
    client_identifier: str,
    opener: Any | None = None,
) -> tuple[str, str, str]:
    client = JellyfinClient(
        server, "", "", opener=opener, client_identifier=client_identifier
    )
    document = client.request_json(
        "/Users/AuthenticateByName",
        method=HttpMethod.POST,
        body={"Username": username, "Pw": password},
    )
    if not isinstance(document, dict):
        raise ResponseError("Jellyfin returned an invalid sign-in response")
    token = valid_token(document.get("AccessToken"))
    user = document.get("User")
    if not isinstance(user, dict):
        raise ResponseError("Jellyfin returned an invalid user")
    user_id = valid_item_id(user.get("Id"))
    name = clean_text(user.get("Name"), 128)
    return token, user_id, name


def authenticate_with_quick_connect(
    server: str,
    secret: str,
    client_identifier: str,
    opener: Any | None = None,
) -> tuple[str, str, str]:
    client = JellyfinClient(
        server, "", "", opener=opener, client_identifier=client_identifier
    )
    document = client.request_json(
        "/Users/AuthenticateWithQuickConnect",
        method=HttpMethod.POST,
        body={"Secret": secret},
    )
    if not isinstance(document, dict):
        raise ResponseError("Jellyfin returned an invalid sign-in response")
    token = valid_token(document.get("AccessToken"))
    user = document.get("User")
    if not isinstance(user, dict):
        raise ResponseError("Jellyfin returned an invalid user")
    user_id = valid_item_id(user.get("Id"))
    name = clean_text(user.get("Name"), 128)
    return token, user_id, name


_BASE_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]{1,64}")


def validate_origin(value: Any) -> str:
    origin = clean_text(value, 512).rstrip("/")
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError("The Jellyfin server must be an HTTP or HTTPS origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError(
            "The Jellyfin server must not contain credentials, a query, or a fragment"
        )
    try:
        _ = parsed.port
    except ValueError as error:
        raise ConfigurationError("The Jellyfin server has an invalid port") from error
    path = parsed.path or ""
    if path:
        if not path.startswith("/") or "//" in path:
            raise ConfigurationError("The Jellyfin server path is invalid")
        segments = path.lstrip("/").split("/")
        if (
            not segments
            or len(segments) > 4
            or any(not _BASE_PATH_SEGMENT.fullmatch(part) for part in segments)
        ):
            raise ConfigurationError("The Jellyfin server path is invalid")
        if segments[-1].lower() == "web":
            raise ConfigurationError(
                "Use the Jellyfin base URL, not the /web client address"
            )
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, path, "", "")
    )
