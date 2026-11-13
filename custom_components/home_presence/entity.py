"""Shared entity base class for the Home Presence integration."""

from __future__ import annotations

from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HomePresenceCoordinator


class HomePresenceEntity(CoordinatorEntity[HomePresenceCoordinator]):
    """Base class for all Home Presence entities."""

    _attr_has_entity_name = True

    #: Stable, language independent object ID, used to build the entity ID.
    _object_id: str | None = None

    @property
    def suggested_object_id(self) -> str | None:
        """Return the object ID used to generate the entity ID.

        The object ID is derived from the configured person name instead of the
        translated entity name, so entity IDs do not change with the UI
        language.
        """
        return self._object_id

    async def async_added_to_hass(self) -> None:
        """Subscribe to the configured device_tracker entities."""
        await super().async_added_to_hass()

        tracked_entities = self.coordinator.tracked_entities
        if not tracked_entities:
            return

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, tracked_entities, self._async_tracked_entity_changed
            )
        )

    @callback
    def _async_tracked_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """React immediately when a device_tracker entity changes state."""
        self.coordinator.async_handle_tracker_event()
        self.async_write_ha_state()
