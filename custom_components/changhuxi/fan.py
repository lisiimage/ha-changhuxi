"""Purifier power, presets and six manual speeds."""

from homeassistant.components.fan import FanEntity, FanEntityFeature

from .const import MODES
from .entity import ChanghuxiEntity
from .model import speed_points


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(ChanghuxiFan(coordinator, d) for d in coordinator.devices)


class ChanghuxiFan(ChanghuxiEntity, FanEntity):
    _attr_name = None
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = list(MODES)
    _attr_speed_count = 6

    def __init__(self, coordinator, device):
        super().__init__(coordinator, device, "fan")

    @property
    def is_on(self):
        return self.value.get("power")

    @property
    def percentage(self):
        return self.value.get("percentage")

    @property
    def preset_mode(self):
        return self.value.get("preset_mode")

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        points = {31: 1}
        if preset_mode is not None:
            if preset_mode not in MODES:
                raise ValueError("Unsupported preset mode")
            points[32] = MODES[preset_mode]
        elif percentage is not None:
            points = speed_points(percentage)
        await self.coordinator.async_control(self.device_id, points)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_control(self.device_id, {31: 0})

    async def async_set_percentage(self, percentage):
        await self.coordinator.async_control(self.device_id, speed_points(percentage))

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode not in MODES:
            raise ValueError("Unsupported preset mode")
        await self.coordinator.async_control(self.device_id, {31: 1, 32: MODES[preset_mode]})
