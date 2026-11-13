"""Binary sensors for the Home Presence integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomePresenceConfigEntry
from .coordinator import HomePresenceCoordinator, PersonStatus
from .entity import HomePresenceEntity
from .people import Person


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomePresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Home Presence binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [AnyoneHomeBinarySensor(coordinator)]
    entities.extend(
        PersonHomeBinarySensor(coordinator, person) for person in coordinator.people
    )
    async_add_entities(entities)


class PersonHomeBinarySensor(HomePresenceEntity, BinarySensorEntity):
    """Whether one person is home, based on any of their devices."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_translation_key = "person_home"

    def __init__(self, coordinator: HomePresenceCoordinator, person: Person) -> None:
        """Initialize the person presence sensor."""
        super().__init__(coordinator)
        self._person_slug = person.slug
        self._object_id = f"{person.slug}_home"
        self._attr_unique_id = f"{coordinator.entry_id}_{person.slug}_home"
        self._attr_translation_placeholders = {"person": person.name}

    @property
    def _person(self) -> PersonStatus | None:
        """Return the status of this person from the coordinator data."""
        data = self.coordinator.data
        if data is None:
            return None
        for person in data.people:
            if person.slug == self._person_slug:
                return person
        return None

    @property
    def is_on(self) -> bool:
        """Return True when at least one device of the person is present."""
        person = self._person
        return bool(person is not None and person.home)

    @property
    def icon(self) -> str:
        """Return the icon for the current state."""
        return "mdi:home-account" if self.is_on else "mdi:account-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the per-device details of the person."""
        person = self._person
        if person is None:
            return {"devices": []}
        return {
            "devices": [
                {
                    "token": device.token,
                    "type": device.kind,
                    "present": device.present,
                    "last_seen": (
                        device.last_seen.isoformat()
                        if device.last_seen is not None
                        else None
                    ),
                    "ip": device.ip,
                }
                for device in person.devices
            ]
        }


class AnyoneHomeBinarySensor(HomePresenceEntity, BinarySensorEntity):
    """Whether at least one person is home."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE
    _attr_translation_key = "anyone_home"
    _object_id = "anyone_home"

    def __init__(self, coordinator: HomePresenceCoordinator) -> None:
        """Initialize the household presence sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_anyone_home"

    @property
    def is_on(self) -> bool:
        """Return True when at least one person is home."""
        data = self.coordinator.data
        return bool(data is not None and data.anyone_home)

    @property
    def icon(self) -> str:
        """Return the icon for the current state."""
        return "mdi:home-account" if self.is_on else "mdi:home-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the people that are currently home."""
        data = self.coordinator.data
        return {"people": data.people_home if data is not None else []}
