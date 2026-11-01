"""Config flow for the OpenWrt (ubus) integration."""

from typing import Any, override

from aioubus import UbusAuthenticationError, UbusError
import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_DHCP_SOFTWARE, DEFAULT_DHCP_SOFTWARE, DHCP_SOFTWARES, DOMAIN
from .coordinator import async_create_client

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
        await async_create_client(self.hass, data).login()

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
            except UbusError, ValueError:
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
        except UbusError, ValueError:
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(title=import_data[CONF_HOST], data=import_data)
