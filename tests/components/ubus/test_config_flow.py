"""Tests for the OpenWrt (ubus) config flow."""

from unittest.mock import AsyncMock, MagicMock

from aioubus import (
    UbusAuthenticationError,
    UbusConnectionError,
    UbusError,
    UbusResponseError,
)
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.ubus.const import CONF_DHCP_SOFTWARE, DOMAIN
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MOCK_CONFIG, MOCK_HOST

USER_INPUT = {
    CONF_HOST: MOCK_HOST,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "password",
}


async def test_user_flow_success(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_ubus_client: MagicMock
) -> None:
    """Test the user flow creates an entry with the default DHCP software."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_HOST
    assert result["data"] == MOCK_CONFIG


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_ubus_client: MagicMock
) -> None:
    """Test the user flow recovers after a connection error."""
    mock_ubus_client.return_value.login.side_effect = UbusConnectionError("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_ubus_client.return_value.login.side_effect = None

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_host(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_ubus_client: MagicMock
) -> None:
    """Test the user flow reports a host that isn't a valid address."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={**USER_INPUT, CONF_HOST: "router.lan:abc"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    mock_ubus_client.assert_not_called()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_ubus_client: MagicMock
) -> None:
    """Test the user flow reports invalid credentials and then recovers."""
    mock_ubus_client.return_value.login.side_effect = UbusAuthenticationError(
        "login rejected"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    mock_ubus_client.return_value.login.side_effect = None

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the user flow aborts when the host is already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_import_flow(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_ubus_client: MagicMock
) -> None:
    """Test importing a YAML configuration."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=MOCK_CONFIG
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_HOST
    assert result["data"] == MOCK_CONFIG


async def test_import_flow_already_configured(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the import flow aborts when the host is already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=MOCK_CONFIG
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_import_flow_preserves_dhcp_software(
    hass: HomeAssistant, mock_setup_entry: AsyncMock, mock_ubus_client: MagicMock
) -> None:
    """Test a non-default DHCP software choice survives the import."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={**MOCK_CONFIG, CONF_DHCP_SOFTWARE: "odhcpd"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DHCP_SOFTWARE] == "odhcpd"


@pytest.mark.parametrize(
    ("side_effect", "reason"),
    [
        pytest.param(UbusConnectionError, "cannot_connect", id="cannot_connect"),
        pytest.param(UbusResponseError, "cannot_connect", id="unexpected_response"),
        pytest.param(UbusAuthenticationError, "invalid_auth", id="invalid_auth"),
    ],
)
async def test_import_flow_errors(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
    mock_ubus_client: MagicMock,
    side_effect: type[UbusError],
    reason: str,
) -> None:
    """Test the import flow aborts when the router can't be logged in to."""
    mock_ubus_client.return_value.login.side_effect = side_effect("boom")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=MOCK_CONFIG
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
