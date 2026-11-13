# Home Presence

Home Presence answers one question for your household: **who is home?**

It is not another "is this device online" sensor. A person is considered home when
**any** of their devices is detected, from **any** of two independent sources:

1. **A network scan**, run by `nmap`. This catches phones that still answer ARP on
   your LAN, even when no app is running. It is the fallback for phones without the
   Home Assistant companion app. Hosts found by the scan can be matched by MAC
   address, IP address or hostname.
2. **An existing `device_tracker` entity**, for example the Home Assistant companion
   app tracker. The app reports its location even when the phone is asleep, Wi-Fi
   is off, or the phone is on a mobile network.

Both sources are fused per device, and a person is home if at least one of their
devices is home. That is the whole point: the companion app entity is the reliable
signal for phones that sleep, and the network scan covers phones (and other
hardware) that have no app at all.

## Why MAC scanning alone is not enough

A sleeping phone stops answering ARP requests, so an `nmap` scan simply does not
see it. Integrations that only ping or scan MAC addresses therefore mark people as
away while they are sitting on the sofa with a locked phone. Conversely, a phone
that leaves the house but keeps a DHCP lease may still show up in an ARP cache for a
while. Combining the scan with the companion app tracker, and keeping a device
"home" for a configurable number of minutes after the last detection, gives a
stable result without false "away" flapping.

## How devices are identified

Tokens are matched in this order of reliability:

| Token | Reliability | Why |
| --- | --- | --- |
| `entity:device_tracker.*` | Best | The companion app reports `home` even when the phone sleeps, and it is unaffected by Wi-Fi, DHCP or MAC changes. |
| MAC address | Good | Stable for as long as the phone keeps the Wi-Fi network saved. Add a second MAC to the same person's line if the address rotates. |
| `host:name` | Fair | The DHCP/PTR hostname is usually stable, but depends on the router and on DNS being enabled in the scan. |
| `ip:192.168.1.197` | Least stable | DHCP can hand the address to another device at any time. Use it only for static addresses. |

MAC randomisation is applied **per saved Wi-Fi network**, so it normally does not
change on its own. If it does change (for example after "forget network" and
reconnect), add the new MAC to the same person's line: any matching device means the
person is home.

Recommended setup: use the companion app entity as the primary token for every phone
that has the app, and add a MAC address as a fallback for the same phone. Phones
without the app get a MAC address (or `host:`/`ip:` when no MAC is available).

## Installation

### Requirements

- Home Assistant **2026.11** or newer (Python 3.13).
- `nmap` installed on the machine that runs Home Assistant:
  - Home Assistant OS: install the **Advanced SSH & Web Terminal** add-on, disable
    protection mode, then run `apk add nmap`.
  - Debian/Ubuntu: `sudo apt install nmap`.
  - Docker: install nmap inside the container, or use a container image that ships
    it. `nmap` must be on the `PATH` of the Home Assistant process.
- ARP based detection requires the Home Assistant host to be on the **same
  layer-2 network** as the devices, and nmap needs enough privileges (root or
  `CAP_NET_RAW`) to read ARP replies.

### Manual installation

1. Copy the `custom_components/home_presence` folder into your Home Assistant
   `config/custom_components/` directory, so that the files end up in
   `config/custom_components/home_presence/`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and search for
   **Home Presence**.

### HACS (custom repository)

Add this repository to HACS as an integration, install **Home Presence**, restart
Home Assistant, then add the integration from the UI.

## Configuration

Only one config entry is needed for the whole household. The `People` field shows a
table of the devices that are currently visible on the configured networks, so you
can copy a MAC address (or hostname) straight into the field. Hosts without a MAC
address are skipped in that table.

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `Networks to scan` | text | `192.168.1.0/24` | One or more IPv4 networks in CIDR notation, comma separated. Validated with Python's `ipaddress`. |
| `nmap options` | text | `-n -sn -PR -T4 --host-timeout 3s` | Extra arguments passed to `nmap`. The integration always adds `-oX -` to read the XML result from stdout. |
| `Scan interval (seconds)` | integer | `60` | How often the network is scanned. Allowed range: 10–600. |
| `Keep devices home for (minutes)` | integer | `10` | A device stays "home" for this many minutes after it was last seen by a scan. Allowed range: 1–240. Survives restarts. |
| `People` | multiline text | — | The household definition, one person per line. See below. |

All fields can be changed later via **Settings → Devices & services → Home Presence
→ Configure**; the entry reloads automatically.

### The `people` format

```
Name = device, device, ...
```

A device can be any of:

| Form | Example | Matching |
| --- | --- | --- |
| MAC address | `D6:45:F4:AA:72:0B`, `D6-45-F4-AA-72-0B`, `D645F4AA720B` | Case-insensitive against the MAC reported by the scan. |
| `mac:` prefixed MAC | `mac:D6:45:F4:AA:72:0B` | Same as above. |
| `device_tracker` entity | `device_tracker.24117rn76e` | The state must be `home`. |
| `entity:` prefixed entity | `entity:device_tracker.24117rn76e` | Same as above. |
| `ip:` address | `ip:192.168.1.197` | Exact match with the IP reported by the scan. |
| `host:` hostname | `host:Redmi-Note-14` | Case-insensitive match with the hostname reported by the scan. |

Rules:

- A person may have any number of tokens of mixed types, including several MAC
  addresses. **Any** match means the device is home.
- Names must be unique. Empty lines are ignored.
- Lines starting with `#` are comments and are ignored.
- `ip:` is the least stable identifier (DHCP may reassign it); prefer the
  companion app entity or a MAC address.

Example: one phone with the companion app plus its MAC as a fallback, one phone
without the app, and a tablet that is always at home:

```
# Name = device, device, ...
Oleksii = entity:device_tracker.24117rn76e, D6:45:F4:AA:72:0B
Natalia = CA:D5:7C:BB:EB:90
Kids = device_tracker.kids_tablet, 3C:22:FB:1A:2B:3C
```

Example: a device with no usable MAC, identified by hostname, and a device with a
static IP:

```
Oleksii = device_tracker.pixel_9
Printer = host:HP-LaserJet-LAN
Camera = ip:192.168.1.197
```

> **Hostnames need DNS.** The default scan options contain `-n`, which disables
> reverse DNS, so nmap reports no hostnames. Remove `-n` from the nmap options if
> you want `host:` tokens (and to see hostnames in the device table).

## Entities

All entities are created from the config entry, have `has_entity_name` enabled and
use translated names.

| Entity | Type | Description |
| --- | --- | --- |
| `binary_sensor.<person_slug>_home` | binary sensor, `presence` | One per person. `on` when at least one device of that person is home. |
| `binary_sensor.anyone_home` | binary sensor, `presence` | `on` when at least one person is home. |
| `sensor.people_home` | sensor | Number of people currently home. |

`<person_slug>` is the ASCII slug of the person's name, so `Oleksii` becomes
`binary_sensor.oleksii_home`. Cyrillic names are transliterated (for example
`Олексій` becomes `oleksii`).

### Attributes

`binary_sensor.<person_slug>_home`:

```yaml
devices:
  - token: "d6:45:f4:aa:72:0b"
    type: mac
    present: true
    last_seen: "2026-11-13T18:12:04+00:00"
    ip: "192.168.1.42"
  - token: "device_tracker.24117rn76e"
    type: entity
    present: true
    last_seen: "2026-11-13T18:12:04+00:00"
    ip: null
  - token: "redmi-note-14"
    type: host
    present: false
    last_seen: null
    ip: null
```

`type` is one of `mac`, `entity`, `ip` or `host`. `ip` is filled in from the scan
result when the device was seen.

`sensor.people_home`:

```yaml
people: ["Oleksii", "Natalia"]
total: 3
```

## How updates work

- Every `scan interval` seconds `nmap` runs once for all configured networks. The
  IP address, MAC address and hostname of every host that is up are collected.
- A scan based device (MAC, `ip:` or `host:`) counts as present when it matches the
  current scan result, or when it was last seen within the `consider_home` window.
  The `last_seen` timestamps are stored in `.storage/home_presence.<entry_id>`, so
  the window survives a restart.
- A `device_tracker` counts as present only when its state is `home`. States
  `unknown`, `unavailable` and missing entities are ignored — they never prove that
  a person is away, and never override a scan hit.
- A person is home when at least one of their devices is present.
- State changes of the configured `device_tracker` entities are subscribed to, so
  the entities update immediately when the companion app reports a change. The
  periodic scan keeps the scan data fresh.

## Example automations

Turn the lights on when somebody arrives:

```yaml
automation:
  - alias: "Lights on when somebody arrives"
    triggers:
      - trigger: state
        entity_id: binary_sensor.anyone_home
        from: "off"
        to: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.living_room
```

Turn everything off when the last person leaves:

```yaml
automation:
  - alias: "Last person leaves"
    triggers:
      - trigger: state
        entity_id: sensor.people_home
        from: 1
        to: 0
    actions:
      - action: climate.turn_off
        target:
          entity_id: climate.boiler
      - action: light.turn_off
        target:
          entity_id: all
```

Per-person automation:

```yaml
automation:
  - alias: "Welcome Oleksii"
    triggers:
      - trigger: state
        entity_id: binary_sensor.oleksii_home
        from: "off"
        to: "on"
    actions:
      - action: notify.mobile_app_pixel
        data:
          message: "Welcome home!"
```

## Limitations

- **MAC randomisation.** Modern phones randomise their Wi-Fi MAC per saved network.
  It normally stays the same on that network, but if it rotates, add the new MAC to
  the same person's line. The companion app tracker is unaffected by this.
- **`ip:` is unstable.** DHCP may hand an address to another device, which would
  produce a false "home". Use `ip:` only for static leases.
- **Hostnames need DNS.** With `-n` in the nmap options, nmap does not resolve
  hostnames, so `host:` tokens and the hostname column of the device table stay
  empty.
- **`nmap` is required.** Without the binary the integration cannot start and will
  ask you to install it. If nmap disappears later, a single warning is logged and
  the scan data is treated as empty; presence then falls back to the
  `consider_home` window and to `device_tracker` entities.
- **Same network segment.** ARP scanning only sees devices on the same layer-2
  network. Devices behind a router, on a guest VLAN or on a VPN will only be
  detected through a `device_tracker` entity, or by `ip:`/`host:` if they are
  routed to and nmap can reach them.
- **Privileges.** Without root or `CAP_NET_RAW`, nmap may still list hosts but
  cannot report MAC addresses. In that case use `ip:` or `host:` tokens.
- **Sleeping phones and the app.** The companion app reports when it can; iOS in
  particular may delay background updates. This integration cannot make a sleeping
  phone answer ARP — it only makes sure that one working source is enough.
- **Multiple devices per person.** List all of a person's devices (phone, tablet,
  laptop) so that any of them can prove presence.
