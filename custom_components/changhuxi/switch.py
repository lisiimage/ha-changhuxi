"""Purifier child lock."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .entity import ChanghuxiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(ChanghuxiChildLock(c, d) for d in c.devices)


class ChanghuxiChildLock(ChanghuxiEntity, SwitchEntity):
    _attr_translation_key = "child_lock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "child_lock")

    @property
    def is_on(self):
        return self.value.get("child_lock")

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_control(self.device_id, {33: 1})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_control(self.device_id, {33: 0})
