"""Parsing and validation of the ``people`` option.

This module is deliberately free of Home Assistant imports so the pure parsing
logic can be unit tested on its own.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

DeviceKind = Literal["mac", "ip", "host", "entity"]

_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_MAC_LENGTH: Final = 12
_ENTITY_ID_RE: Final = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_HOSTNAME_RE: Final = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")
_SLUG_RE: Final = re.compile(r"[^a-z0-9]+")
_TRACKER_DOMAIN: Final = "device_tracker"
_KNOWN_PREFIXES: Final = frozenset({"mac", "ip", "host", "entity"})

#: Cyrillic to Latin transliteration so that people with Ukrainian or Russian
#: names still get readable, stable entity IDs.
_CYRILLIC: Final[dict[str, str]] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "h",
    "ґ": "g",
    "д": "d",
    "е": "e",
    "є": "ye",
    "ж": "zh",
    "з": "z",
    "и": "y",
    "і": "i",
    "ї": "yi",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ь": "",
    "ю": "yu",
    "я": "ya",
    "ы": "y",
    "э": "e",
    "ё": "yo",
    "ъ": "",
    "’": "",
    "'": "",
}


def _build_translit_table() -> dict[int, str]:
    table: dict[int, str] = {}
    for char, latin in _CYRILLIC.items():
        table[ord(char)] = latin
        table[ord(char.upper())] = latin[:1].upper() + latin[1:]
    return table


_TRANSLIT: Final = _build_translit_table()


class PeopleParseError(ValueError):
    """Raised when a line of the ``people`` option cannot be parsed."""

    def __init__(self, line: str, reason: str) -> None:
        """Initialize the error with the offending line and a reason."""
        super().__init__(f"{reason}: {line}")
        self.line = line
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PersonDevice:
    """A device of a person: a MAC address, an IP, a hostname or a tracker."""

    token: str
    kind: DeviceKind

    @property
    def key(self) -> str:
        """Return a unique key used for the persisted ``last_seen`` data."""
        return f"{self.kind}:{self.token}"


@dataclass(frozen=True, slots=True)
class Person:
    """A person and the devices that can prove they are home."""

    name: str
    slug: str
    devices: tuple[PersonDevice, ...]


def normalize_mac(value: str) -> str | None:
    """Return a MAC address in canonical lowercase colon form, or None.

    Accepts ``aa:bb:cc:dd:ee:ff``, ``AA-BB-CC-DD-EE-FF`` and ``aabbccddeeff``.
    """
    candidate = value.strip().lower().replace(":", "").replace("-", "")
    if len(candidate) != _MAC_LENGTH:
        return None
    if any(char not in _HEX_DIGITS for char in candidate):
        return None
    return ":".join(candidate[index : index + 2] for index in range(0, _MAC_LENGTH, 2))


def normalize_entity_id(value: str) -> str | None:
    """Return a normalized ``device_tracker`` entity ID, or None."""
    entity_id = value.strip().lower()
    if not _ENTITY_ID_RE.match(entity_id):
        return None
    domain, _, object_id = entity_id.partition(".")
    if domain != _TRACKER_DOMAIN or not object_id:
        return None
    return entity_id


def normalize_ip(value: str) -> str | None:
    """Return a normalized IPv4 address, or None."""
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ValueError:
        return None


def normalize_hostname(value: str) -> str | None:
    """Return a normalized lowercase hostname, or None."""
    hostname = value.strip().lower().rstrip(".")
    if not hostname or len(hostname) > 253 or not _HOSTNAME_RE.match(hostname):
        return None
    return hostname


def parse_device_token(value: str) -> PersonDevice:
    """Parse a single device token of a person.

    Supported forms::

        D6:45:F4:AA:72:0B
        device_tracker.24117rn76e
        mac:D6:45:F4:AA:72:0B
        entity:device_tracker.24117rn76e
        ip:192.168.1.197
        host:Redmi-Note-14

    Raises ValueError with a human readable reason when the token is invalid.
    """
    token = value.strip()
    if not token:
        raise ValueError("empty device token")

    prefix, separator, remainder = token.partition(":")
    if separator and prefix.lower() in _KNOWN_PREFIXES:
        return _parse_prefixed(prefix.lower(), token, remainder)

    mac = normalize_mac(token)
    if mac is not None:
        return PersonDevice(token=mac, kind="mac")

    entity_id = normalize_entity_id(token)
    if entity_id is not None:
        return PersonDevice(token=entity_id, kind="entity")

    raise ValueError(
        f"'{token}' is not a MAC address, ip:..., host:... or a device_tracker entity"
    )


def _parse_prefixed(kind: str, original: str, value: str) -> PersonDevice:
    """Parse a token that starts with ``mac:``, ``ip:``, ``host:`` or ``entity:``."""
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"'{original}' has no value after the '{kind}:' prefix")

    if kind == "mac":
        mac = normalize_mac(stripped)
        if mac is None:
            raise ValueError(f"'{original}' is not a valid MAC address")
        return PersonDevice(token=mac, kind="mac")

    if kind == "entity":
        entity_id = normalize_entity_id(stripped)
        if entity_id is None:
            raise ValueError(f"'{original}' is not a valid device_tracker entity")
        return PersonDevice(token=entity_id, kind="entity")

    if kind == "ip":
        ip_address = normalize_ip(stripped)
        if ip_address is None:
            raise ValueError(f"'{original}' is not a valid IPv4 address")
        return PersonDevice(token=ip_address, kind="ip")

    hostname = normalize_hostname(stripped)
    if hostname is None:
        raise ValueError(f"'{original}' is not a valid hostname")
    return PersonDevice(token=hostname, kind="host")


def slugify_person_name(name: str) -> str:
    """Return an ASCII object ID slug for a person name."""
    transliterated = name.translate(_TRANSLIT)
    ascii_name = (
        unicodedata.normalize("NFKD", transliterated)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = _SLUG_RE.sub("_", ascii_name.lower()).strip("_")
    return slug or "person"


def parse_people(text: str) -> tuple[Person, ...]:
    """Parse the multiline ``people`` option.

    Format, one person per line::

        Oleksii = D6:45:F4:AA:72:0B, device_tracker.24117rn76e
        Natalia = mac:CA:D5:7C:BB:EB:90, host:Redmi-Note-14
        Kids = ip:192.168.1.197

    Empty lines and lines starting with ``#`` are ignored. Duplicate person
    names and malformed device tokens raise :class:`PeopleParseError`.
    """
    people: list[Person] = []
    seen_names: set[str] = set()
    used_slugs: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise PeopleParseError(line, "expected 'Name = device, device'")

        name_part, _, devices_part = line.partition("=")
        name = name_part.strip()
        if not name:
            raise PeopleParseError(line, "the person name is empty")

        name_key = name.casefold()
        if name_key in seen_names:
            raise PeopleParseError(line, f"duplicate person name '{name}'")
        seen_names.add(name_key)

        if not devices_part.strip():
            raise PeopleParseError(line, "the person has no devices")

        devices: list[PersonDevice] = []
        for raw_token in devices_part.split(","):
            token = raw_token.strip()
            if not token:
                raise PeopleParseError(line, "empty device token")
            try:
                device = parse_device_token(token)
            except ValueError as err:
                raise PeopleParseError(line, str(err)) from err
            if device not in devices:
                devices.append(device)

        base_slug = slugify_person_name(name)
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        used_slugs.add(slug)

        people.append(Person(name=name, slug=slug, devices=tuple(devices)))

    return tuple(people)
