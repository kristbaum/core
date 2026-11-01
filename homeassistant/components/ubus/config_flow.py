"""Config flow for the OpenWrt (ubus) integration."""

from typing import Any, override

from aioubus import UbusAuthenticationError, UbusClient, UbusError
import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_DHCP_SOFTWARE, DEFAULT_DHCP_SOFTWARE, DHCP_SOFTWARES, DOMAIN

STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(probatio.Secret(CONF_PASSWORD)): str,
        probatio.Required(
            CONF_DHCP_SOFTWARE, default=DEFAULT_DHCP_SOFTWARE
        ): SelectSelector(
            SelectSelectorConfig(
                options=DHCP_SOFTWARES,
                translation_key="dhcp_software",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


class UbusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenWrt (ubus)."""

    VERSION = 1

    async def _async_validate_connection(self, data: dict[str, Any]) -> None:
        """Validate that we can log in to the router with the given configuration."""
        client = UbusClient(
            data[CONF_HOST],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            session=async_get_clientsession(self.hass),
        )
        await client.login()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            try:
                await self._async_validate_connection(user_input)
            except UbusAuthenticationError:
                errors["base"] = "invalid_auth"
            except UbusError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_HOST], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import a configuration from configuration.yaml."""
        self._async_abort_entries_match({CONF_HOST: import_data[CONF_HOST]})

        try:
            await self._async_validate_connection(import_data)
        except UbusAuthenticationError:
            return self.async_abort(reason="invalid_auth")
        except UbusError:
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(title=import_data[CONF_HOST], data=import_data)
