"""Interactive Smartisan sign-in, device selection and reauthentication."""

from __future__ import annotations

import copy
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import (
    AuthenticationError,
    CannotConnect,
    CaptchaRequired,
    async_get_devices,
    async_login,
)
from .const import (
    CONF_CREDENTIALS,
    CONF_DEVICES,
    CONF_RESOURCE,
    CONF_SELECTED,
    DOMAIN,
    PRODUCT_A3XX,
)


def supported_devices(devices):
    """Only expose devices whose datapoint layout has been recovered."""
    fields = ("id", "product_id", "name", "mac", "firmware_version", "is_online")
    return [
        {k: d.get(k) for k in fields}
        for d in devices
        if d.get("product_id") == PRODUCT_A3XX and d.get("id") is not None
    ]


def device_selector(devices):
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=str(d["id"]), label=d.get("name") or "Changhuxi purifier"
                )
                for d in devices
            ],
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


class ChanghuxiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._login = None
        self._username = None
        self._password = None
        self._captcha_url = ""
        self._device_id = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ChanghuxiOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            return await self._async_login()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_login(self, captcha=None):
        errors = {}
        try:
            self._login = await async_login(
                async_get_clientsession(self.hass),
                self._username,
                self._password,
                captcha=captcha,
                device_id=self._device_id,
            )
        except CaptchaRequired as err:
            self._device_id = err.device_id
            parsed = urlsplit(err.captcha_url)
            self._captcha_url = (
                err.captcha_url
                if parsed.scheme == "https"
                and parsed.hostname in {"api-account.smartisan.com", "account.smartisan.com"}
                else ""
            )
            return await self.async_step_captcha()
        except AuthenticationError:
            errors["base"] = "invalid_auth"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        if errors:
            self._password = None
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_USERNAME, default=self._username): str,
                        vol.Required(CONF_PASSWORD): selector.TextSelector(
                            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                        ),
                    }
                ),
                errors=errors,
            )
        self._password = None
        user_id = str(self._login["user_id"])
        if self.context.get("source") == config_entries.SOURCE_REAUTH:
            if str(self._get_reauth_entry().data[CONF_CREDENTIALS]["user_id"]) != user_id:
                return self.async_abort(reason="wrong_account")
        await self.async_set_unique_id(user_id)
        if self.context.get("source") != config_entries.SOURCE_REAUTH:
            self._abort_if_unique_id_configured()
        devices = supported_devices(self._login.pop("devices", []))
        self._login[CONF_DEVICES] = devices
        if not devices:
            return self.async_abort(reason="no_devices")
        return await self.async_step_devices()

    async def async_step_captcha(self, user_input=None):
        if user_input is not None:
            return await self._async_login(user_input["captcha"])
        return self.async_show_form(
            step_id="captcha",
            data_schema=vol.Schema({vol.Required("captcha"): str}),
            description_placeholders={"captcha_url": self._captcha_url},
        )

    async def async_step_devices(self, user_input=None):
        devices = self._login[CONF_DEVICES]
        errors = {}
        if user_input is not None:
            selected = user_input[CONF_SELECTED]
            allowed = {str(d["id"]) for d in devices}
            if not selected or not set(selected) <= allowed:
                errors["base"] = "no_selection"
            else:
                credentials = {k: v for k, v in self._login.items() if k != CONF_DEVICES}
                data = {
                    CONF_CREDENTIALS: credentials,
                    CONF_DEVICES: devices,
                    CONF_SELECTED: selected,
                    CONF_RESOURCE: "",
                }
                if self.context.get("source") == config_entries.SOURCE_REAUTH:
                    entry = self._get_reauth_entry()
                    if entry.options.get(CONF_SELECTED):
                        self.hass.config_entries.async_update_entry(
                            entry, options={**entry.options, CONF_SELECTED: selected}
                        )
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                return self.async_create_entry(
                    title=f"Changhuxi ({self._username[-4:]})", data=data
                )
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELECTED, default=[str(d["id"]) for d in devices]
                    ): device_selector(devices),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_user()


class ChanghuxiOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        entry = self.config_entry
        devices = entry.data[CONF_DEVICES]
        if user_input is not None:
            selected = user_input[CONF_SELECTED]
            if not selected or not set(selected) <= {str(d["id"]) for d in devices}:
                errors["base"] = "no_selection"
            else:
                return self.async_create_entry(data={CONF_SELECTED: selected})
        else:
            credentials = copy.deepcopy(entry.data[CONF_CREDENTIALS])
            try:
                devices = supported_devices(
                    await async_get_devices(async_get_clientsession(self.hass), credentials)
                )
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_CREDENTIALS: credentials, CONF_DEVICES: devices}
                )
            except AuthenticationError:
                entry.async_start_reauth(self.hass)
                return self.async_abort(reason="reauth_required")
            except CannotConnect:
                errors["base"] = "cannot_connect"
        selected = entry.options.get(CONF_SELECTED, entry.data[CONF_SELECTED])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELECTED,
                        default=[x for x in selected if x in {str(d["id"]) for d in devices}],
                    ): device_selector(devices),
                }
            ),
            errors=errors,
        )
