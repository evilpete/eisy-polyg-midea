# Midea AC Node Server for EISY / Polisy (Polyglot v3)

Monitor and control Midea (and associated brand) smart air conditioners from a
Universal Devices EISY or Polisy, over the local network.

Built on [msmart-ng](https://github.com/mill1000/midea-msmart) by mill1000.
All runtime communication is local — the Midea cloud is never contacted by this
node server.

## Supported hardware

Air conditioners (Midea device type `0xAC`) paired with any of these apps:

* Midea Air (`com.midea.aircondition.obm`)
* NetHome Plus (`com.midea.aircondition`)
* SmartHome / MSmartHome (`com.midea.ai.overseas`)
* Artic King (`com.arcticking.ac`)
* Toshiba AC NA (`com.midea.toshiba`)
* 美的美居 (`com.midea.ai.appliances`)

Protocol V1, V2 and V3 units are supported. V3 units additionally need a token
and key, which you supply once in the configuration.

## Installation

See [INSTALL.md](INSTALL.md) for the full walkthrough. In short: install from
the PG3x Plugin Store, then put one entry per air conditioner in **Plugin
Management → Custom Parameters**, which is edited as JSON:

| Key | Value |
| --- | --- |
| `temp_units` | `F` |
| `Bedroom` | `ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>` |

Not the Device Configuration form — that is for `devd` hardware such as a USB
dongle, not network devices.

Configuration options are documented on the plugin's configuration page, and in
[POLYGLOT_CONFIG.md](POLYGLOT_CONFIG.md).

### Getting a token and key for a V3 unit

On any machine on the same network:

```shell
pip install msmart-ng
msmart-ng discover
```

The output lists each unit's `ip`, `id`, `token` and `key`. Save them — they
remain valid until the unit is re-paired in the phone app. Add them to a custom
parameter:

```
Bedroom = ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>
```

## Nodes

### Controller

| Driver | Meaning |
| --- | --- |
| `ST` | Node server state |
| `GV0` | Devices configured |
| `GV1` | Devices online |

Commands: re-discover devices, query all, update profile, clear notices.

### Air Conditioner

| Driver | Meaning | Writable |
| --- | --- | --- |
| `ST` | Power | yes (`DON` / `DOF`) |
| `GV0` | Connection state | no |
| `CLITEMP` | Indoor temperature | no |
| `GV1` | Outdoor temperature | no |
| `CLISPC` | Target temperature | yes (`SETTEMP`) |
| `CLIMD` | Mode — auto / cool / dry / heat / fan only / smart dry | yes (`SETMODE`) |
| `CLIFS` | Fan speed preset — silent / low / medium / high / max / auto | yes (`SETFAN`) |
| `GV2` | Fan speed percent (units with custom fan speed) | yes |
| `CLIHUM` | Indoor humidity | no |
| `GV3` | Target humidity | yes |
| `GV4` | Swing mode | yes |
| `GV5` / `GV6` | Vertical / horizontal louver position — `vertical_louver` / `horizontal_louver` | yes |
| `GV7` | Eco mode | yes |
| `GV8` | Turbo mode | yes |
| `GV9` | Sleep mode | yes |
| `GV10` | Freeze protection | yes |
| `GV11` | Display / LED | yes |
| `GV12` | Purifier | yes |
| `GV13` | Follow Me | yes |
| `GV14` | Filter alert | no |
| `GV15` | Self clean active | no (`SELFCLEAN` starts a cycle) |
| `GV16` | Error code | no |
| `GV17` | Breeze mode | yes |
| `GV18` | Fresh air fan speed | yes |
| `GV19` | Power gear | yes |
| `GV20` | Aux heat | yes |
| `GV21` / `GV22` | Total energy / power usage | no |
| `GV23` | Beep on command | yes |
| `GV24` | Defrost active | no |
| `GV25` | Compressor frequency | no |
| `GV26` / `GV27` | Indoor / outdoor coil temperature | no |

Capabilities are read from each unit at startup and are enforced in both
directions. A feature the unit does not have is not reported as a reading, and
a command for it is refused with a log line rather than sent — which matters
more than it sounds: the library only warns and carries on, leaving the
rejected value set on the device so it is re-sent with every later command.

By default the rows for those features, and the controls that set them, are
left off the node entirely, applied as soon as the unit connects. Reopen the
Admin Console to see it. `auto_hide_unsupported = false` keeps every row.

A node's rows come from the ISY profile rather than from what the plugin
reports, so a reading that is simply left unreported still appears as an empty
row. Use the `hide_drivers` setting, or a per-device `hide` field, to drop the
ones you do not want; both take driver ids (`GV6`) or the friendly names above
with spaces replaced by underscores (`horizontal_louver`).

To make that work the plugin generates an extra node definition for each
distinct set of hidden readings and sends it to the ISY at startup. The
definition shipped in `profile/` is the template and is never modified;
generated variants sit alongside it and are rebuilt on every start, so they
cannot go stale. See `nodes/profilegen.py`.

Temperatures are reported in whatever `temp_units` is set to; the library works
in Celsius internally and the node server converts in both directions.

## Where credentials live

**On the EISY**, in the plugin's PG3 Custom Parameters. PG3 stores them in its
own database; nothing is written into this repository.

**For `tools/standalone.py`**, in a config file holding the same key/value
pairs, as JSON or as `key = value` lines, so an entry can be moved between the
file and PG3 unchanged:

```json
{
    "temp_units": "F",
    "Bedroom": "ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>"
}
```

`./tools/standalone.py discover --save` writes this file for you, with the
token and key left blank to fill in.

Searched in order: `--config`, `$MIDEA_CONFIG`, `./devices.json`,
`./devices.conf`, `~/.config/midea-poly/devices.json`,
`~/.config/midea-poly/devices.conf`, `~/.midea-devices.conf`. A `key = value`
file is accepted as well as JSON. The tool warns if the file is readable by
other users, and `.gitignore` excludes it so credentials are not committed by
accident.

`$MIDEA_TOKEN` and `$MIDEA_KEY` are used if nothing else supplies them, so
credentials need never appear in shell history.

## Development

The plugin can be exercised without an EISY or an air conditioner:

```shell
pip install msmart-ng
python3 tests/run.py
```

Against real hardware, with no Polyglot running:

```shell
./tools/standalone.py discover --save        # find units, write devices.json
./tools/standalone.py devices                # what is configured
./tools/standalone.py query   --device Bedroom
./tools/standalone.py raw     --device Bedroom
./tools/standalone.py caps    --device Bedroom   # report + what it implies
./tools/standalone.py watch   --device Bedroom -n 10 -i 15
./tools/standalone.py control --device Bedroom --cmd SETTEMP --value 72
```

`query` prints the ISY drivers with their decoded labels, so it shows exactly
what the Admin Console would show; `raw` prints the library's own view. Add
`--debug` for full protocol logging.

`tests/test_offline.py` drives the controller and node classes against a fake
device and a stub `udi_interface`. `tests/test_profile.py` checks that the ISY
profile, the NLS file and the Python driver/command tables all agree.

## Publishing

Values for the PG3 Developer Tools submission form are in
[PUBLISHING.md](PUBLISHING.md).

## License

MIT. See [LICENSE](LICENSE).
