from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.changhuxi.coordinator import ChanghuxiCoordinator


@pytest.mark.asyncio
async def test_one_offline_device_does_not_hide_online_devices(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        async_on_unload=Mock(),
        data={"credentials": {"user_id": 123, "authorize": "placeholder"}, "resource": ""},
    )
    c = ChanghuxiCoordinator(hass, entry, [{"id": 1}, {"id": 2}])
    hass.async_add_executor_job = AsyncMock(side_effect=[{"power": False}, TimeoutError()])
    result = await c._async_update_data()
    assert result["1"]["available"] is True
    assert result["2"]["available"] is False


@pytest.mark.asyncio
async def test_control_publishes_readback_without_waiting_for_poll(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test",
        async_on_unload=Mock(),
        data={"credentials": {"user_id": 123, "authorize": "placeholder"}, "resource": ""},
    )
    c = ChanghuxiCoordinator(hass, entry, [{"id": 1}])
    hass.async_add_executor_job = AsyncMock(return_value={"power": True, "available": True})
    await c.async_control("1", {31: 1})
    assert c.data["1"]["power"] is True
