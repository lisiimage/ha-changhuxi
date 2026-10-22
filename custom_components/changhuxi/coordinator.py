"""Serialize account operations and keep devices independently available."""

import asyncio
import hashlib
import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import Client, CloudAuthenticationError
from .const import CONF_CREDENTIALS, CONF_RESOURCE, DOMAIN
from .model import decode

_LOGGER = logging.getLogger(__name__)


class ChanghuxiCoordinator(DataUpdateCoordinator[dict]):
    """Poll selected purifiers without blocking the HA event loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, devices: list[dict]):
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=timedelta(seconds=30)
        )
        self.entry = entry
        self.devices = devices
        self.lock = asyncio.Lock()

    def _config(self, device_id):
        credentials = self.entry.data[CONF_CREDENTIALS]
        user_id = str(credentials["user_id"])
        return {
            "host": "smartisan-cm.xlink.cn",
            "port": 1883,
            "user_id": user_id,
            "password": hashlib.md5((user_id + credentials["authorize"]).encode())
            .hexdigest()
            .upper(),
            "resource": self.entry.data[CONF_RESOURCE],
            "device_id": int(device_id),
        }

    def _read(self, device_id):
        with Client(self._config(device_id)) as client:
            return decode(client.get())

    async def _async_update_data(self):
        result = {}
        async with self.lock:
            for device in self.devices:
                device_id = str(device["id"])
                try:
                    value = await self.hass.async_add_executor_job(self._read, device_id)
                    result[device_id] = {**value, "available": True}
                except CloudAuthenticationError as err:
                    raise ConfigEntryAuthFailed(
                        "Cloud authentication failed; sign in again"
                    ) from err
                except (OSError, ValueError, ConnectionError) as err:
                    _LOGGER.debug("A purifier query failed: %s", type(err).__name__)
                    result[device_id] = {"available": False}
        if not any(v["available"] for v in result.values()):
            raise UpdateFailed("No selected purifier responded")
        return result

    def _write(self, device_id, points):
        with Client(self._config(device_id)) as client:
            client.set(points)
        # Acknowledgement alone does not confirm the hardware's applied state.
        for _ in range(3):
            time.sleep(0.8)
            with Client(self._config(device_id)) as client:
                actual = client.get()
            if all(actual.get(k) == v for k, v in points.items()):
                return {**decode(actual), "available": True}
        raise HomeAssistantError("The purifier did not confirm the requested state")

    async def async_control(self, device_id: str, points: dict[int, int]):
        """Send once, verify, and publish actual state immediately."""
        async with self.lock:
            try:
                value = await self.hass.async_add_executor_job(self._write, device_id, points)
            except CloudAuthenticationError as err:
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError("Sign in to Changhuxi again") from err
            except (OSError, ValueError, ConnectionError) as err:
                self.async_set_updated_data({**(self.data or {}), device_id: {"available": False}})
                raise HomeAssistantError(
                    "Command outcome is uncertain; check the purifier before retrying"
                ) from err
            self.async_set_updated_data({**(self.data or {}), device_id: value})
