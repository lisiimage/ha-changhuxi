"""Common device identity and availability."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class ChanghuxiEntity(CoordinatorEntity):
    """A stable entity belonging to an account's purifier."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device, key):
        super().__init__(coordinator)
        self.device_id = str(device["id"])
        self._attr_unique_id = f"{self.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.get("name") or "Changhuxi purifier",
            manufacturer="Smartisan / Changhuxi",
            model="A3xx",
            sw_version=str(device.get("firmware_version") or "unknown"),
        )

    @property
    def value(self):
        return (self.coordinator.data or {}).get(self.device_id, {})

    @property
    def available(self):
        return super().available and self.value.get("available", False)
