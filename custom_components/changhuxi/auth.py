"""Smartisan OAuth and Xlink authentication used by the Android application.

The password is transmitted over verified HTTPS and is never retained. Public
application identifiers below are protocol constants, not user credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import aiohttp

SMARTISAN_ACCOUNT = "https://api-account.smartisan.com"
SMARTISAN_OAUTH = "https://api.smartisan.com"
XLINK_API = "https://smartisan-api.xlink.cn"
CORP_ID = "100fa2b1b91cca00"
CLIENT_ID = "10000006"
REDIRECT_URI = "smapp10000006://oauth"
SIGN = (
    hashlib.sha256(b"com.smartisan.smarthomecf74803c4c4ab15f5a5e801ee47ff82e").hexdigest().upper()
)
DEFAULT_USER_AGENT = "ChangHuXi Client/v1.3.3 (Android, Home Assistant, 12)"
TIMEOUT = aiohttp.ClientTimeout(total=25)


class AuthenticationError(Exception):
    """The account or session was rejected; Home Assistant should reauthenticate."""


class CannotConnect(Exception):
    """The service was unreachable or returned an unusable response."""


class CaptchaRequired(AuthenticationError):
    """A human must solve the account service's image challenge.

    Keep device_id and the session's cookies when retrying with captcha=answer.
    Never log captcha_url: the URL may contain a challenge token.
    """

    def __init__(self, captcha_url: str, device_id: str) -> None:
        super().__init__("Smartisan requires a captcha")
        self.captcha_url = captcha_url
        self.device_id = device_id


class _HttpAuthError(AuthenticationError):
    """Internal HTTP authentication status."""


async def _request(
    session: aiohttp.ClientSession, method: str, url: str, **kwargs: Any
) -> tuple[int, dict[str, str], Any]:
    """Read a bounded JSON response without exposing a body or credential URL."""
    try:
        async with session.request(
            method, url, timeout=TIMEOUT, allow_redirects=False, **kwargs
        ) as response:
            if response.status in (401, 403):
                raise _HttpAuthError("Authentication rejected by the service")
            if response.status == 429:
                raise CannotConnect("The service rate limited this request; retry later")
            if response.status >= 500:
                raise CannotConnect("The service is temporarily unavailable")
            headers = dict(response.headers)
            if response.status in (301, 302, 303, 307, 308):
                return response.status, headers, None
            raw = await response.content.read(2_000_001)
            if len(raw) > 2_000_000:
                raise CannotConnect("The service response exceeded the size limit")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError) as err:
                raise CannotConnect("The service returned an invalid JSON response") from err
            if response.status >= 400:
                # Error bodies can contain account identifiers; report only numeric code.
                code = data.get("errno", data.get("code")) if isinstance(data, dict) else None
                raise AuthenticationError(f"The service rejected this request (code {code})")
            return response.status, headers, data
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise CannotConnect("Could not connect to the authentication service") from err


def _required(data: Any, *keys: str) -> dict[str, Any]:
    if not isinstance(data, dict) or any(data.get(k) in (None, "") for k in keys):
        raise CannotConnect("The service returned an incomplete response")
    return data


def _normalize_device(device: dict[str, Any]) -> dict[str, Any]:
    def value(snake: str, camel: str, default: Any = None) -> Any:
        return device.get(snake, device.get(camel, default))

    online = value("is_online", "isOnline", device.get("online", False))
    if isinstance(online, str):
        online = online.lower() in ("true", "1")
    return {
        "id": device.get("id", device.get("device_id")),
        "product_id": value("product_id", "productId", ""),
        "mac": device.get("mac", ""),
        "name": device.get("name") or "Changhuxi purifier",
        "firmware_version": value("firmware_version", "firmwareVersion"),
        "access_key": value("access_key", "accessKey"),
        "is_online": bool(online),
        # LAN operation can reuse these without a new pairing operation.
        "pairing_id": value("pairing_id", "pairingId"),
        "pairing_key": value("pairing_key", "pairingKey"),
    }


async def async_refresh_credentials(
    session: aiohttp.ClientSession, credentials: dict[str, Any]
) -> None:
    """Refresh Xlink's REST token in place; retain the MQTT authorize value."""
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        raise AuthenticationError("The session expired; sign in again")
    _, _, body = await _request(
        session,
        "POST",
        f"{XLINK_API}/v2/user/token/refresh",
        json={"refresh_token": refresh_token},
    )
    body = _required(body, "access_token")
    credentials["access_token"] = body["access_token"]
    if body.get("refresh_token"):
        credentials["refresh_token"] = body["refresh_token"]
    if body.get("authorize"):
        credentials["authorize"] = body["authorize"]
    if body.get("expire_in") is not None:
        credentials["expires_at"] = time.time() + int(body["expire_in"])


async def async_get_devices(
    session: aiohttp.ClientSession, credentials: dict[str, Any]
) -> list[dict[str, Any]]:
    """Discover all subscriptions, refreshing once on an expired REST token.

    The supplied credential dictionary is updated after refresh; the caller must
    persist that update. A fresh version=0 requests the complete subscription list.
    """
    _required(credentials, "user_id", "access_token")
    if credentials.get("expires_at", 0) and credentials["expires_at"] <= time.time() + 30:
        await async_refresh_credentials(session, credentials)
    for attempt in range(2):
        try:
            _, _, body = await _request(
                session,
                "GET",
                f"{XLINK_API}/v2/user/{int(credentials['user_id'])}/subscribe/devices",
                headers={"Access-Token": credentials["access_token"]},
                params={"version": "0"},
            )
            break
        except _HttpAuthError:
            if attempt:
                raise AuthenticationError("The session expired; sign in again") from None
            await async_refresh_credentials(session, credentials)
    body = _required(body, "list")
    if not isinstance(body["list"], list):
        raise CannotConnect("The service returned an invalid device list")
    return [_normalize_device(d) for d in body["list"] if isinstance(d, dict)]


async def async_login(
    session: aiohttp.ClientSession, username: str, password: str, **kwargs: Any
) -> dict[str, Any]:
    """Sign in using the APK's V3 ticket → OAuth → Xlink flow.

    Optional captcha, device_id and user_agent kwargs support an interactive
    challenge retry. Passwords are used exactly as entered, without a local hash.
    No credentials or response bodies are logged.
    """
    username = username.strip()
    if username.startswith("+86"):
        username = username[3:]
    if not username or not password:
        raise AuthenticationError("Username and password are required")
    # Android's fallback is a persistent 15-digit identifier. No actual IMEI is needed.
    device_id = str(kwargs.get("device_id") or (10**14 + secrets.randbelow(9 * 10**14)))
    headers = {
        "App-Id": "6",
        "Features": "1",
        "S-Ver": "20150813.07",
        "User-Agent": str(kwargs.get("user_agent") or DEFAULT_USER_AGENT),
        "Device-Id": device_id,
    }
    payload = {"cellphone": username, "password": password}
    if kwargs.get("captcha"):
        payload["captcha"] = str(kwargs["captcha"])
    _, _, ticket = await _request(
        session, "POST", f"{SMARTISAN_ACCOUNT}/v2/oauth/ticket", headers=headers, json=payload
    )
    ticket = _required(ticket, "errno")
    if int(ticket["errno"]) == 1502:
        data = ticket.get("data") or {}
        raise CaptchaRequired(str(data.get("captcha", "")), device_id)
    if int(ticket["errno"]) != 0:
        raise AuthenticationError(f"Smartisan sign-in failed (code {ticket['errno']})")
    data = _required(ticket.get("data"), "ticket", "secret")
    status, auth_headers, _ = await _request(
        session,
        "GET",
        f"{SMARTISAN_OAUTH}/oauth/authorize",
        headers={"Ticket": data["ticket"], "Secret": data["secret"]},
        params={
            "client_id": CLIENT_ID,
            "response_type": "token",
            "state": "xxxxdfsfsdfsdfsdfsdfsdf",
            "redirect_uri": REDIRECT_URI,
            "sign": SIGN,
            "auto_approve": "1",
        },
    )
    location = next((v for k, v in auth_headers.items() if k.lower() == "location"), "")
    if status != 302 or not location.startswith(REDIRECT_URI):
        raise AuthenticationError("Smartisan did not grant OAuth access")
    fragment = {k: v[0] for k, v in parse_qs(urlsplit(location).fragment).items()}
    _required(fragment, "openid", "access_token")
    _, _, xlink = await _request(
        session,
        "POST",
        f"{XLINK_API}/v2/user_auth_third",
        json={
            "corp_id": CORP_ID,
            "open_id": fragment["openid"],
            "access_token": fragment["access_token"],
            "name": "ChangHuXi",
            "source": 10,
            "resource": str(kwargs.get("resource") or ""),
        },
    )
    xlink = _required(xlink, "user_id", "authorize", "access_token", "refresh_token")
    result = {k: xlink[k] for k in ("user_id", "authorize", "access_token", "refresh_token")}
    result["device_id"] = device_id
    if xlink.get("expire_in") is not None:
        result["expires_at"] = time.time() + int(xlink["expire_in"])
    result["devices"] = await async_get_devices(session, result)
    return result
