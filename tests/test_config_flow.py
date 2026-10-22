from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.changhuxi.auth import AuthenticationError
from custom_components.changhuxi.config_flow import ChanghuxiConfigFlow
from custom_components.changhuxi.const import PRODUCT_A3XX


@pytest.mark.asyncio
async def test_password_never_saved_and_nonpurifier_filtered(tmp_path):
    flow = ChanghuxiConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    flow.context = {"source": "user"}
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    login = {
        "user_id": 123,
        "authorize": "example",
        "access_token": "token",
        "refresh_token": "refresh",
        "devices": [
            {"id": 1, "product_id": PRODUCT_A3XX, "name": "Purifier"},
            {"id": 2, "product_id": "humidifier"},
        ],
    }
    with (
        patch("custom_components.changhuxi.config_flow.async_get_clientsession"),
        patch("custom_components.changhuxi.config_flow.async_login", AsyncMock(return_value=login)),
    ):
        form = await flow.async_step_user(
            {"username": "13800000000", "password": "private-example"}
        )
    assert form["step_id"] == "devices"
    assert flow._password is None
    result = await flow.async_step_devices({"selected_devices": ["1"]})
    assert result["type"] == "create_entry"
    assert len(result["data"]["devices"]) == 1
    assert "password" not in str(result["data"])
    assert "13800000000" not in str(result["data"])


@pytest.mark.asyncio
async def test_invalid_login_does_not_create_entry(tmp_path):
    flow = ChanghuxiConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    flow.context = {"source": "user"}
    with (
        patch("custom_components.changhuxi.config_flow.async_get_clientsession"),
        patch(
            "custom_components.changhuxi.config_flow.async_login",
            AsyncMock(side_effect=AuthenticationError()),
        ),
    ):
        result = await flow.async_step_user(
            {"username": "13800000000", "password": "private-example"}
        )
    assert result["errors"] == {"base": "invalid_auth"}
    assert flow._password is None
