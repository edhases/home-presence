"""Config and options flow for the Home Presence integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CONSIDER_HOME,
    CONF_PEOPLE,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_OPTIONS,
    CONF_SUBNET,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_OPTIONS,
    DEFAULT_SUBNET,
    DEVICES_SCAN_TIMEOUT,
    DOMAIN,
    MAX_CONSIDER_HOME,
    MAX_SCAN_INTERVAL,
    MIN_CONSIDER_HOME,
    MIN_SCAN_INTERVAL,
    NAME,
    parse_subnets,
)
from .people import PeopleParseError, parse_people
from .scanner import (
    NmapNotFoundError,
    NmapScanError,
    async_scan,
    format_hosts_table,
)

_SCAN_UNAVAILABLE = "(scan unavailable)"
_NO_DEVICES = "(no devices found)"


def _positive_int(value: Any, fallback: int) -> int:
    """Return an int default for the schemas."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


async def _async_devices_placeholder(subnet: str, scan_options: str) -> str:
    """Run one short scan and format the discovered devices for the form."""
    try:
        subnets = parse_subnets(subnet)
    except ValueError:
        return _SCAN_UNAVAILABLE

    try:
        result = await async_scan(
            subnets,
            scan_options or DEFAULT_SCAN_OPTIONS,
            timeout=DEVICES_SCAN_TIMEOUT,
        )
    except (NmapNotFoundError, NmapScanError):
        return _SCAN_UNAVAILABLE

    return format_hosts_table(result.hosts) or _NO_DEVICES


def _schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Return the shared form schema for the config and options flows."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SUBNET,
                default=str(defaults.get(CONF_SUBNET) or DEFAULT_SUBNET),
            ): selector.TextSelector(),
            vol.Required(
                CONF_SCAN_OPTIONS,
                default=str(defaults.get(CONF_SCAN_OPTIONS) or DEFAULT_SCAN_OPTIONS),
            ): selector.TextSelector(),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=_positive_int(
                    defaults.get(CONF_SCAN_INTERVAL), DEFAULT_SCAN_INTERVAL
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_CONSIDER_HOME,
                default=_positive_int(
                    defaults.get(CONF_CONSIDER_HOME), DEFAULT_CONSIDER_HOME
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_CONSIDER_HOME,
                    max=MAX_CONSIDER_HOME,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_PEOPLE,
                default=str(defaults.get(CONF_PEOPLE) or ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        }
    )


def _validate_input(
    user_input: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Validate the form input.

    Returns a tuple of errors and description placeholders. Field errors are
    keyed by the field name, form wide errors use the ``base`` key.
    """
    errors: dict[str, str] = {}
    placeholders: dict[str, str] = {}

    try:
        parse_subnets(str(user_input.get(CONF_SUBNET) or ""))
    except ValueError:
        errors[CONF_SUBNET] = "invalid_subnet"

    if not str(user_input.get(CONF_SCAN_OPTIONS) or "").strip():
        errors[CONF_SCAN_OPTIONS] = "invalid_scan_options"

    number_checks = (
        (CONF_SCAN_INTERVAL, MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL),
        (CONF_CONSIDER_HOME, MIN_CONSIDER_HOME, MAX_CONSIDER_HOME),
    )
    for field, minimum, maximum in number_checks:
        try:
            value = int(user_input.get(field))
        except (TypeError, ValueError):
            errors[field] = f"invalid_{field}"
            continue
        if not minimum <= value <= maximum:
            errors[field] = f"invalid_{field}"

    try:
        people = parse_people(str(user_input.get(CONF_PEOPLE) or ""))
    except PeopleParseError as err:
        errors["base"] = "invalid_people"
        placeholders["line"] = err.line
    else:
        if not people:
            errors["base"] = "no_people"

    return errors, placeholders


class HomePresenceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration of Home Presence."""

    VERSION = 1

    _devices: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the network scan settings and the household members."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            errors, placeholders = _validate_input(user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=NAME, data=user_input)

        if self._devices is None:
            values = user_input or {}
            self._devices = await _async_devices_placeholder(
                str(values.get(CONF_SUBNET) or DEFAULT_SUBNET),
                str(values.get(CONF_SCAN_OPTIONS) or DEFAULT_SCAN_OPTIONS),
            )
        placeholders["devices"] = self._devices

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HomePresenceOptionsFlow:
        """Return the options flow."""
        return HomePresenceOptionsFlow()


class HomePresenceOptionsFlow(OptionsFlowWithReload):
    """Handle the options of an existing Home Presence entry."""

    _devices: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the scan settings and the household members."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        entry = self.config_entry
        defaults: dict[str, Any] = {**entry.data, **(entry.options or {})}

        if user_input is not None:
            errors, placeholders = _validate_input(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        if self._devices is None:
            self._devices = await _async_devices_placeholder(
                str(defaults.get(CONF_SUBNET) or DEFAULT_SUBNET),
                str(defaults.get(CONF_SCAN_OPTIONS) or DEFAULT_SCAN_OPTIONS),
            )
        placeholders["devices"] = self._devices

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(defaults),
            errors=errors,
            description_placeholders=placeholders,
        )
