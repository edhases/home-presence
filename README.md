# Home Presence

A Home Assistant custom integration that answers **who is home** — not "which
device is online".

A person is home when **any** of their devices is detected, from **any** of two
sources:

- a **network scan** with `nmap` (matching by MAC address, IP address or
  hostname), for phones that answer ARP, and
- an existing **`device_tracker` entity** (for example the companion app), which
  keeps reporting even when the phone sleeps.

That fusion matters: MAC scanning alone loses sleeping phones, while the companion
app alone does not cover phones without the app.

## Features

- One config entry for the whole household, with a simple text format:
  `Name = device, device, ...`. A device can be a MAC address, an `ip:…` address, a
  `host:…` name or a `device_tracker` entity.
- `binary_sensor.<person_slug>_home` per person, `binary_sensor.anyone_home`, and
  `sensor.people_home`.
- `consider_home` window that survives restarts (persisted `last_seen` timestamps).
- Instant updates when a configured `device_tracker` changes state.
- Fully translated UI and entity names (English, Ukrainian).

## Installation

1. Install `nmap` on the Home Assistant host and make sure it is on the `PATH`
   (Home Assistant OS: `apk add nmap` in the Advanced SSH & Web Terminal add-on
   with protection mode disabled).
2. Copy `custom_components/home_presence` into your Home Assistant
   `config/custom_components/` directory.
3. Restart Home Assistant.
4. Add the **Home Presence** integration in **Settings → Devices & services**.

Or add this repository to HACS as a custom integration repository and install it
from there.

## Documentation

See [custom_components/home_presence/README.md](custom_components/home_presence/README.md)
for the configuration fields, the `people` format with examples, the entity list,
example automations, the device identification order and known limitations.
