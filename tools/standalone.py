#!/usr/bin/env python3
"""
Stand-alone driver for the Midea node server.

Runs the plugin's real controller and node classes against real hardware with
no Polyglot, no ISY and no EISY involved, and prints exactly which ISY drivers
would be set. Use it to debug a device before or instead of installing the
plugin.

    ./tools/standalone.py discover
    ./tools/standalone.py probe 10.1.1.39
    ./tools/standalone.py query 10.1.1.39 --id 151732604872862 \
        --token <TOKEN> --key <KEY>
    ./tools/standalone.py caps  10.1.1.39 --id ... --token ... --key ...
    ./tools/standalone.py watch 10.1.1.39 --id ... --token ... --key ... -n 10
    ./tools/standalone.py control 10.1.1.39 --id ... --token ... --key ... \
        --cmd CLISPC --value 72
    ./tools/standalone.py raw 10.1.1.39 --id ... --token ... --key ...

Connection details can also be given exactly as they appear in a PG3 custom
parameter, which is the easiest way to check that a parameter is well formed:

    ./tools/standalone.py query --param 'ip=10.1.1.39; id=151732604872862; token=AA; key=BB'
"""

import argparse
import json
import logging
import os
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
from nodes.mapping import address_for  # noqa: E402

PROFILE = os.path.join(ROOT, 'profile')


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

    order = [d['driver'] for d in MideaACNode.drivers]
    for driver in order:
        value = node.driver_values.get(driver)
        label = nls.get(f'ST-MIDEAAC-{driver}-NAME', driver)

        editor = driver_editor.get(driver)
        prefix = index_editors.get(editor)
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

def build(args):
    """Build a controller and one node, the same way the plugin does."""
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')
    controller.fahrenheit = args.units.upper().startswith('F')
    controller.beep = args.beep
    controller.energy_stats = args.energy
    controller.extended_sensors = args.extended
    controller.discovery_timeout = args.timeout

    RUNNER.start()

    config = device_config(controller, args)
    if config is None:
        return controller, None

    if config.get('id') is None:
        print(f'No id given; probing {config["ip"]} ...')
        info = controller._probe(config['ip'])
        if info is None:
            print(f'Could not reach {config["ip"]}')
            return controller, None
        config['id'] = info['id']
        config['version'] = info['version']
        config['port'] = info['port']
        print(f'Found id={config["id"]} version={config["version"]}')

    address = address_for(config['id'])
    node = MideaACNode(polyglot, 'controller', address,
                       config.get('name') or 'Midea AC', config, controller)
    polyglot.addNode(node)
    return controller, node


def device_config(controller, args):
    """Resolve connection details from --param or the individual flags."""
    if args.param:
        config = controller._parse_device_param('standalone', args.param)
        if config is None:
            print('That parameter value is not valid. See the messages above.')
        return config

    if not args.host:
        print('Give a host, or use --param.')
        return None

    return {
        'address': None,
        'param_key': 'standalone',
        'ip': args.host,
        'port': args.port,
        'id': args.id,
        'token': args.token,
        'key': args.key,
        'version': 3 if (args.token and args.key) else None,
        'name': args.name or args.host,
    }


def connect(node):
    if not node.connect():
        print('Connection failed. Run with --debug for the full reason.')
        return False
    return True


# -------------------------------------------------------------- subcommands

def cmd_discover(args):
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')
    controller.discovery_timeout = args.timeout
    controller.discovery_interface = args.interface
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
    return 0


def cmd_probe(args):
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')
    controller.discovery_timeout = args.timeout
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
    print(json.dumps(node.device.serialize_capabilities(),
                     indent=2, default=str))
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
    """Parse a set of custom parameters without touching any hardware."""
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')

    params = {}
    for entry in args.param_entry:
        key, _, value = entry.partition('=')
        params[key.strip()] = value.strip()

    controller.parameter_handler(params)

    print('\nSettings:')
    print(f'  units               {"F" if controller.fahrenheit else "C"}')
    print(f'  discovery           {controller.discovery_enabled}')
    print(f'  discovery_timeout   {controller.discovery_timeout}')
    print(f'  beep                {controller.beep}')
    print(f'  energy_stats        {controller.energy_stats}')
    print(f'  extended_sensors    {controller.extended_sensors}')

    print('\nDevices:')
    for address, config in controller.configured.items():
        print(f'  {address}  {json.dumps(config, default=str)}')
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
    parser.add_argument('--timeout', type=int, default=5,
                        help='discovery timeout in seconds (default 5)')

    def add_device_args(sub):
        sub.add_argument('host', nargs='?', help='device IP or hostname')
        sub.add_argument('--id', type=int, help='Midea device id')
        sub.add_argument('--token', help='V3 token (hex)')
        sub.add_argument('--key', help='V3 key (hex)')
        sub.add_argument('--port', type=int, default=6444)
        sub.add_argument('--name', help='node name to use')
        sub.add_argument('--param',
                         help='connection details in PG3 custom parameter '
                              'form, e.g. "ip=10.1.1.39; id=...; token=...; '
                              'key=..."')
        sub.add_argument('--units', default='F', choices=['F', 'C', 'f', 'c'])
        sub.add_argument('--beep', action='store_true',
                         help='let the unit beep on each command')
        sub.add_argument('--energy', action='store_true',
                         help='request energy counters')
        sub.add_argument('--extended', action='store_true',
                         help='request coil temps, compressor and defrost data')

    subs = parser.add_subparsers(dest='command', required=True)

    sub = subs.add_parser('discover', help='broadcast for devices')
    sub.add_argument('--interface', help='local interface address to bind')
    sub.set_defaults(func=cmd_discover)

    sub = subs.add_parser('probe', help='unicast discovery of one host')
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
                     help='ISY command id, e.g. DON, DOF, CLIMD, CLISPC')
    sub.add_argument('--value', help='command parameter, if the command takes one')
    sub.set_defaults(func=cmd_control)

    sub = subs.add_parser(
        'params', help='parse custom parameters without any hardware')
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
