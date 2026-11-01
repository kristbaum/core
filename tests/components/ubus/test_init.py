"""Tests for the OpenWrt (ubus) integration setup."""

from typing import Any
from unittest.mock import MagicMock

from aioubus import (
    HostapdClients,
    UbusAuthenticationError,
    UbusConnectionError,
    UbusPermissionError,
)
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.ubus.coordinator import UPDATE_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import MAC_GUEST, MAC_LAPTOP, MAC_PHONE


@pytest.mark.parametrize(
    ("method", "behavior"),
    [
        pytest.param(
            "list_hostapd_interfaces",
            {"side_effect": UbusConnectionError("boom")},
            id="unreachable",
        ),
        pytest.param("list_hostapd_interfaces", {"return_value": ()}, id="no_hostapd"),
        pytest.param(
            "get_hostapd_clients",
            {"side_effect": UbusAuthenticationError("login rejected")},
            id="invalid_auth",
        ),
        pytest.param(
            "get_hostapd_clients",
            {"side_effect": UbusPermissionError("access denied")},
            id="access_denied",
        ),
        pytest.param(
            "get_dnsmasq_leases",
            {"side_effect": UbusPermissionError("access denied")},
            id="leases_denied",
        ),
    ],
)
async def test_setup_retry(
    hass: HomeAssistant,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    method: str,
    behavior: dict[str, Any],
) -> None:
    """Test the config entry retries setup when the router can't be read."""
    getattr(mock_ubus_client.return_value, method).configure_mock(**behavior)

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_clients_merged_across_interfaces(
    hass: HomeAssistant,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a client authorized on any interface is tracked."""
    client = mock_ubus_client.return_value
    client.list_hostapd_interfaces.return_value = ("phy0-ap0", "phy1-ap0")
    client.get_hostapd_clients.side_effect = [
        HostapdClients.from_json(
            "phy0-ap0",
            {
                "clients": {
                    MAC_PHONE: {"authorized": True},
                    MAC_GUEST: {"authorized": True},
                }
            },
        ),
        HostapdClients.from_json(
            "phy1-ap0",
            {
                "clients": {
                    MAC_LAPTOP: {"authorized": True},
                    MAC_GUEST: {"authorized": False},
                }
            },
        ),
    ]

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    assert {e.unique_id for e in entries} == {MAC_PHONE, MAC_LAPTOP, MAC_GUEST}


async def test_router_metadata_is_cached(
    hass: HomeAssistant,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test interfaces and hostnames are read once, clients on every update."""
    client = mock_ubus_client.return_value
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert client.list_hostapd_interfaces.call_count == 1
    assert client.get_dnsmasq_leases.call_count == 1
    assert client.get_hostapd_clients.call_count == 2


async def test_unload_entry(
    hass: HomeAssistant,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the config entry unloads cleanly."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
