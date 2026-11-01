"""DataUpdateCoordinator for the OpenWrt (ubus) integration."""

from collections.abc import Mapping
from datetime import timedelta
from ipaddress import ip_address
import logging
from typing import Any, override

from aioubus import DnsmasqLease, OdhcpdLease, UbusClient, UbusError
from yarl import URL

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DHCP_SOFTWARE, DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=30)

type UbusConfigEntry = ConfigEntry[UbusDataUpdateCoordinator]


def async_create_client(hass: HomeAssistant, data: Mapping[str, Any]) -> UbusClient:
    """Create a ubus client for the configured router.

    The host may carry a port or a bracketed IPv6 address. Raises ValueError
    if it is not a valid host.
    """
    host: str = data[CONF_HOST]
    port: int | None = None
    try:
        ip_address(host)
    except ValueError:
        url = URL(f"http://{host}")
        host, port = url.host or host, url.explicit_port
    return UbusClient(
        host,
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        port=port,
        session=async_get_clientsession(hass),
        # Routers redirecting HTTP to HTTPS serve self-signed certificates.
        verify_ssl=False,
    )


class UbusDataUpdateCoordinator(DataUpdateCoordinator[dict[str, str | None]]):
    """Fetch the authorized wireless clients from an OpenWrt router over ubus."""

    config_entry: UbusConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: UbusConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        self.host: str = config_entry.data[CONF_HOST]
        self.dhcp_software: str = config_entry.data[CONF_DHCP_SOFTWARE]
        self.client = async_create_client(hass, config_entry.data)
        self._hostapd: tuple[str, ...] = ()
        self._mac2name: dict[str, str] | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} - {self.host}",
            update_interval=UPDATE_INTERVAL,
        )

    @override
    async def _async_update_data(self) -> dict[str, str | None]:
        """Return the currently connected devices keyed by MAC address."""
        try:
            clients = await self._async_fetch_authorized_clients()
        except UbusError as err:
            raise UpdateFailed(f"Error querying ubus at {self.host}: {err}") from err
        if self._mac2name is None:
            try:
                self._mac2name = await self._async_generate_mac2name()
            except UbusError as err:
                # Hostnames are optional; keep tracking and retry next update.
                _LOGGER.debug("Error reading leases from %s: %s", self.host, err)
        mac2name = self._mac2name or {}
        return {mac: mac2name.get(mac) for mac in clients}

    async def _async_fetch_authorized_clients(self) -> set[str]:
        """Return the MAC addresses of authorized clients on all interfaces."""
        if not self._hostapd:
            if not (hostapd := await self.client.list_hostapd_interfaces()):
                raise UpdateFailed(f"No hostapd data from ubus at {self.host}")
            self._hostapd = hostapd
        authorized: set[str] = set()
        for interface in self._hostapd:
            result = await self.client.get_hostapd_clients(interface)
            authorized.update(
                mac for mac, client in result.clients.items() if client.authorized
            )
        return authorized

    async def _async_generate_mac2name(self) -> dict[str, str]:
        """Build the MAC-to-hostname map for the configured DHCP software."""
        leases: tuple[DnsmasqLease, ...] | tuple[OdhcpdLease, ...]
        if self.dhcp_software == "dnsmasq":
            leases = await self.client.get_dnsmasq_leases()
        elif self.dhcp_software == "odhcpd":
            leases = await self.client.get_odhcpd_ipv4_leases()
        else:
            return {}
        return {
            lease.mac: lease.hostname
            for lease in leases
            if lease.mac and lease.hostname
        }
