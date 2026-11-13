"""nmap based network scanning for the Home Presence integration."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import shlex
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from .const import NMAP_BINARY, NMAP_SCAN_TIMEOUT
from .people import normalize_mac

_LOGGER = logging.getLogger(__name__)

_UP_STATE: Final = "up"
_MAX_TABLE_ROWS: Final = 40


class NmapNotFoundError(RuntimeError):
    """Raised when the nmap binary is not available."""


class NmapScanError(RuntimeError):
    """Raised when nmap could not run or returned unusable output."""


@dataclass(frozen=True, slots=True)
class ScanHost:
    """A host that answered during a scan."""

    ip: str | None
    mac: str | None
    hostname: str | None


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Result of one scan, indexed for MAC, IP and hostname lookups."""

    hosts: tuple[ScanHost, ...] = ()
    by_mac: dict[str, ScanHost] = field(default_factory=dict)
    by_ip: dict[str, ScanHost] = field(default_factory=dict)
    by_hostname: dict[str, ScanHost] = field(default_factory=dict)

    @classmethod
    def from_hosts(cls, hosts: Iterable[ScanHost]) -> ScanResult:
        """Build a scan result and its lookup indexes."""
        host_list = tuple(hosts)
        return cls(
            hosts=host_list,
            by_mac={host.mac: host for host in host_list if host.mac},
            by_ip={host.ip: host for host in host_list if host.ip},
            by_hostname={
                host.hostname: host for host in host_list if host.hostname
            },
        )

    @classmethod
    def empty(cls) -> ScanResult:
        """Return an empty scan result."""
        return cls()


def find_nmap() -> str | None:
    """Return the path of the nmap binary, or None when it is missing."""
    return shutil.which(NMAP_BINARY)


def parse_nmap_xml(xml_text: str) -> tuple[ScanHost, ...]:
    """Extract the hosts that are up from ``nmap -oX`` output.

    Hostnames are only reported by nmap when reverse DNS is enabled, so they
    may be missing when the scan options contain ``-n``.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise NmapScanError(f"Could not parse the nmap XML output: {err}") from err

    hosts: list[ScanHost] = []
    for host in root.iter("host"):
        status = host.find("status")
        if status is None or status.get("state") != _UP_STATE:
            continue

        mac: str | None = None
        ip: str | None = None
        hostname: str | None = None

        for address in host.iter("address"):
            value = address.get("addr")
            if not value:
                continue
            addrtype = address.get("addrtype")
            if addrtype == "mac":
                mac = normalize_mac(value)
            elif addrtype in ("ipv4", "ipv6") and ip is None:
                ip = value

        hostnames = host.find("hostnames")
        if hostnames is not None:
            for element in hostnames.iter("hostname"):
                name = element.get("name")
                if name and name.strip():
                    hostname = name.strip().lower()
                    break

        hosts.append(ScanHost(ip=ip, mac=mac, hostname=hostname))

    return tuple(hosts)


def _ip_sort_key(host: ScanHost) -> tuple[int, bytes]:
    """Sort hosts by IP address, keeping hosts without a usable IP last."""
    if host.ip is None:
        return (1, b"")
    try:
        return (0, ipaddress.ip_address(host.ip).packed)
    except ValueError:
        return (2, host.ip.encode())


def format_hosts_table(
    hosts: Iterable[ScanHost], limit: int = _MAX_TABLE_ROWS
) -> str:
    """Format discovered hosts as a copyable IP/MAC/hostname table.

    Hosts without a MAC address are skipped, because the table exists to help
    users fill in the ``people`` option.
    """
    rows = [host for host in hosts if host.mac]
    rows.sort(key=_ip_sort_key)

    lines = [
        f"{host.ip or '-':<15}  {host.mac or '':<17}  {host.hostname or ''}".rstrip()
        for host in rows[:limit]
    ]
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more")
    return "\n".join(lines)


async def async_scan(
    subnets: Sequence[str],
    scan_options: str,
    timeout: float = NMAP_SCAN_TIMEOUT,
) -> ScanResult:
    """Run nmap once and return the detected hosts.

    Raises :class:`NmapNotFoundError` when the binary cannot be started and
    :class:`NmapScanError` for any other failure.
    """
    binary = find_nmap()
    if binary is None:
        raise NmapNotFoundError(
            "The nmap binary was not found. Install nmap and make sure it is on "
            "the PATH."
        )

    args = [binary, "-oX", "-", *shlex.split(scan_options), *subnets]
    _LOGGER.debug("Running nmap scan: %s", " ".join(args))

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as err:
        raise NmapNotFoundError(f"Could not start nmap: {err}") from err

    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await process.communicate()
    except TimeoutError as err:
        process.kill()
        await process.wait()
        raise NmapScanError(
            f"The nmap scan timed out after {timeout} seconds"
        ) from err

    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or "unknown error"
        raise NmapScanError(f"nmap exited with {process.returncode}: {message}")

    output = stdout.decode(errors="replace")
    if not output.strip():
        raise NmapScanError("nmap returned no output")

    result = ScanResult.from_hosts(parse_nmap_xml(output))
    _LOGGER.debug("nmap found %s host(s)", len(result.hosts))
    return result
