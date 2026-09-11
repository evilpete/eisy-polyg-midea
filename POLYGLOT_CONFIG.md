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

Any custom parameter whose key is *not* one of the settings listed further down
is treated as a device. The key becomes the node name; the value describes how
to reach the unit.

| Key | Value |
| --- | --- |
| `Bedroom` | `ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>` |
| `Den` | `10.1.1.40` |

Fields inside the value, separated by `;` (or `,`):

| Field | Required | Notes |
| --- | --- | --- |
| `ip` | yes | IP address or hostname of the indoor unit. `host` is accepted as a synonym. |
| `id` | recommended | Midea device id. If omitted, the node server probes `ip` at startup to learn it. |
| `token` | V3 only | Hex token from `msmart-ng discover`. |
| `key` | V3 only | Hex key from `msmart-ng discover`. Must be given together with `token`. |
| `port` | no | Defaults to `6444`. |
| `name` | no | Overrides the node name; otherwise the parameter key is used. |

A value with no `=` in it is treated as a bare IP address.

The `token` and `key` must be hexadecimal exactly as `msmart-ng discover`
printed them; a typo is reported here as a notice rather than leaving the node
mysteriously offline.

Configured devices are always probed directly, so they work whether or not
broadcast discovery is enabled, and a hand-entered token/key is never
overwritten by discovery.

Assign your units **static IP addresses or DHCP reservations**. Node addresses
are derived from the Midea device id, so a unit keeps its node and its ISY
programs even if its IP changes — but the node server has to find it first.

---

### Settings

| Parameter | Default | Description |
| --- | --- | --- |
| `temp_units` | `F` | `F` or `C`. Controls how all temperatures are reported and how setpoints are interpreted. |
| `discovery` | `true` | Broadcast for devices at startup and on each long poll. Set to `false` to use only the devices you listed. |
| `discovery_timeout` | `5` | Seconds to wait for discovery responses. Raise it on a busy or slow network. |
| `discovery_interface` | *(unset)* | Bind discovery to a specific local interface address. Useful on a multi-homed EISY. |
| `beep` | `false` | Whether the indoor unit beeps when the node server sends a command. Can also be overridden per node from the Admin Console. |
| `energy_stats` | `false` | Request energy and power counters on every poll. Only some units answer. |
| `extended_sensors` | `false` | Request the optional data groups: coil temperatures, compressor frequency, defrost state, louver angles. Adds several extra round trips per poll. |
| `connection_lifetime` | *(unset)* | Seconds after which the TCP connection to a device is recycled. |

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
