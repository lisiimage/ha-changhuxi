"""The unofficial Changhuxi purifier integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICES, CONF_SELECTED, PLATFORMS
from .coordinator import ChanghuxiCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    selected = entry.options.get(CONF_SELECTED, entry.data.get(CONF_SELECTED, []))
    devices = [d for d in entry.data[CONF_DEVICES] if str(d["id"]) in selected]
    coordinator = ChanghuxiCoordinator(hass, entry, devices)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)
