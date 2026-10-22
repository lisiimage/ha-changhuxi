"""Offline authentication protocol tests; never contact a real login service."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def auth():
    """Load the API without importing the Home Assistant integration package."""
    path = Path(__file__).parents[1] / "custom_components/changhuxi/auth.py"
    spec = importlib.util.spec_from_file_location("changhuxi_auth_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_login_chain_and_normalization(auth, monkeypatch):
    request = AsyncMock(
        side_effect=[
            (200, {}, {"errno": 0, "data": {"ticket": "ticket", "secret": "secret"}}),
            (
                302,
                {"Location": "smapp10000006://oauth#openid=openid&access_token=oauth-token"},
                None,
            ),
            (
                200,
                {},
                {
                    "user_id": 123,
                    "authorize": "mqtt-auth",
                    "access_token": "rest-token",
                    "refresh_token": "refresh-token",
                    "expire_in": 7200,
                },
            ),
            (
                200,
                {},
                {
                    "list": [
                        {
                            "id": 1,
                            "product_id": "product",
                            "mac": "aabbccddeeff",
                            "access_key": 123,
                            "is_online": True,
                            "name": "Test",
                            "firmware_version": "1.0",
                            "pairing_id": "2",
                            "pairing_key": "abc",
                        }
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr(auth, "_request", request)
    result = await auth.async_login(
        None, "+8613800000000", "original password", device_id="100000000000001"
    )
    calls = request.call_args_list
    assert calls[0].args[2] == "https://api-account.smartisan.com/v2/oauth/ticket"
    assert calls[0].kwargs["json"] == {"cellphone": "13800000000", "password": "original password"}
    assert calls[0].kwargs["headers"]["Device-Id"] == "100000000000001"
    assert calls[0].kwargs["headers"]["App-Id"] == "6"
    assert calls[1].kwargs["params"]["sign"] == auth.SIGN
    assert auth.SIGN == auth.SIGN.upper()
    assert calls[1].kwargs["headers"] == {"Ticket": "ticket", "Secret": "secret"}
    assert calls[2].kwargs["json"]["source"] == 10
    assert calls[2].kwargs["json"]["resource"] == ""
    assert calls[2].kwargs["json"]["access_token"] == "oauth-token"
    assert calls[3].kwargs["headers"] == {"Access-Token": "rest-token"}
    assert calls[3].kwargs["params"] == {"version": "0"}
    assert result["authorize"] == "mqtt-auth"
    assert result["devices"][0] == {
        "id": 1,
        "product_id": "product",
        "mac": "aabbccddeeff",
        "name": "Test",
        "firmware_version": "1.0",
        "access_key": 123,
        "is_online": True,
        "pairing_id": "2",
        "pairing_key": "abc",
    }
    assert "password" not in result


@pytest.mark.asyncio
async def test_captcha_preserves_device_id(auth, monkeypatch):
    request = AsyncMock(
        return_value=(
            200,
            {},
            {"errno": 1502, "data": {"captcha": "https://api-account.smartisan.com/challenge"}},
        )
    )
    monkeypatch.setattr(auth, "_request", request)
    with pytest.raises(auth.CaptchaRequired) as caught:
        await auth.async_login(
            None, "13800000000", "password", device_id="same-device", captcha="answer"
        )
    assert caught.value.device_id == "same-device"
    assert caught.value.captcha_url.endswith("/challenge")
    assert request.call_args.kwargs["json"]["captcha"] == "answer"
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_login_error_stops_before_oauth(auth, monkeypatch):
    request = AsyncMock(return_value=(200, {}, {"errno": 1501}))
    monkeypatch.setattr(auth, "_request", request)
    with pytest.raises(auth.AuthenticationError):
        await auth.async_login(None, "13800000000", "password")
    assert request.await_count == 1


@pytest.mark.asyncio
async def test_refreshes_once_and_retains_mqtt_auth(auth, monkeypatch):
    request = AsyncMock(
        side_effect=[
            auth._HttpAuthError("expired"),
            (200, {}, {"access_token": "new", "refresh_token": "new-refresh", "expire_in": 7200}),
            (200, {}, {"list": []}),
        ]
    )
    monkeypatch.setattr(auth, "_request", request)
    credentials = {
        "user_id": 123,
        "access_token": "old",
        "refresh_token": "refresh",
        "authorize": "mqtt-auth",
    }
    assert await auth.async_get_devices(None, credentials) == []
    assert credentials["access_token"] == "new"
    assert credentials["refresh_token"] == "new-refresh"
    assert credentials["authorize"] == "mqtt-auth"
    assert request.await_count == 3


@pytest.mark.asyncio
async def test_rejected_refresh_requires_reauth(auth, monkeypatch):
    request = AsyncMock(
        side_effect=[auth._HttpAuthError("expired"), auth._HttpAuthError("refresh expired")]
    )
    monkeypatch.setattr(auth, "_request", request)
    with pytest.raises(auth.AuthenticationError):
        await auth.async_get_devices(
            None, {"user_id": 1, "access_token": "expired", "refresh_token": "expired"}
        )
    assert request.await_count == 2


@pytest.mark.asyncio
async def test_malformed_success_is_connection_error(auth, monkeypatch):
    monkeypatch.setattr(
        auth, "_request", AsyncMock(return_value=(200, {}, {"errno": 0, "data": {}}))
    )
    with pytest.raises(auth.CannotConnect):
        await auth.async_login(None, "13800000000", "password")
