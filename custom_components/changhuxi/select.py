"""Display brightness with automatic and off settings."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

from .const import BRIGHTNESS
from .entity import ChanghuxiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(ChanghuxiBrightness(c, d) for d in c.devices)


class ChanghuxiBrightness(ChanghuxiEntity, SelectEntity):
    _attr_translation_key = "brightness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(BRIGHTNESS)

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "brightness")

    @property
    def current_option(self):
        return next((k for k, v in BRIGHTNESS.items() if v == self.value.get("brightness")), None)

    async def async_select_option(self, option):
        await self.coordinator.async_control(self.device_id, {35: BRIGHTNESS[option]})
