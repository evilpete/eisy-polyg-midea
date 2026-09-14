## Midea Air Conditioner Node Server

Monitors and controls Midea (and associated brand) smart air conditioners over
your local network using the
[msmart-ng](https://github.com/mill1000/midea-msmart) library. No cloud
connection is used at runtime.

Works with units paired to Midea Air, NetHome Plus, SmartHome/MSmartHome,
Artic King, Toshiba AC NA and 美的美居.

---

### Quick start

1. Leave everything at its default and restart the node server. It broadcasts
   on the LAN and creates a node for each air conditioner it finds.
2. Check the node server log. **V1/V2 devices work immediately.** **V3 devices
   need a token and key** — the log and a notice will say so.
3. Get the token and key for a V3 device by running `msmart-ng discover` on any
   machine on the same network (the tool logs in to the Midea cloud once to
   fetch them), then add them here as described below.

---

### Device parameters

Everything is configured on the **Custom Parameters** page, as key/value pairs.
This plugin does not use the *Device Configuration* form — that is for `devd`
style hardware such as a USB dongle, not for network devices.

One parameter per air conditioner. **The key becomes the node name**, and the
value holds the connection details:

<table>
    <tr>
        <td>Key</td>
        <td>Value</td>
    </tr>
    <tr>
        <td>`Bedroom`</td>
        <td>`ip=10.0.0.39; id=151732604872862; token=&lt;TOKEN&gt;; key=&lt;KEY&gt;`</td>
    </tr>
    <tr>
        <td>`Den`</td>
        <td>`ip=10.0.0.40; id=151732604872863; token=&lt;TOKEN&gt;; key=&lt;KEY&gt;`</td>
    </tr>
</table>

Where the page is edited as a JSON document, that is the same thing written as:

```json
{
    "temp_units": "F",
    "discovery": "true",
    "Bedroom": "ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>",
    "Den": "ip=10.1.1.40; id=151732604873863; token=<TOKEN>; key=<KEY>"
}
```

A fresh install seeds an `example_device` parameter showing this shape. It is
ignored until you replace the `<PLACEHOLDER>` text, so either fill it in or
delete it.

Fields inside the value, separated by `;` (or `,`):

<table>
    <tr>
        <td>Field</td>
        <td>Required</td>
        <td>Notes</td>
    </tr>
    <tr>
        <td>`ip`</td>
        <td>yes</td>
        <td>IP address or hostname of the indoor unit. `host` is accepted as a synonym.</td>
    </tr>
    <tr>
        <td>`id`</td>
        <td>recommended</td>
        <td>Midea device id. If omitted, the node server probes `ip` at startup to learn it.</td>
    </tr>
    <tr>
        <td>`token`</td>
        <td>V3 only</td>
        <td>Hex token from `msmart-ng discover`.</td>
    </tr>
    <tr>
        <td>`key`</td>
        <td>V3 only</td>
        <td>Hex key from `msmart-ng discover`. Must be given together with `token`.</td>
    </tr>
    <tr>
        <td>`port`</td>
        <td>no</td>
        <td>Defaults to `6444`.</td>
    </tr>
    <tr>
        <td>`name`</td>
        <td>no</td>
        <td>Overrides the node name; otherwise the key is used.</td>
    </tr>
    <tr>
        <td>`hide`</td>
        <td>no</td>
        <td>Readings to leave off this node, in addition to `hide_drivers`.</td>
    </tr>
</table>


Fields are separated by `;`. A comma is *not* a field separator, so it can be
used inside a value — which is what `hide` needs.

A value with no `=` in it is treated as a bare IP address, so `Den` = `10.1.1.40`
is valid shorthand.

#### Readings a unit does not have

Each unit reports what it is capable of, and by default the readings it has no
hardware for are left off its node, along with the controls that set them. Your
unit reporting no eco mode means no Eco Mode row and no *Set Eco Mode* command.

The profile has to be built before any unit is contacted, so a newly learned
capability set applies on the **next** start: the plugin posts a notice when it
learns something new, and after a restart the rows are gone. Set
`auto_hide_unsupported` to `false` to keep every row regardless.

Commands are refused on capability grounds whether or not the row is hidden, so
an ISY program asking for something a unit cannot do is logged and ignored
rather than sent.

#### Hiding readings by hand

Every node carries the full set of readings, because the ISY profile is fixed
at install time and cannot vary per device. A unit with no horizontal louver
still shows a Horizontal Louver row, sitting at its default.

`hide_drivers` drops readings from every node, and a `hide` field drops them
from one:

<table>
    <tr>
        <td>Key</td>
        <td>Value</td>
    </tr>
    <tr>
        <td>`hide_drivers`</td>
        <td>`horizontal_louver, total_energy, power_usage`</td>
    </tr>
    <tr>
        <td>`Bedroom`</td>
        <td>`ip=10.1.1.39; id=151732604872862; hide=fresh_air,aux_heat`</td>
    </tr>
</table>

Either driver ids (`GV6`) or friendly names (`horizontal_louver`) are accepted.
The full list of names is in the driver table in
[README.md](https://github.com/evilpete/eisy-polyg-midea/blob/main/README.md).

The row is genuinely removed, not just left blank, and the control that sets it
goes with it — hiding `horizontal_louver` also removes *Set Horizontal Louver*
from the command list. Hidden readings are never polled either.

**After changing this, restart the plugin and then close and reopen the Admin
Console.** The plugin generates a node definition for each distinct set of
hidden readings and sends it to the ISY at startup, and the Admin Console reads
node definitions only when it loads.

The `token` and `key` must be hexadecimal exactly as `msmart-ng discover`
printed them; a typo is reported here as a notice rather than leaving the node
mysteriously offline.


### Settings

<table>
    <tr>
        <td>Parameter</td>
        <td>Default</td>
        <td>Description</td>
    </tr>
    <tr>
        <td>`temp_units`</td>
        <td>`F`</td>
        <td>`F` or `C`. Controls how all temperatures are reported and how setpoints are interpreted.</td>
    </tr>
    <tr>
        <td>`discovery`</td>
        <td>`true`</td>
        <td>Broadcast for devices at startup and on each long poll. Set to `false` to use only the devices you listed.</td>
    </tr>
    <tr>
        <td>`discovery_timeout`</td>
        <td>`5`</td>
        <td>Seconds to wait for discovery responses. Raise it on a busy or slow network.</td>
    </tr>
    <tr>
        <td>`discovery_interface`</td>
        <td>*(unset)*</td>
        <td>Bind discovery to a specific local interface address. Useful on a multi-homed EISY.</td>
    </tr>
    <tr>
        <td>`beep`</td>
        <td>`false`</td>
        <td>Whether the indoor unit beeps when the node server sends a command. Can also be overridden per node from the Admin Console.</td>
    </tr>
    <tr>
        <td>`energy_stats`</td>
        <td>`false`</td>
        <td>Request energy and power counters on every poll. Only some units answer.</td>
    </tr>
    <tr>
        <td>`extended_sensors`</td>
        <td>`false`</td>
        <td>Request the optional data groups: coil temperatures, compressor frequency, defrost state, louver angles. Adds several extra round trips per poll.</td>
    </tr>
    <tr>
        <td>`connection_lifetime`</td>
        <td>*(unset)*</td>
        <td>Seconds after which the TCP connection to a device is recycled.</td>
    </tr>
    <tr>
        <td>`hide_drivers`</td>
        <td>*(unset)*</td>
        <td>Comma separated list of readings to leave off every node. See below.</td>
    </tr>
    <tr>
        <td>`auto_hide_unsupported`</td>
        <td>`true`</td>
        <td>Leave off readings a unit reports it has no hardware for. Takes effect on the restart after the unit first connects.</td>
    </tr>
</table>


---

### Polling

* **Short poll** (default 60 s) refreshes the state of every device.
* **Long poll** (default 300 s) re-runs discovery, which recovers units that
  were offline, rebooted or moved.

Increase the short poll if you have many units or see timeouts in the log.

---

### Troubleshooting

**"Authentication Failed" on a node** — the token/key are wrong, belong to a
different unit, or the unit was re-paired in the phone app (which invalidates
them). Re-run `msmart-ng discover` and update the parameter.

**A node stays "Offline"** — the unit is unreachable. Confirm with
`msmart-ng query <ip>` from another machine on the same subnet. Midea units
accept only one LAN connection at a time, so close the phone app while testing.

**Nothing is discovered** — discovery is a UDP broadcast and does not cross
subnets or VLANs. List the devices explicitly by IP instead, or set
`discovery_interface`.

**"Unsupported Device"** — the unit answered but is not an air conditioner the
library supports. Only types `0xAC` and `0xCC` are; this node server handles
`0xAC`.
