#!/usr/bin/env python3
"""
Stand-alone driver for the Midea node server.

Runs the plugin's real controller and node classes against real hardware with
no Polyglot, no ISY and no EISY involved, and prints exactly which ISY drivers
would be set. Use it to debug a device before or instead of installing the
plugin.

Connection details live in a config file written in exactly the same syntax as
PG3 Custom Parameters, so whatever works here can be pasted straight into PG3:

    # devices.conf
    temp_units = F
    Bedroom = ip=10.1.1.39; id=151732604872862; token=<TOKEN>; key=<KEY>
    Den     = ip=10.1.1.40; id=151732604872863; token=<TOKEN>; key=<KEY>

Searched in order: --config, $MIDEA_CONFIG, ./devices.conf,
~/.config/midea-poly/devices.conf, ~/.midea-devices.conf.

    ./tools/standalone.py devices                    # what is in the file
    ./tools/standalone.py discover --save            # append what it finds
    ./tools/standalone.py query   --device Bedroom
    ./tools/standalone.py watch   --device Bedroom -n 10 -i 15
    ./tools/standalone.py control --device Bedroom --cmd SETTEMP --value 72
    ./tools/standalone.py raw     --device Bedroom
    ./tools/standalone.py caps    --device Bedroom

Everything can also be given on the command line, which overrides the file:

    ./tools/standalone.py query 10.1.1.39 --id 151732604872862 \
        --token <TOKEN> --key <KEY>
    ./tools/standalone.py query --param 'ip=10.1.1.39; id=...; token=...; key=...'

$MIDEA_TOKEN and $MIDEA_KEY are used if neither the file nor the command line
supplies them, so credentials need never appear in shell history.
"""

import argparse
import json
import logging
import os
import stat
import sys
import time
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The stub udi_interface stands in for the real one, which only exists on a
# Polyglot host. It must precede the project root on the path.
sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
sys.path.insert(1, ROOT)

import udi_interface  # noqa: E402

from nodes.ac import MideaACNode  # noqa: E402
from nodes.aioloop import RUNNER  # noqa: E402
from nodes.controller import Controller  # noqa: E402
from nodes.mapping import address_for, is_hex, safe_name  # noqa: E402

PROFILE = os.path.join(ROOT, 'profile')

CONFIG_CANDIDATES = (
    os.path.join(os.getcwd(), 'devices.json'),
    os.path.join(os.getcwd(), 'devices.conf'),
    os.path.expanduser('~/.config/midea-poly/devices.json'),
    os.path.expanduser('~/.config/midea-poly/devices.conf'),
    os.path.expanduser('~/.midea-devices.conf'),
)

# JSON by default: the Plugin Management page edits parameters as JSON,
# so a file in this shape can be pasted straight into the PG3 UI.
DEFAULT_SAVE_PATH = os.path.expanduser('~/.config/midea-poly/devices.json')


# ------------------------------------------------------------- config file

def find_config(explicit=None):
    """Locate the config file. An explicit path that is missing is an error."""
    if explicit:
        if not os.path.exists(explicit):
            raise SystemExit(f'No such config file: {explicit}')
        return explicit

    from_env = os.environ.get('MIDEA_CONFIG')
    if from_env:
        if not os.path.exists(from_env):
            raise SystemExit(f'$MIDEA_CONFIG points at a missing file: '
                             f'{from_env}')
        return from_env

    for path in CONFIG_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def looks_like_json(text):
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('//'):
            continue
        return line.startswith('{')
    return False


def read_config(path):
    """Read a config file into the same dict shape PG3 hands the plugin.

    Accepts either JSON, matching what the Plugin Management page edits, or
    simple `key = value` lines. Both end up as the same dict, so an entry can
    be moved between the file and the PG3 UI unchanged.
    """
    params = {}
    if not path:
        return params

    with open(path) as handle:
        text = handle.read()

    if looks_like_json(text):
        try:
            params = json.loads(text)
        except ValueError as ex:
            raise SystemExit(f'{path}: not valid JSON: {ex}')
        if not isinstance(params, dict):
            raise SystemExit(f'{path}: expected a JSON object at the top level')
    else:
        for number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#') or line.startswith(';'):
                continue
            if '=' not in line:
                print(f'{path}:{number}: ignoring line with no "="')
                continue
            key, _, value = line.partition('=')
            params[key.strip()] = value.strip()

    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f'Warning: {path} is readable by other users. It holds device '
              f'credentials; consider: chmod 600 {path}')

    return params


def known_device_ids(params):
    """Collect the ids already present, in whichever shape they are written."""
    ids = set()

    def scan(value):
        if isinstance(value, dict):
            for field, field_value in value.items():
                if str(field).strip().lower() == 'id':
                    ids.add(str(field_value).strip())
                elif isinstance(field_value, (dict, list)):
                    scan(field_value)
        elif isinstance(value, list):
            for item in value:
                scan(item)
        else:
            for part in str(value).replace(',', ';').split(';'):
                field, _, field_value = part.partition('=')
                if field.strip().lower() == 'id':
                    ids.add(field_value.strip())

    for value in params.values():
        scan(value)
    return ids


def append_to_config(path, entries):
    """Add discovered devices to the config file, skipping known ids."""
    existing = read_config(path) if os.path.exists(path) else {}
    is_json = (os.path.exists(path)
               and looks_like_json(open(path).read())) or path.endswith('.json')
    known_ids = known_device_ids(existing)
    known_keys = set(existing)

    if is_json:
        return append_to_json_config(path, existing, entries,
                                     known_ids, known_keys)

    new_lines = []
    for info in entries:
        if str(info['id']) in known_ids:
            print(f'  {info["name"]} ({info["ip"]}) is already in the file')
            continue

        key = unique_key(info['name'], known_keys)

        if info.get('version') == 3:
            new_lines.append(
                '# V3 device: fill in token and key from `msmart-ng discover`')
            new_lines.append(
                f'{key} = ip={info["ip"]}; id={info["id"]}; token=; key=')
        else:
            new_lines.append(f'{key} = ip={info["ip"]}; id={info["id"]}')
        print(f'  added {key} -> {info["ip"]}')

    if not new_lines:
        print('Nothing new to add.')
        return

    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    is_new = not os.path.exists(path)

    with open(path, 'a') as handle:
        if is_new:
            handle.write('# Midea node server device list.\n'
                         '# Same syntax as PG3 Custom Parameters.\n'
                         'temp_units = F\n')
        handle.write('\n')
        handle.write('\n'.join(new_lines))
        handle.write('\n')

    if is_new:
        os.chmod(path, 0o600)

    print(f'Wrote {path}')


def unique_key(name, known_keys):
    base = safe_name(name).replace(' ', '_')
    key = base
    suffix = 2
    while key in known_keys:
        key = f'{base}_{suffix}'
        suffix += 1
    known_keys.add(key)
    return key


def append_to_json_config(path, existing, entries, known_ids, known_keys):
    """Merge discovered devices into a JSON config file."""
    added = 0
    for info in entries:
        if str(info['id']) in known_ids:
            print(f'  {info["name"]} ({info["ip"]}) is already in the file')
            continue

        key = unique_key(info['name'], known_keys)
        entry = {'ip': info['ip'], 'id': info['id']}
        if info.get('version') == 3:
            # Left empty on purpose: fill in from `msmart-ng discover`.
            entry['token'] = ''
            entry['key'] = ''
        existing[key] = entry
        added += 1
        print(f'  added {key} -> {info["ip"]}')

    if not added:
        print('Nothing new to add.')
        return

    existing.setdefault('temp_units', 'F')

    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, 'w') as handle:
        json.dump(existing, handle, indent=4)
        handle.write('\n')

    if is_new:
        os.chmod(path, 0o600)

    print(f'Wrote {path}')


# ------------------------------------------------------------------ profile

def load_profile():
    """Read the NLS and editor files so drivers can be printed with labels."""
    nls = {}
    with open(os.path.join(PROFILE, 'nls', 'en_us.txt')) as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                nls[key.strip()] = value.strip()

    editors = ET.parse(
        os.path.join(PROFILE, 'editor', 'editors.xml')).getroot()
    index_editors = {}
    for editor in editors.findall('editor'):
        for rng in editor.findall('range'):
            if rng.get('nls'):
                index_editors[editor.get('id')] = rng.get('nls')

    nodedefs = ET.parse(
        os.path.join(PROFILE, 'nodedef', 'nodedefs.xml')).getroot()
    driver_editor = {}
    for nodedef in nodedefs.findall('nodeDef'):
        if nodedef.get('id') != 'MIDEAAC':
            continue
        for st in nodedef.iter('st'):
            driver_editor[st.get('id')] = st.get('editor')

    return nls, index_editors, driver_editor


def print_drivers(node):
    """Print the node's drivers the way the Admin Console would show them."""
    nls, index_editors, driver_editor = load_profile()

    print(f'\n{node.name}  [{node.address}]  {node.config.get("ip")}')
    print('-' * 68)

    for driver in [d['driver'] for d in MideaACNode.drivers]:
        value = node.driver_values.get(driver)
        label = nls.get(f'ST-MIDEAAC-{driver}-NAME', driver)

        prefix = index_editors.get(driver_editor.get(driver))
        shown = value
        if prefix is not None:
            try:
                shown = nls.get(f'{prefix}-{int(value)}', value)
            except (TypeError, ValueError):
                pass

        uom = node.driver_uoms.get(driver)
        print(f'  {driver:<8} {label:<24} {str(shown):<18} (uom {uom})')
    print()


# --------------------------------------------------------------- scaffolding

def make_controller(args):
    """Build a controller seeded from the config file, then CLI overrides."""
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')

    path = find_config(getattr(args, 'config', None))
    params = read_config(path)
    if params:
        controller.parameter_handler(params)

    # Command line wins over the file.
    units = getattr(args, 'units', None)
    if units:
        controller.fahrenheit = units.upper().startswith('F')
    if getattr(args, 'beep', False):
        controller.beep = True
    if getattr(args, 'energy', False):
        controller.energy_stats = True
    if getattr(args, 'extended', False):
        controller.extended_sensors = True
    if getattr(args, 'timeout', None):
        controller.discovery_timeout = args.timeout
    if getattr(args, 'interface', None):
        controller.discovery_interface = args.interface

    return controller, path


def device_config(controller, path, args):
    """Work out which device to talk to, and how."""
    if args.param:
        config = controller._parse_device_param('standalone', args.param)
        if config is None:
            print('That parameter value is not valid. See the messages above.')
        return config

    config = None
    configured = controller.configured

    if args.device:
        config = configured.get(args.device)
        if config is None:
            print(f'No device named "{args.device}" in '
                  f'{path or "any config file"}.')
            if configured:
                print(f'Known: {", ".join(sorted(configured))}')
            return None
        config = dict(config)

    elif args.host:
        # A host that matches a config entry picks up that entry's credentials.
        for entry in configured.values():
            if entry['ip'] == args.host:
                config = dict(entry)
                break
        if config is None:
            config = {
                'address': None, 'param_key': 'standalone',
                'ip': args.host, 'port': 6444, 'id': None,
                'token': None, 'key': None, 'version': None,
                'name': args.host,
            }

    elif len(configured) == 1:
        config = dict(next(iter(configured.values())))
        print(f'Using the only device in {path}: {config["name"]}')

    elif configured:
        print(f'{path} has several devices. Choose one with --device NAME:')
        for name, entry in sorted(configured.items()):
            print(f'  {name:<20} {entry["ip"]}')
        return None

    else:
        print('No device given and no config file found.\n'
              'Give a host, use --param, or create a config file '
              '(see "discover --save").')
        return None

    # Individual flags override whatever came from the file.
    for flag, field in (('id', 'id'), ('token', 'token'), ('key', 'key'),
                        ('port', 'port'), ('name', 'name')):
        value = getattr(args, flag, None)
        if value is not None:
            config[field] = value

    # Last resort for credentials, so they need not be in shell history.
    config['token'] = config.get('token') or os.environ.get('MIDEA_TOKEN')
    config['key'] = config.get('key') or os.environ.get('MIDEA_KEY')

    if bool(config.get('token')) != bool(config.get('key')):
        print('A token and a key must be given together.')
        return None

    for field in ('token', 'key'):
        value = config.get(field)
        if value is not None and not is_hex(value):
            print(f'The {field} is not hexadecimal. Copy it exactly as '
                  f'"msmart-ng discover" printed it.')
            return None

    config.setdefault('port', 6444)
    if config.get('token') and config.get('key') and not config.get('version'):
        config['version'] = 3

    return config


def build(args):
    """Build a controller and one node, the same way the plugin does."""
    controller, path = make_controller(args)
    RUNNER.start()

    config = device_config(controller, path, args)
    if config is None:
        return controller, None

    if config.get('id') is None:
        print(f'No id given; probing {config["ip"]} ...')
        info = controller._probe(config['ip'])
        if info is None:
            print(f'Could not reach {config["ip"]}')
            return controller, None
        config['id'] = info['id']
        config['version'] = config.get('version') or info['version']
        config['port'] = info['port']
        print(f'Found id={config["id"]} version={config["version"]}')

    if config.get('version') == 3 and not (config.get('token')
                                           and config.get('key')):
        print(f'\n{config["ip"]} is a V3 device and needs a token and key.\n'
              f'Run "msmart-ng discover" to fetch them, then add them to your '
              f'config file:\n'
              f'  {config.get("name")} = ip={config["ip"]}; '
              f'id={config["id"]}; token=<TOKEN>; key=<KEY>\n')

    node = MideaACNode(controller.poly, 'controller',
                       address_for(config['id']),
                       config.get('name') or 'Midea AC', config, controller)
    controller.poly.addNode(node)
    return controller, node


def connect(node):
    if not node.connect():
        print('Connection failed. Run with --debug for the full reason.')
        return False
    return True


# -------------------------------------------------------------- subcommands

def cmd_devices(args):
    controller, path = make_controller(args)

    if path is None:
        print('No config file found. Looked for:')
        for candidate in CONFIG_CANDIDATES:
            print(f'  {candidate}')
        print('\nCreate one with "discover --save", or write it by hand:\n')
        print('  temp_units = F')
        print('  Bedroom = ip=10.1.1.39; id=151732604872862; '
              'token=<TOKEN>; key=<KEY>')
        return 1

    print(f'Config file: {path}\n')
    print(f'  units               {"F" if controller.fahrenheit else "C"}')
    print(f'  discovery           {controller.discovery_enabled}')
    print(f'  discovery_timeout   {controller.discovery_timeout}')
    print(f'  beep                {controller.beep}')
    print(f'  energy_stats        {controller.energy_stats}')
    print(f'  extended_sensors    {controller.extended_sensors}')

    print('\nDevices:')
    for name, config in sorted(controller.configured.items()):
        creds = 'token+key set' if config['token'] else 'no token/key'
        print(f'  {name:<20} {config["ip"]:<16} id={config["id"]}  {creds}')
    if not controller.configured:
        print('  (none)')

    if controller.Notices:
        print('\nNotices that would appear in PG3:')
        for text in controller.Notices.values():
            print(f'  - {text}')
    return 0


def cmd_discover(args):
    controller, path = make_controller(args)
    RUNNER.start()

    found = controller._broadcast()
    if not found:
        print('No devices found. Discovery is a UDP broadcast and does not '
              'cross subnets or VLANs.')
        return 1

    for info in found:
        print(json.dumps({
            'name': info['name'],
            'ip': info['ip'],
            'port': info['port'],
            'id': info['id'],
            'version': info['version'],
            'sn': info.get('sn'),
            'supported': info.get('supported'),
            'isy_address': info['address'],
        }, indent=2, default=str))
        if info['version'] == 3:
            print('  -> V3 device: needs token and key. Run "msmart-ng '
                  'discover" to fetch them.')

    if args.save:
        target = args.config or path or DEFAULT_SAVE_PATH
        print(f'\nSaving to {target}')
        append_to_config(target, found)

    return 0


def cmd_probe(args):
    controller, _ = make_controller(args)
    RUNNER.start()

    info = controller._probe(args.host)
    if info is None:
        print(f'No response from {args.host}')
        return 1

    print(json.dumps(info, indent=2, default=str))
    return 0


def cmd_query(args):
    _, node = build(args)
    if node is None or not connect(node):
        return 1
    print_drivers(node)
    return 0


def cmd_raw(args):
    """Dump the library's own view of the device, not the ISY's."""
    _, node = build(args)
    if node is None or not connect(node):
        return 1
    print(json.dumps(node.device.to_dict(), indent=2, default=str))
    return 0


def cmd_caps(args):
    _, node = build(args)
    if node is None or not connect(node):
        return 1

    capabilities = node.device.serialize_capabilities()
    print(json.dumps(capabilities, indent=2, default=str))

    # This report is what decides which rows the node gets, so show the
    # conclusion the plugin draws from it.
    from nodes.ac import DRIVER_COMMANDS, unsupported_drivers
    hidden = unsupported_drivers(capabilities)

    nls, _, _ = load_profile()
    print('\nThis unit has no hardware for:')
    for driver in sorted(hidden):
        label = nls.get(f'ST-MIDEAAC-{driver}-NAME', driver)
        command = DRIVER_COMMANDS.get(driver)
        note = f'  (also drops {command})' if command else ''
        print(f'  {driver:<8} {label}{note}')
    if not hidden:
        print('  (nothing - this unit supports everything the plugin knows)')

    print('\nWith auto_hide_unsupported left on, those rows and their '
          'controls\nare left off the node.')
    return 0


def cmd_watch(args):
    _, node = build(args)
    if node is None or not connect(node):
        return 1

    print_drivers(node)
    count = 1
    try:
        while args.count == 0 or count < args.count:
            time.sleep(args.interval)
            count += 1
            print(f'--- poll {count} ---')
            if node.update():
                print_drivers(node)
            else:
                print('Poll failed')
    except KeyboardInterrupt:
        print('\nStopped.')
    return 0


def cmd_control(args):
    _, node = build(args)
    if node is None or not connect(node):
        return 1

    handler = MideaACNode.commands.get(args.cmd.upper())
    if handler is None:
        print(f'Unknown command {args.cmd}. Known commands: '
              f'{", ".join(sorted(MideaACNode.commands))}')
        return 1

    print(f'Sending {args.cmd.upper()}'
          + (f' value={args.value}' if args.value is not None else ''))
    handler(node, {'value': args.value} if args.value is not None else None)

    node.update()
    print_drivers(node)
    return 0


def cmd_params(args):
    """Parse custom parameters given on the command line, no hardware needed."""
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')

    params = {}
    for entry in args.param_entry:
        key, _, value = entry.partition('=')
        params[key.strip()] = value.strip()

    controller.parameter_handler(params)

    print('\nDevices:')
    for name, config in controller.configured.items():
        print(f'  {name}  {json.dumps(config, default=str)}')
    if not controller.configured:
        print('  (none)')

    if controller.Notices:
        print('\nNotices that would appear in PG3:')
        for text in controller.Notices.values():
            print(f'  - {text}')
    return 0


# --------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(
        description='Stand-alone driver for the Midea node server.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--debug', action='store_true',
                        help='full library debug logging')

    def add_common(sub):
        sub.add_argument('--config', help='path to the device config file')
        sub.add_argument('--timeout', type=int, default=None,
                         help='discovery timeout in seconds (default 5)')

    def add_device_args(sub):
        add_common(sub)
        sub.add_argument('host', nargs='?', help='device IP or hostname')
        sub.add_argument('--device',
                         help='name of an entry in the config file')
        sub.add_argument('--id', type=int, help='Midea device id')
        sub.add_argument('--token', help='V3 token (hex)')
        sub.add_argument('--key', help='V3 key (hex)')
        sub.add_argument('--port', type=int, default=None)
        sub.add_argument('--name', help='node name to use')
        sub.add_argument('--param',
                         help='connection details in PG3 custom parameter '
                              'form, e.g. "ip=10.1.1.39; id=...; token=...; '
                              'key=..."')
        sub.add_argument('--units', default=None, choices=['F', 'C', 'f', 'c'])
        sub.add_argument('--beep', action='store_true',
                         help='let the unit beep on each command')
        sub.add_argument('--energy', action='store_true',
                         help='request energy counters')
        sub.add_argument('--extended', action='store_true',
                         help='request coil temps, compressor and defrost data')

    subs = parser.add_subparsers(dest='command', required=True)

    sub = subs.add_parser('devices', help='show the configured devices')
    add_common(sub)
    sub.set_defaults(func=cmd_devices)

    sub = subs.add_parser('discover', help='broadcast for devices')
    add_common(sub)
    sub.add_argument('--interface', help='local interface address to bind')
    sub.add_argument('--save', action='store_true',
                     help='append what is found to the config file')
    sub.set_defaults(func=cmd_discover)

    sub = subs.add_parser('probe', help='unicast discovery of one host')
    add_common(sub)
    sub.add_argument('host')
    sub.set_defaults(func=cmd_probe)

    sub = subs.add_parser('query', help='show the ISY drivers for a device')
    add_device_args(sub)
    sub.set_defaults(func=cmd_query)

    sub = subs.add_parser('raw', help="dump the library's device state")
    add_device_args(sub)
    sub.set_defaults(func=cmd_raw)

    sub = subs.add_parser('caps', help='dump device capabilities')
    add_device_args(sub)
    sub.set_defaults(func=cmd_caps)

    sub = subs.add_parser('watch', help='poll a device repeatedly')
    add_device_args(sub)
    sub.add_argument('-n', '--count', type=int, default=0,
                     help='number of polls, 0 for forever (default)')
    sub.add_argument('-i', '--interval', type=int, default=30,
                     help='seconds between polls (default 30)')
    sub.set_defaults(func=cmd_watch)

    sub = subs.add_parser('control', help='send one ISY command to a device')
    add_device_args(sub)
    sub.add_argument('--cmd', required=True,
                     help='ISY command id, e.g. DON, DOF, SETMODE, SETTEMP')
    sub.add_argument('--value',
                     help='command parameter, if the command takes one')
    sub.set_defaults(func=cmd_control)

    sub = subs.add_parser(
        'params', help='parse custom parameters given on the command line')
    sub.add_argument('param_entry', nargs='+',
                     help='"key=value" pairs as entered in PG3')
    sub.set_defaults(func=cmd_params)

    args = parser.parse_args()

    logging.getLogger().setLevel(
        logging.DEBUG if args.debug else logging.INFO)
    logging.getLogger('msmart').setLevel(
        logging.DEBUG if args.debug else logging.WARNING)

    try:
        return args.func(args)
    finally:
        RUNNER.stop()


if __name__ == '__main__':
    sys.exit(main())
