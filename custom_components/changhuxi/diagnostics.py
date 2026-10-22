"""Privacy-preserving diagnostics: never include account or hardware identity."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "selected_device_count": len(coordinator.devices),
        "last_update_success": coordinator.last_update_success,
        "devices": [
            {
                "model": "A3xx",
                "available": (coordinator.data or {}).get(str(d["id"]), {}).get("available", False),
            }
            for d in coordinator.devices
        ],
    }
