# MelcoBEMS MINI (A1M) — Mitsubishi VRF for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/jamesrossell/melcobems_a1m)](https://github.com/jamesrossell/melcobems_a1m/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local-polling Home Assistant integration for **Mitsubishi Electric City Multi VRF indoor
units** controlled over **Modbus RTU** via the **MelcoBEMS MINI (A1M)** interface — using the
A1M's *Air-To-Air* register set.

Each indoor unit becomes a proper Home Assistant **Device** with a climate entity, sensors,
fault monitoring and — the headline feature — first-class support for the A1M's obscure but
brilliant **Setpoint Offset** function, which makes a ducted unit thermostat on a *real room
temperature sensor* instead of its own return-air thermistor.

As far as I can tell this is the **first public integration of any kind for the A1M's
Air-To-Air registers** — everything else out there (Home Assistant, ESPHome, openHAB,
Node-RED) targets the A1M's Air-To-Water/Ecodan tables, which share nothing with this one.

---

## Background — how and why this exists

My house has a Mitsubishi **PUMY-P300YBM** (City Multi S-series, 2-pipe heat pump — one
compressor) feeding **five PEFY ducted indoor units** (PEFY-P·VMS1-E and PEFY-M·VMA-A).
When it was installed I made a bold decision: **no wall controllers at all**. Each indoor
unit got a MelcoBEMS MINI (A1M) on its CN105 connector, all five daisy-chained on one RS-485
bus into a USB-serial adapter on my Home Assistant server. Modbus or nothing.

**Phase 1 — YAML.** There was no reference material for this combination anywhere, so I
mapped the A1M registers into Home Assistant's built-in `modbus:` climate platform by hand.
It mostly worked — heating, cooling, fan and setpoints were fine — but two things never sat
right: *Auto mode did nothing*, and the units *didn't stop cooling when the room was
already cold*.

**Phase 2 — research.** A deep sweep of GitHub, HACS, the HA community forum, Reddit and
the official Mitsubishi/MELSmart documentation (run with Claude doing the digging) found:

- **No existing integration, component, or even shared YAML** for the A1M Air-To-Air
  registers. The entire A1M open-source ecosystem is Ecodan/Air-To-Water. The only other
  code on the internet speaking these registers was a single Fibaro home-centre Lua script.
- **Auto mode is a hardware impossibility here, not a bug.** A 2-pipe City Multi runs ONE
  mode system-wide. Native auto-changeover exists only via an outdoor-unit DIP switch
  (SW9-1), applies only through the lowest-address unit, and switches every zone together.
  Probed live: writing mode=8 (Auto) to a unit makes it quietly **demote itself to FAN** —
  the A1M ACKs the write and the register snaps back. So "Auto" in a dashboard was actually
  turning that room's conditioning *off*.
- **The return-air problem is physics.** A ducted unit's TH21 thermistor sits at the unit
  inlet in the ceiling void. Under active cooling, supply air short-circuits back and the
  unit can believe the room is *several degrees colder* than it is (I logged a 15 °C reading
  while an independent sensor in the same room never went below 19.2 °C). Mitsubishi's own
  design book acknowledges ceiling-unit return-air readings "may differ" and suggests
  separate thermostats.
- **The fix was hiding in the A1M manual all along**: the *Setpoint Offset* feature
  (registers 15/16/17). A BMS writes the real room temperature into a volatile register and
  the A1M continuously re-derives the unit's internal setpoint:
  `unit_setpoint = return_air − (bms_room_temp − virtual_setpoint)` — so the unit
  effectively thermostats on the real room sensor. I could find **zero published field use**
  of this feature. It works beautifully.

**Phase 3 — this integration.** The YAML got fixed, the Setpoint Offset was proven live on
one bedroom, and then the whole thing was rebuilt properly: a config-flow integration, one
Device per indoor unit, one block-read per unit per cycle instead of ~30 single-register
polls, and the offset feed engine running natively with watchdog semantics. This repo is
the result — published in the hope that the next person searching "A1M Modbus Home
Assistant" finds more than I did.

---

## Features

- **One Device per indoor unit** (plus a bus device), with firmware version, area support
  and all entities grouped where they belong.
- **Climate entity** per unit: heat / cool / dry / fan-only, fan speeds (auto / low /
  medium / high / top), 0.5 °C setpoint steps, best-effort `hvac_action`.
  *Auto is deliberately not offered* (see background).
- **Setpoint Offset engine** (per unit, opt-in): pick any HA temperature sensor as the
  room reference and the integration keeps the A1M fed with it. When active, the climate
  entity shows the *real* room temperature and the *virtual* target — what your family
  expects a thermostat to mean. Safety semantics built in:
  - source sensor stale (>2 h) or unavailable → feature disabled at the A1M (write 0)
  - Home Assistant stopping / integration unloading → disabled at the A1M
  - A1M power-cycle wipes the volatile register → automatically re-armed next cycle
  - writes only on change (the EEPROM-backed virtual setpoint is written on change only)
- **Efficient polling**: one FC03 block read (regs 0–19) per unit per cycle
  (default 30 s, configurable 10–300 s).
- **Fault monitoring**: decoded fault sensor ("OK" / "A1M-to-unit comms fault (CN105)" /
  "Unit fault NNNN"), a `problem` binary sensor per unit for alerting, plus diagnostic
  firmware and bus-traffic counters.
- **Virtual Setpoint number entity** per unit for automations/dashboards.
- Transport: serial RTU today; RTU-over-TCP plumbing is present for serial-device servers
  and the A1M+ generation.

## Tested on

| Component | Detail |
|---|---|
| Outdoor unit | PUMY-P300YBM (City Multi S-series, 2-pipe) |
| Indoor units | PEFY-P50VMS1-E, PEFY-P40VMS1-E, PEFY-M80VMA-A, PEFY-M50VMA-A, PEFY-M40VMA-A1 |
| Interface | MelcoBEMS MINI (A1M) × 5, firmware 3.0.29, RS-485 daisy chain @ 9600 8N1 |
| Adapter | FTDI FT232R USB-RS485 |
| Home Assistant | 2026.7 (HAOS) |

It should work with any City Multi / Mr Slim indoor unit the A1M supports in Air-To-Air
mode. Air-To-Water (Ecodan) systems use a different register table — this integration will
refuse them at setup (it validates every unit answers as Air-To-Air).

## Installation

### HACS (custom repository)

1. HACS → **⋮** (top right) → **Custom repositories**
2. Repository: `https://github.com/jamesrossell/melcobems_a1m` — Type: **Integration** → Add
3. Search for "MelcoBEMS", download, restart Home Assistant.

### Manual

Copy `custom_components/melcobems_a1m/` into your config's `custom_components/` and restart.

## Configuration

**Settings → Devices & Services → Add Integration → "MelcoBEMS MINI (A1M)"**

| Field | Example |
|---|---|
| Connection | `serial` |
| Serial port | `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0` |
| Baud rate | `9600` (A1M default) |
| Units | `1:Kitchen, 2:Lounge, 3:Master Bedroom` |

Every listed unit is probed live during setup — no reply, or an Air-To-Water answer, fails
fast with a clear error.

> ⚠️ The serial port must not be in use by anything else (e.g. a built-in `modbus:` YAML
> hub). Remove/disable the old configuration first.

### Enabling Setpoint Offset (the good stuff)

Integration tile → **Configure**:
pick an external temperature sensor for a unit (e.g. `ext_entity_3`), tick its enable box
(`offset_enabled_3`), submit. Within a poll cycle the unit starts thermostatting on the real
room temperature. Requires A1M firmware ≥ 3.0.18 (3.0.19+ recommended).

## Entities per unit

| Entity | Notes |
|---|---|
| `climate.<unit>` | Primary control. Attributes expose `setpoint_offset_active`, raw `unit_setpoint_reg1`, `return_air_reg8`. |
| `sensor.<unit>_return_air_temperature` | TH21 reading (reg 8) — useful history even with offset active |
| `sensor.<unit>_fault` | Decoded from reg 12 (`8000`=OK, `6999`=CN105 fault) |
| `binary_sensor.<unit>_problem` | `on` when fault ≠ OK — alert on this |
| `number.<unit>_virtual_setpoint` | Reg 17 (EEPROM-backed; written on change only) |
| `sensor.<unit>_a1m_firmware` / `sensor.<unit>_modbus_comms_counter` | Diagnostics |

## A1M Air-To-Air register map (as implemented)

All holding registers, 0-based protocol addressing; temperatures °C×10 unless noted.

| Reg | Function | R/W | Values / notes |
|-----|----------|-----|----------------|
| 0 | Drive mode | RW | 1 heat · 2 dry · 3 cool · 7 fan · 8 auto (see below) · 9/10/11 read-only i-see variants |
| 1 | Setpoint | RW | °C×10 |
| 2 | Fan speed | RW | 0 auto · 2 low · 3 med · 5 high · 6 very-high |
| 3 | Vane | RW | not implemented (N/A on ducted PEFY) |
| 4/5/6 | Modbus address / baud / parity | RW | **never write** — bus-breaking, deliberately not exposed |
| 7 | Power | RW | 0 off · 1 on |
| 8 | Return air temp (TH21) | RO | int16 °C×10 |
| 10 | Firmware | RO | e.g. `30029` = 3.0.29 |
| 11 | Comms counter | RO | wraps at 65535 |
| 12 | Fault code | RO | 8000 OK · 6999 CN105 fault · else unit code |
| 13 | System type | RO | 0 = Air-To-Air (validated at setup) |
| 14 | Deadband (DIP 8) state | RO | A1M auto-emulation; keep OFF when using Setpoint Offset |
| 15/16 | BMS room temperature (signed/unsigned views) | RW | volatile; **0 disables offset**; this integration feeds reg 16 |
| 17 | BMS virtual setpoint | RW | EEPROM-backed |
| 18/19 | Deadband heat/cool setpoints | RW | °C×**1** (not ×10); not exposed |
| Coil 0 | Drive on/off | RW | duplicate of reg 7; not used |

## Limitations & design decisions

- **No Auto mode, on purpose.** On 2-pipe (heat-pump, non-heat-recovery) City Multi systems
  the unit demotes Auto to FAN — offering it in the UI silently disables conditioning.
  If you run an R2 heat-recovery system and Auto genuinely works via the A1M, open an issue.
- **No vane/swing** (ducted units have none). Trivial to add for cassettes/wall units —
  PRs or issues with test hardware welcome.
- **Deadband (A1M auto-emulation) not exposed** — it fights both HA and the Setpoint Offset.
- One climate per A1M; group control via HA groups/automations.
- `hvac_action` is inferred (the ATA map has no thermo-on register) — treat as best-effort.
- PEFY-M·VMA-A units are not on the A1M's official compatibility list (which predates them);
  they work fine here, but officially you're in the same boat I am.

## Roadmap

- Whole-house "season arbiter" (single heat/cool decision for 2-pipe systems, per-room
  thermostatting inside it)
- ESPHome port (free the USB port, RS-485 straight into an ESP32)
- HACS default-store inclusion

## Disclaimer

Not affiliated with, or endorsed by, Mitsubishi Electric or Procon. MelcoBEMS, City Multi,
Mr Slim and Ecodan are trademarks of their respective owners. You are writing registers on
heating/cooling plant — understand your system, and use at your own risk.

## Credits

- Register semantics: *MELCOBEMS MINI (A1M) Install & User Manual* (Mitsubishi Electric UK / MELSmart).
- Research, register validation and the integration itself were built in an extended
  pairing session with **Claude** (Anthropic) — including the live register probes that
  proved the Auto-demotion behaviour and the first field deployment of Setpoint Offset.
- The Home Assistant community, whose Ecodan/A1M Air-To-Water projects proved the bus wiring
  approach even though the registers were all different.

## License

[MIT](LICENSE) © 2026 James Rossell
