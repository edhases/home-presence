"""Sensors for the Home Presence integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomePresenceConfigEntry
from .coordinator import HomePresenceCoordinator
from .entity import HomePresenceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomePresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Home Presence sensors."""
    async_add_entities([PeopleHomeSensor(entry.runtime_data)])


class PeopleHomeSensor(HomePresenceEntity, SensorEntity):
    """Number of people that are currently home."""

    _attr_translation_key = "people_home"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:account-group"
    _object_id = "people_home"

    def __init__(self, coordinator: HomePresenceCoordinator) -> None:
        """Initialize the people home sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_people_home"

    @property
    def native_value(self) -> int:
        """Return the number of people that are home."""
        data = self.coordinator.data
        return len(data.people_home) if data is not None else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the names of the people that are home."""
        data = self.coordinator.data
        if data is None:
            return {"people": [], "total": 0}
        return {"people": data.people_home, "total": len(data.people)}
