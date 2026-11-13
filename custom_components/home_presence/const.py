"""Constants and configuration helpers for the Home Presence integration."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

DOMAIN = "home_presence"
NAME = "Home Presence"
MANUFACTURER = "Home Presence"
VERSION = "0.1.0"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONF_SUBNET = "subnet"
CONF_SCAN_OPTIONS = "scan_options"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CONSIDER_HOME = "consider_home"
CONF_PEOPLE = "people"

DEFAULT_SUBNET = "192.168.1.0/24"
DEFAULT_SCAN_OPTIONS = "-n -sn -PR -T4 --host-timeout 3s"
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_CONSIDER_HOME = 10

MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 600
MIN_CONSIDER_HOME = 1
MAX_CONSIDER_HOME = 240

NMAP_BINARY = "nmap"
NMAP_SCAN_TIMEOUT = 180
#: The config form additionally runs one short scan to list known devices.
DEVICES_SCAN_TIMEOUT = 5

#: Store key is ``home_presence.<config entry id>``.
STORE_VERSION = 1
#: Coalesce writes of the ``last_seen`` timestamps.
STORE_SAVE_DELAY = 5


@dataclass(frozen=True, slots=True)
class HomePresenceConfig:
    """Validated configuration of a Home Presence config entry."""

    subnets: tuple[str, ...]
    scan_options: str
    scan_interval: int
    consider_home: int
    people: str

    @property
    def consider_home_delta(self) -> timedelta:
        """Return the keep-home window as a timedelta."""
        return timedelta(minutes=self.consider_home)

    @property
    def network_list(self) -> str:
        """Return the networks as a human readable, comma separated list."""
        return ", ".join(self.subnets)


def parse_subnets(value: str) -> tuple[str, ...]:
    """Parse a comma separated list of IPv4 networks in CIDR notation.

    Raises ValueError when the value is empty or contains something that is not
    a valid network.
    """
    subnets: list[str] = []
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError as err:
            raise ValueError(f"invalid network: {item}") from err
        if network.version != 4:
            raise ValueError(f"only IPv4 networks are supported: {item}")
        normalized = str(network)
        if normalized not in subnets:
            subnets.append(normalized)
    if not subnets:
        raise ValueError("no networks configured")
    return tuple(subnets)


def _as_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Coerce a config value to an int within the allowed range."""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def build_config(entry: ConfigEntry) -> HomePresenceConfig:
    """Build the effective configuration from a config entry.

    Options (set by the options flow) take precedence over the original data.
    """
    merged: dict[str, object] = {**entry.data, **(entry.options or {})}

    scan_options = str(merged.get(CONF_SCAN_OPTIONS) or DEFAULT_SCAN_OPTIONS).strip()
    return HomePresenceConfig(
        subnets=parse_subnets(str(merged.get(CONF_SUBNET) or DEFAULT_SUBNET)),
        scan_options=scan_options or DEFAULT_SCAN_OPTIONS,
        scan_interval=_as_int(
            merged.get(CONF_SCAN_INTERVAL),
            DEFAULT_SCAN_INTERVAL,
            MIN_SCAN_INTERVAL,
            MAX_SCAN_INTERVAL,
        ),
        consider_home=_as_int(
            merged.get(CONF_CONSIDER_HOME),
            DEFAULT_CONSIDER_HOME,
            MIN_CONSIDER_HOME,
            MAX_CONSIDER_HOME,
        ),
        people=str(merged.get(CONF_PEOPLE) or ""),
    )
