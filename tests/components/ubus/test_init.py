"""Tests for the OpenWrt (ubus) integration setup."""

from typing import Any
from unittest.mock import MagicMock

from aioubus import (
    HostapdClients,
    UbusAuthenticationError,
    UbusConnectionError,
    UbusError,
    UbusNotFoundError,
    UbusPermissionError,
)
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.ubus.const import DOMAIN
from homeassistant.components.ubus.coordinator import UPDATE_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import MAC_GUEST, MAC_LAPTOP, MAC_PHONE, MOCK_CONFIG


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


@pytest.mark.parametrize(
    ("host", "expected_host", "expected_port"),
    [
        pytest.param("192.168.1.1", "192.168.1.1", None, id="ipv4"),
        pytest.param("router.lan", "router.lan", None, id="hostname"),
        pytest.param("192.168.1.1:8080", "192.168.1.1", 8080, id="ipv4_port"),
        pytest.param("fd00::1", "fd00::1", None, id="ipv6"),
        pytest.param("[fd00::1]", "fd00::1", None, id="ipv6_brackets"),
        pytest.param("[fd00::1]:8080", "fd00::1", 8080, id="ipv6_port"),
    ],
)
async def test_host_formats(
    hass: HomeAssistant,
    mock_ubus_client: MagicMock,
    host: str,
    expected_host: str,
    expected_port: int | None,
) -> None:
    """Test stored hosts with a port or bracketed IPv6 address still connect."""
    entry = MockConfigEntry(domain=DOMAIN, data={**MOCK_CONFIG, CONF_HOST: host})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert mock_ubus_client.call_args.args[0] == expected_host
    assert mock_ubus_client.call_args.kwargs["port"] == expected_port


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(UbusNotFoundError("no lease file"), id="no_lease_file"),
        pytest.param(UbusPermissionError("access denied"), id="access_denied"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_leases_unavailable(
    hass: HomeAssistant,
    mock_ubus_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
    error: UbusError,
) -> None:
    """Test clients are tracked without hostnames until the leases can be read."""
    client = mock_ubus_client.return_value
    leases = client.get_dnsmasq_leases.return_value
    client.get_dnsmasq_leases.side_effect = error

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = entity_registry.async_get_entity_id("device_tracker", DOMAIN, MAC_PHONE)
    assert entity_id
    state = hass.states.get(entity_id)
    assert state
    assert state.state == "home"
    assert "host_name" not in state.attributes

    client.get_dnsmasq_leases.side_effect = None
    client.get_dnsmasq_leases.return_value = leases
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state
    assert state.attributes["host_name"] == "my-phone"


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
