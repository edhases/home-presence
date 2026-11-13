"""The Home Presence integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PLATFORMS, STORE_VERSION, build_config
from .coordinator import HomePresenceCoordinator
from .people import PeopleParseError, parse_people
from .scanner import find_nmap

_LOGGER = logging.getLogger(__name__)

type HomePresenceConfigEntry = ConfigEntry[HomePresenceCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: HomePresenceConfigEntry
) -> None:
    """Set up Home Presence from a config entry."""
    try:
        config = build_config(entry)
    except ValueError as err:
        raise ConfigEntryError(f"Invalid network configuration: {err}") from err

    try:
        people = parse_people(config.people)
    except PeopleParseError as err:
        raise ConfigEntryError(
            f"Invalid people configuration on line '{err.line}': {err.reason}"
        ) from err

    if not people:
        raise ConfigEntryError("No people are configured")

    nmap_path = await hass.async_add_executor_job(find_nmap)
    if nmap_path is None:
        raise ConfigEntryNotReady(
            "The nmap binary was not found. Install nmap on the Home Assistant host "
            "and make sure it is available on the PATH, then reload the integration."
        )
    _LOGGER.debug("Using nmap at %s", nmap_path)

    coordinator = HomePresenceCoordinator(hass, entry, config, people)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(
    hass: HomeAssistant, entry: HomePresenceConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_flush()
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: HomePresenceConfigEntry
) -> None:
    """Remove the persisted presence timestamps of a deleted entry."""
    store: Store[dict[str, object]] = Store(
        hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}"
    )
    await store.async_remove()
