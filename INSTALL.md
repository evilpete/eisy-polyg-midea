# Installing on an EISY / Polisy

## 1. Install the plugin

PG3/PG3x only runs on an EISY or Polisy.

**Close the IoX Admin Console first.** It reads plugin nodes and profiles only
when it loads, so installing with it open leads to nodes that look wrong until
you restart it.

Open the PG3x web UI on your EISY, go to the **Plugin Store**, and install.

While this plugin is not in the public store, publish it to your **Local**
plugin store first — that store lives only in your own PG3 database. Go to
**Developer Tools → Add New Plugin**, fill in the form using the values in
[PUBLISHING.md](PUBLISHING.md), select the Local store, and submit. It then
appears in the Plugin Store page for you to install.

Developer Tools requires a vetted UDI developer account, a login to the PG3x
instance on the EISY itself, and that EISY registered to your ISY Portal
account.

PG3 clones the plugin into

```
/var/polyglot/pg3/ns/<ISY-uuid>_<slot>/
```

and creates a Python virtual environment there, into which `requirements.txt`
(`udi_interface`, `msmart-ng`) is installed by `install.sh`.

For fast iteration you can edit files in that directory directly and restart
the plugin from the PG3 UI — no reinstall needed. A Samba share pointing at
`/var/polyglot/pg3/ns` makes that comfortable from a desktop.

## 2. Enter your device credentials

Everything goes in **Plugin Management → Custom Parameters**, as key/value
pairs. Ignore the *Device Configuration* section — that is for `devd` style
hardware such as a USB dongle, not for network devices.

After a fresh install the parameters are seeded with `temp_units`, `discovery`
and an `example_device` template. Replace the template with one parameter per
air conditioner. **The key becomes the node name:**

| Key | Value |
| --- | --- |
| `temp_units` | `F` |
| `discovery` | `true` |
| `Bedroom` | `ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>` |
| `Den` | `ip=10.1.1.40; id=151732604872863; token=<TOKEN>; key=<KEY>` |

Where the page is edited as a JSON document, the same thing is:

```json
{
    "temp_units": "F",
    "discovery": "true",
    "Bedroom": "ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>",
    "Den": "ip=10.1.1.40; id=151732604872863; token=<TOKEN>; key=<KEY>"
}
```

Click **Save**, then restart the plugin.

`example_device` is ignored while it still contains the `<PLACEHOLDER>` text,
so leaving it in place does nothing harmful — but deleting it is tidier.

If your PG3 version accepts structured JSON, a nested object per device and a
`devices` collection also work; see
[POLYGLOT_CONFIG.md](POLYGLOT_CONFIG.md#richer-json-where-the-ui-allows-it).

### Getting the id, token and key

On any machine on the same network:

```shell
pip install msmart-ng
msmart-ng discover
```

It prints `ip`, `id`, `token` and `key` for each unit. Copy the token and key
exactly — they are hex, and a typo is reported back as a notice on the PG3
page rather than leaving the node silently offline.

V1 and V2 units need no token or key; V3 units do. If you leave them out, the
plugin tells you which device needs them and shows the parameter to paste.

### Checking a parameter before you paste it

`tools/standalone.py` parses parameters with the plugin's own code, so you can
validate one anywhere, without an EISY:

```shell
# a single entry, as a string
./tools/standalone.py params 'Bedroom=ip=10.1.1.39; id=151732604872862; token=AABB; key=CCDD'

# or a whole JSON blob, exactly as you would paste it into the UI
./tools/standalone.py devices --config devices.json
```

`tools/standalone.py discover --save` writes a `devices.json` in the same
shape the Custom Parameters page expects, so you can fill in the tokens and
paste the file straight into PG3.

## 3. Confirm it worked

* The controller node's **Devices Configured** and **Devices Online** drivers
  should both be non-zero.
* Each air conditioner node's **Connection** driver should read `Online`.
  `Authentication Failed` means the token/key are wrong or the unit was
  re-paired in the phone app since they were issued.
* Anything the plugin wants you to fix appears as a notice on the plugin page.

Reopen the Admin Console once the nodes exist.

## Notes

* Midea units accept only **one LAN connection at a time** — close the phone
  app while testing.
* Discovery is a UDP broadcast and does not cross subnets or VLANs. Across a
  VLAN, list each device explicitly by IP.
* Give the units static IPs or DHCP reservations. Node addresses derive from
  the Midea device id, so a node survives an IP change, but the plugin still
  has to find the unit.
