"""Data update coordinator for the Home Presence integration."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STORE_SAVE_DELAY,
    STORE_VERSION,
    HomePresenceConfig,
)
from .people import DeviceKind, Person, PersonDevice
from .scanner import (
    NmapNotFoundError,
    NmapScanError,
    ScanHost,
    ScanResult,
    async_scan,
)

_LOGGER = logging.getLogger(__name__)

_STATE_UNKNOWN: Final = "unknown"
_STATE_UNAVAILABLE: Final = "unavailable"


@dataclass(slots=True)
class DeviceStatus:
    """Presence state of a single device of a person."""

    token: str
    kind: DeviceKind
    present: bool
    last_seen: datetime | None = None
    ip: str | None = None


@dataclass(slots=True)
class PersonStatus:
    """Presence state of one person."""

    name: str
    slug: str
    home: bool
    devices: list[DeviceStatus]


@dataclass(slots=True)
class PresenceData:
    """Data snapshot shared by every entity of the integration."""

    people: list[PersonStatus]
    hosts: tuple[ScanHost, ...]
    scan_ok: bool

    @property
    def people_home(self) -> list[str]:
        """Return the names of the people that are home."""
        return [person.name for person in self.people if person.home]

    @property
    def anyone_home(self) -> bool:
        """Return True when at least one person is home."""
        return any(person.home for person in self.people)


class HomePresenceCoordinator(DataUpdateCoordinator[PresenceData]):
    """Scan the network and fuse it with device_tracker entities."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config: HomePresenceConfig,
        people: tuple[Person, ...],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=config.scan_interval),
        )
        self.config = config
        self.people = people
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._last_seen: dict[str, datetime] = {}
        self._scan = ScanResult.empty()
        self._scan_ok = True
        self._dirty = False
        self._nmap_missing_warned = False
        self._scan_error_warned = False

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------
    async def async_setup(self) -> None:
        """Load the persisted ``last_seen`` timestamps."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        raw_last_seen = stored.get("last_seen")
        if not isinstance(raw_last_seen, dict):
            return
        for key, value in raw_last_seen.items():
            if not isinstance(value, str):
                continue
            parsed = dt_util.parse_datetime(value)
            if parsed is None:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt_util.UTC)
            self._last_seen[str(key)] = parsed

    async def async_flush(self) -> None:
        """Write pending ``last_seen`` data, e.g. when the entry unloads."""
        if not self._last_seen:
            return
        await self._store.async_save(self._data_to_save())

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    @property
    def entry_id(self) -> str:
        """Return the config entry ID."""
        return self.config_entry.entry_id

    @property
    def tracked_entities(self) -> list[str]:
        """Return the configured device_tracker entity IDs."""
        return [
            device.token
            for device in self._devices()
            if device.kind == "entity"
        ]

    # ------------------------------------------------------------------
    # Data updates
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> PresenceData:
        """Scan the network and recompute the presence of every person."""
        now = dt_util.utcnow()

        try:
            scan = await async_scan(self.config.subnets, self.config.scan_options)
        except NmapNotFoundError as err:
            if not self._nmap_missing_warned:
                _LOGGER.warning(
                    "nmap is not available, MAC based detection is disabled: %s", err
                )
                self._nmap_missing_warned = True
            scan = ScanResult.empty()
            scan_ok = False
        except NmapScanError as err:
            if not self._scan_error_warned:
                _LOGGER.warning(
                    "Network scan failed, falling back to the keep-home window: %s",
                    err,
                )
                self._scan_error_warned = True
            else:
                _LOGGER.debug("Network scan failed: %s", err)
            scan = ScanResult.empty()
            scan_ok = False
        else:
            self._nmap_missing_warned = False
            self._scan_error_warned = False
            scan_ok = True

        self._scan = scan
        self._scan_ok = scan_ok

        self._remember_scan_hits(scan, now)
        self._remember_tracker_hits(now)
        self._schedule_save()

        return self._build_data(now, scan, scan_ok)

    @callback
    def async_handle_tracker_event(self) -> None:
        """Recompute presence after a tracked entity changed state.

        This never re-runs nmap: it re-reads the tracker states and reuses the
        last scan result, so the entities react immediately to app updates.
        """
        if self.data is None:
            return

        now = dt_util.utcnow()
        self._remember_tracker_hits(now)

        data = self._build_data(now, self._scan, self._scan_ok)
        if data != self.data:
            self.data = data
            # Do not use async_set_updated_data(): it resets the poll timer and
            # frequent tracker attribute updates would postpone the nmap scan.
            self.async_update_listeners()
        self._schedule_save()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _devices(self) -> Iterator[PersonDevice]:
        """Iterate over all configured devices of all people."""
        for person in self.people:
            yield from person.devices

    def _scan_host(self, device: PersonDevice, scan: ScanResult) -> ScanHost | None:
        """Return the scan host matching a scan based device token."""
        if device.kind == "mac":
            return scan.by_mac.get(device.token)
        if device.kind == "ip":
            return scan.by_ip.get(device.token)
        if device.kind == "host":
            return scan.by_hostname.get(device.token)
        return None

    def _remember_scan_hits(self, scan: ScanResult, now: datetime) -> None:
        """Store the detection time of every device seen by the scan."""
        for device in self._devices():
            if device.kind == "entity":
                continue
            if self._scan_host(device, scan) is not None:
                self._remember(device.key, now)

    def _remember_tracker_hits(self, now: datetime) -> None:
        """Store the detection time of every tracker that reports home."""
        for device in self._devices():
            if device.kind == "entity" and self._is_tracker_home(device.token):
                self._remember(device.key, now)

    def _remember(self, key: str, now: datetime) -> None:
        """Store the last detection time of a device, flagging a save if needed."""
        previous = self._last_seen.get(key)
        if previous is None or now - previous > self.config.consider_home_delta:
            self._dirty = True
        self._last_seen[key] = now

    def _build_data(
        self, now: datetime, scan: ScanResult, scan_ok: bool
    ) -> PresenceData:
        """Build the presence snapshot from the cache and the given scan."""
        window = self.config.consider_home_delta
        people: list[PersonStatus] = []

        for person in self.people:
            devices: list[DeviceStatus] = []
            for device in person.devices:
                last_seen = self._last_seen.get(device.key)
                host: ScanHost | None = None
                ip: str | None = None

                if device.kind == "entity":
                    present = self._is_tracker_home(device.token)
                else:
                    host = self._scan_host(device, scan)
                    ip = host.ip if host is not None else None
                    if device.kind == "ip":
                        ip = device.token
                    present = host is not None or (
                        last_seen is not None and now - last_seen <= window
                    )

                devices.append(
                    DeviceStatus(
                        token=device.token,
                        kind=device.kind,
                        present=present,
                        last_seen=last_seen,
                        ip=ip,
                    )
                )

            people.append(
                PersonStatus(
                    name=person.name,
                    slug=person.slug,
                    home=any(device.present for device in devices),
                    devices=devices,
                )
            )

        return PresenceData(people=people, hosts=scan.hosts, scan_ok=scan_ok)

    def _is_tracker_home(self, entity_id: str) -> bool:
        """Return True when a tracker reports home.

        ``unknown``, ``unavailable`` and missing entities are ignored: they do
        not prove the person is away, but they are also not a "home" signal.
        """
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (_STATE_UNKNOWN, _STATE_UNAVAILABLE):
            return False
        return state.state == STATE_HOME

    @callback
    def _schedule_save(self) -> None:
        """Persist the timestamps, coalescing writes."""
        if not self._dirty:
            return
        self._dirty = False
        self._store.async_delay_save(self._data_to_save, STORE_SAVE_DELAY)

    def _data_to_save(self) -> dict[str, Any]:
        """Return the store payload."""
        return {
            "last_seen": {
                key: last_seen.isoformat()
                for key, last_seen in self._last_seen.items()
            }
        }
