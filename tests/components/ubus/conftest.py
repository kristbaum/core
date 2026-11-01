"""Fixtures for the OpenWrt (ubus) integration tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from aioubus import HostapdClients, parse_dnsmasq_leases
from aioubus.models import parse_odhcpd_leases
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    load_fixture,
    load_json_object_fixture,
)

from homeassistant.components.ubus.const import (
    CONF_DHCP_SOFTWARE,
    DEFAULT_DHCP_SOFTWARE,
    DOMAIN,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

MOCK_HOST = "192.168.1.1"

MOCK_CONFIG = {
    CONF_HOST: MOCK_HOST,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "password",
    CONF_DHCP_SOFTWARE: DEFAULT_DHCP_SOFTWARE,
}

MAC_PHONE = "aa:bb:cc:dd:ee:ff"
MAC_LAPTOP = "11:22:33:44:55:66"
MAC_GUEST = "99:88:77:66:55:44"


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.ubus.async_setup_entry", return_value=None
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def dhcp_software() -> str:
    """Return the DHCP software the mock config entry is created with."""
    return DEFAULT_DHCP_SOFTWARE


@pytest.fixture
def mock_config_entry(dhcp_software: str) -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={**MOCK_CONFIG, CONF_DHCP_SOFTWARE: dhcp_software},
        title=MOCK_HOST,
    )


@pytest.fixture
def mock_ubus_client() -> Generator[MagicMock]:
    """Mock the aioubus client with parsed router responses."""
    with (
        patch(
            "homeassistant.components.ubus.coordinator.UbusClient", autospec=True
        ) as mock_client,
        patch("homeassistant.components.ubus.config_flow.UbusClient", new=mock_client),
    ):
        client = mock_client.return_value
        client.list_hostapd_interfaces.return_value = ("phy0-ap0",)
        client.get_hostapd_clients.return_value = HostapdClients.from_json(
            "phy0-ap0", load_json_object_fixture("hostapd_clients.json", DOMAIN)
        )
        client.get_dnsmasq_leases.return_value = parse_dnsmasq_leases(
            load_fixture("dhcp.leases", DOMAIN)
        )
        client.get_odhcpd_ipv4_leases.return_value = parse_odhcpd_leases(
            load_json_object_fixture("odhcpd_ipv4leases.json", DOMAIN)
        )
        yield mock_client
