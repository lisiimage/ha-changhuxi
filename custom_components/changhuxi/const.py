"""Constants for the unofficial Changhuxi integration."""

from homeassistant.const import Platform

DOMAIN = "changhuxi"
PLATFORMS = [Platform.FAN, Platform.SENSOR, Platform.SWITCH, Platform.SELECT]
PRODUCT_A3XX = "160fa6b1b95b03e9160fa6b1b95b2401"
MODES = {"auto": 0, "manual": 1, "turbo": 2, "sleep": 3}
BRIGHTNESS = {"auto": 0, "off": 249, **{f"level_{i}": i for i in range(1, 9)}}
CONF_DEVICES = "devices"
CONF_SELECTED = "selected_devices"
CONF_CREDENTIALS = "credentials"
CONF_RESOURCE = "resource"
