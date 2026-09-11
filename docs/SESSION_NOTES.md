# Session notes — Midea AC node server

Everything needed to pick this project back up in a fresh session.

---

## 1. What this is

A Polyglot v3 (PG3/PG3x) node server for Universal Devices EISY/Polisy that
monitors and controls Midea smart air conditioners on the local network, built
on [msmart-ng](https://github.com/mill1000/midea-msmart) (`pip install
msmart-ng`, import name `msmart`).

* Repository: `evilpete/eisy-polyg-midea`
* Development branch: `claude/universal-devices-eisy-polyglot-v82x4n`

## 2. Decisions already made

These were chosen by the repo owner at the start and should not be revisited
without asking:

| Decision | Choice |
| --- | --- |
| Device types | **AC (`0xAC`) only.** CC (`0xCC`) is deliberately out of scope. |
| Device discovery | **Auto-discover plus manual override.** Broadcast on the LAN, and allow per-device entries in Custom Parameters that pin ip/id/token/key. |
| V3 authentication | **Stored token/key only.** The owner pastes token+key into Custom Parameters. The node server never contacts the Midea cloud — every `Discover` call passes `auto_connect=False`. Cloud fetch was explicitly declined. |
| Feature depth | **Capability-driven full set.** Call `get_capabilities()` per device and gate everything on it. |

## 3. Layout

```
midea-poly.py             entry point; builds the Interface and the Controller
nodes/
  controller.py           config parsing, discovery, node creation, polling
  ac.py                   one air conditioner: publish state, handle commands
  aioloop.py              background asyncio loop; msmart is async, PG3 is not
  mapping.py              UOM constants, temperature conversion, small parsers
profile/
  nodedef/nodedefs.xml    MIDEACTRL and MIDEAAC node definitions
  editor/editors.xml      value editors, including dual-UOM temperature ranges
  nls/en_us.txt           every driver, command and index label
tools/
  standalone.py           run the plugin's own code against real hardware, no PG3
tests/
  run.py                  runs everything
  test_offline.py         controller + node behaviour against a fake device
  test_profile.py         profile/NLS/Python consistency
  stubs/udi_interface.py  stand-in for the real udi_interface
POLYGLOT_CONFIG.md        shown on the PG3 configuration page
```

## 4. How to run things

```shell
pip install msmart-ng          # udi_interface is NOT needed off-box
python3 tests/run.py           # 53 tests, all offline

# Against real hardware, with no Polyglot involved:
./tools/standalone.py discover --save          # find units, write devices.conf
./tools/standalone.py devices                  # show what is configured
./tools/standalone.py probe 10.1.1.39
./tools/standalone.py query   --device Bedroom
./tools/standalone.py raw     --device Bedroom
./tools/standalone.py caps    --device Bedroom
./tools/standalone.py watch   --device Bedroom -n 5 -i 15
./tools/standalone.py control --device Bedroom --cmd CLISPC --value 72
./tools/standalone.py params 'temp_units=F' 'Bedroom=ip=10.1.1.39; id=...'
```

**Where credentials live.** On the EISY: PG3 Custom Parameters. For the
standalone tool: a config file in the identical syntax, so entries can be
pasted between the two. Searched in order — `--config`, `$MIDEA_CONFIG`,
`./devices.conf`, `~/.config/midea-poly/devices.conf`, `~/.midea-devices.conf`.
`$MIDEA_TOKEN` / `$MIDEA_KEY` are a last-resort fallback. The tool warns on a
group- or world-readable file and creates new ones as 0600; `devices.conf` is
gitignored.

`query` prints the ISY drivers with their decoded labels, so it shows exactly
what the Admin Console would show. `raw` prints the library's own view. Add
`--debug` for full msmart protocol logging.

Note that `udi_interface` cannot be pip-installed in a plain container (its
`netifaces` dependency needs a C toolchain). That is why `tests/stubs/
udi_interface.py` exists; it is shadowed by the real package on an EISY.

## 5. Design notes worth remembering

**Async bridge.** msmart is asyncio; PG3 calls back on threads. `nodes/
aioloop.py` runs one event loop on a daemon thread for the process lifetime.
Every call goes through `RUNNER.run(coro, timeout)`, so a wedged device cannot
block a poll thread forever. Each node holds an `asyncio.Lock` created on that
loop, so a poll and a command never overlap on one device.

**Node addresses.** `mapping.address_for()` = `'ac' + '%012x' % device_id`.
Midea ids are 6 bytes, so this is always 14 characters, the ISY limit. The
address is derived from the device id rather than the IP, so a unit keeps its
node and its ISY programs across a DHCP change. Verified against the owner's
real id `151732604872862` → `ac8a000003a89e`.

**Temperature units.** msmart works only in Celsius. `temp_units` (`F`/`C`)
controls both reporting and setpoint interpretation. Temperature editors carry
two `<range>` elements (uom 17 and uom 4) and the code sends the matching uom
with each `setDriver`.

**Setpoint precision.** Some ISY firmware sends editor-precision-scaled
integers (`720` meaning `72.0`). The command editor `M_SETPOINT_CMD` uses
`prec="0"` to avoid this, and `cmd_set_temperature` additionally divides by 10
if it receives a value more than twice the legal maximum. The *status* editor
`M_SETPOINT` keeps `prec="1"` so half-degree setpoints display.

**Capability gating.** The owner's unit reports `supports_eco: False`,
`supports_humidity: False` and `target_humidity: 0`. Publishing that `0` as a
real humidity reading would be wrong, so `publish()` checks the `supports_*`
property before writing those drivers, and commands for unsupported features
are refused with a log line rather than sent.

**Display control.** The protocol only offers a *toggle*, so `SETDISPLAY`
compares the requested state with `device.display_on` and only toggles on a
real difference.

**Breeze mode.** The library exposes breeze as three mutually exclusive
booleans (`breeze_away`, `breeze_mild`, `breezeless`); setting any one to
`False` returns the unit to OFF. `GV17` maps a single enum onto them.

**Fan speed.** `CLIFS` holds the preset (20/40/60/80/100/102); `GV2` always
holds the numeric percentage. A custom speed that is not a preset updates only
`GV2` so the preset driver does not show a lie.

**Discovery cadence.** Short poll refreshes every node. Long poll re-broadcasts
only every `Controller.REDISCOVER_EVERY` (12) long polls — about hourly at the
default 300 s — but immediately if any node is not online or a configured
device has no node yet.

**Credential validation.** msmart calls `bytes.fromhex()` on the token and
key, which raises `ValueError` on a typo. `mapping.is_hex()` checks both before
they reach the library, so a mistyped parameter produces a clear PG3 notice
instead of a traceback and a mysteriously offline node. `ac.connect()` also
catches `ValueError` and reports Authentication Failed.

**Device count driver.** `GV0` counts existing nodes, not what the last
broadcast happened to see, so a missed broadcast does not make the count drop.

**Nodes are never auto-deleted.** A device that stops responding keeps its node
and goes to `Offline`, so ISY programs referencing it survive an outage.

## 6. Status

* All 53 offline tests pass.
* **Not yet run against real hardware.** The owner will test on their own units
  between sessions and supply token/key at that time.

## 7. Likely next steps

1. Hardware test: `tools/standalone.py discover`, then `query`, then `control`.
2. Install on the EISY and confirm the profile renders correctly in the Admin
   Console — node names, mode/fan dropdowns, the setpoint slider.
3. Confirm the setpoint command path on real ISY firmware; the scaled-integer
   defence in `cmd_set_temperature` is a precaution and the real behaviour is
   worth confirming in the log.
4. Check whether `energy_stats` / `extended_sensors` return anything on the
   owner's units; if not, consider hiding those drivers.
5. Possible additions if wanted: a node-level "reconnect" command, per-node
   poll intervals, and `ieco` / `cascade` / `out_silent` which the library
   supports but this profile does not expose.

## 8. Reference data from the owner's unit

```
ip 10.1.1.39  port 6444  id 151732604872862  sn 000000P0000000Q1FCDF00D0E1E80000
name net_ac_E1E8  type 0xAC (AIR_CONDITIONER)  online True  supported True

supported_modes        FAN_ONLY, DRY, COOL, HEAT, AUTO
supported_swing_modes  OFF, VERTICAL
supported_fan_speeds   SILENT, LOW, MEDIUM, HIGH, AUTO, MAX
supports_custom_fan_speed  True
supports_eco               False
supports_turbo             True
supports_freeze_protection False
supports_display_control   True
supports_filter_reminder   True

state: power False, mode COOL, fan MAX, swing OFF, target 20.5C,
       indoor 22.5C, outdoor 23.0C, indoor_humidity None, target_humidity 0,
       display_on True, fahrenheit True, filter_alert True,
       energy counters all None
```

This is the basis of `FakeDevice` in `tests/test_offline.py`.
