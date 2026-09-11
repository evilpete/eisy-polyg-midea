"""
Controller node: configuration, discovery and polling for the Midea plugin.
"""

import threading

import udi_interface

from msmart.discover import Discover
from msmart.const import DeviceType

from .ac import MideaACNode
from .aioloop import RUNNER
from .mapping import (CTRL_CONNECTED, CTRL_ERROR, CTRL_NOT_CONNECTED,
                      CONN_ONLINE, UOM_INDEX, UOM_RAW, address_for, is_hex,
                      parse_bool, parse_int, safe_name)

LOGGER = udi_interface.LOGGER
Custom = udi_interface.Custom

# Custom parameter keys that configure the plugin rather than a device.
RESERVED_PARAMS = {
    'temp_units',
    'discovery',
    'discovery_timeout',
    'discovery_interface',
    'beep',
    'energy_stats',
    'extended_sensors',
    'connection_lifetime',
}

DEVICE_FIELDS = ('ip', 'host', 'id', 'port', 'token', 'key', 'name', 'version')


class Controller(udi_interface.Node):
    """Top level node. Owns configuration, discovery and the poll loop."""

    id = 'MIDEACTRL'

    drivers = [
        {'driver': 'ST', 'value': CTRL_NOT_CONNECTED, 'uom': UOM_INDEX},
        {'driver': 'GV0', 'value': 0, 'uom': UOM_RAW},
        {'driver': 'GV1', 'value': 0, 'uom': UOM_RAW},
    ]

    def __init__(self, polyglot, primary, address, name):
        super().__init__(polyglot, primary, address, name)

        self.poly = polyglot
        self.Parameters = Custom(polyglot, 'customparams')
        self.Notices = Custom(polyglot, 'notices')
        self.Data = Custom(polyglot, 'customdata')

        # Settings, with defaults applied until custom params arrive.
        self.fahrenheit = True
        self.beep = False
        self.discovery_enabled = True
        self.discovery_timeout = 5
        self.discovery_interface = None
        self.energy_stats = False
        self.extended_sensors = False
        self.connection_lifetime = None

        # address -> device config dict
        self.configured = {}
        self.nodes_by_address = {}

        self._params_ready = threading.Event()
        self._discovery_lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self._long_polls = 0

        polyglot.subscribe(polyglot.START, self.start, address)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.parameter_handler)
        polyglot.subscribe(polyglot.POLL, self.poll)
        polyglot.subscribe(polyglot.DISCOVER, self.cmd_discover)
        polyglot.subscribe(polyglot.STOP, self.stop)

        polyglot.ready()
        polyglot.addNode(self)

    # -------------------------------------------------------------- lifecycle

    def start(self):
        LOGGER.info('Midea node server starting')
        self.poly.updateProfile()
        self.poly.setCustomParamsDoc()

        RUNNER.start()

        # Wait briefly for the first custom parameter callback so we do not
        # discover with stale defaults on a configured install.
        self._params_ready.wait(timeout=20)

        self.setDriver('ST', CTRL_CONNECTED, force=True)
        self.discover()

    def stop(self):
        LOGGER.info('Midea node server stopping')
        self.setDriver('ST', CTRL_NOT_CONNECTED, force=True)
        RUNNER.stop()
        self.poly.stop()

    # ------------------------------------------------------------ parameters

    def parameter_handler(self, params):
        self.Parameters.load(params)
        self.Notices.clear()

        units = str(self.Parameters.get('temp_units') or 'F').strip().upper()
        self.fahrenheit = not units.startswith('C')

        self.beep = parse_bool(self.Parameters.get('beep'), False)
        self.discovery_enabled = parse_bool(
            self.Parameters.get('discovery'), True)
        self.discovery_timeout = parse_int(
            self.Parameters.get('discovery_timeout'), 5) or 5
        self.discovery_interface = (
            self.Parameters.get('discovery_interface') or None)
        self.energy_stats = parse_bool(
            self.Parameters.get('energy_stats'), False)
        self.extended_sensors = parse_bool(
            self.Parameters.get('extended_sensors'), False)
        self.connection_lifetime = parse_int(
            self.Parameters.get('connection_lifetime'), None)

        self.configured = {}
        for key, value in self.Parameters.items():
            if key in RESERVED_PARAMS:
                continue
            config = self._parse_device_param(key, value)
            if config is None:
                continue
            # Keyed by parameter name, not node address: a device whose id is
            # not known yet has no address and would otherwise collide.
            self.configured[key] = config

        LOGGER.info('Configuration loaded: units=%s discovery=%s devices=%d',
                    'F' if self.fahrenheit else 'C',
                    self.discovery_enabled, len(self.configured))

        if not self.discovery_enabled and not self.configured:
            self.Notices['config'] = (
                'Discovery is disabled and no devices are configured. Add a '
                'device parameter, or set discovery to true.')

        self._params_ready.set()

        # Push changes into nodes that already exist.
        for config in self.configured.values():
            node = self.nodes_by_address.get(config.get('address'))
            if node is not None:
                node.update_config(config)

    def _parse_device_param(self, key, value):
        """Parse one `name = ip=..;id=..;token=..;key=..` custom parameter."""
        raw = str(value or '').strip()
        if not raw:
            return None

        fields = {}
        if '=' not in raw:
            # Bare value is treated as the address of the unit.
            fields['ip'] = raw
        else:
            for part in raw.replace(',', ';').split(';'):
                part = part.strip()
                if not part or '=' not in part:
                    continue
                field, _, field_value = part.partition('=')
                field = field.strip().lower()
                if field in DEVICE_FIELDS:
                    fields[field] = field_value.strip()
                else:
                    LOGGER.warning(
                        "Ignoring unknown field '%s' in parameter '%s'",
                        field, key)

        ip = fields.get('ip') or fields.get('host')
        if not ip:
            self.Notices[f'cfg_{key}'] = (
                f"Device '{key}' is missing an ip= value and was ignored.")
            LOGGER.error("Device parameter '%s' has no ip=", key)
            return None

        device_id = parse_int(fields.get('id'))
        if device_id is None:
            self.Notices[f'cfg_{key}'] = (
                f"Device '{key}' has no id= value; it will be resolved by "
                f"probing {ip} at startup.")

        token = fields.get('token') or None
        key_hex = fields.get('key') or None
        if bool(token) != bool(key_hex):
            self.Notices[f'cfg_{key}'] = (
                f"Device '{key}' needs both token= and key= (or neither).")
            LOGGER.error("Device parameter '%s' has only one of token/key", key)
            return None

        for field_name, value_hex in (('token', token), ('key', key_hex)):
            if value_hex is not None and not is_hex(value_hex):
                self.Notices[f'cfg_{key}'] = (
                    f"Device '{key}' has a {field_name}= that is not "
                    f"hexadecimal. Copy it exactly as 'msmart-ng discover' "
                    f"printed it.")
                LOGGER.error("Device parameter '%s' has a non-hex %s",
                             key, field_name)
                return None

        return {
            'address': address_for(device_id) if device_id is not None else None,
            'param_key': key,
            'ip': ip,
            'port': parse_int(fields.get('port'), 6444) or 6444,
            'id': device_id,
            'token': token,
            'key': key_hex,
            'version': parse_int(fields.get('version')),
            'name': fields.get('name') or key,
        }

    # -------------------------------------------------------------- discovery

    def cmd_discover(self, command=None):
        self.discover()

    def discover(self):
        """Find devices, merge them with configuration, and create nodes."""
        if not self._discovery_lock.acquire(blocking=False):
            LOGGER.info('Discovery already in progress')
            return

        try:
            found = {}

            # 1. Probe each explicitly configured host. This resolves the
            #    device id, protocol version and serial number without
            #    touching the Midea cloud.
            for config in list(self.configured.values()):
                info = self._probe(config['ip'])
                if info is not None:
                    merged = dict(info)
                    merged.update({k: v for k, v in config.items()
                                   if v is not None and k != 'address'})
                    # The probe is authoritative for identity fields.
                    merged['id'] = config.get('id') or info['id']
                    merged['version'] = config.get('version') or info.get('version')
                    merged['address'] = address_for(merged['id'])
                    found[merged['address']] = merged
                elif config.get('id') is not None:
                    LOGGER.warning(
                        'Could not probe %s; using the configured id',
                        config['ip'])
                    config['address'] = address_for(config['id'])
                    found[config['address']] = dict(config)
                else:
                    self.Notices[f"probe_{config['param_key']}"] = (
                        f"Could not reach {config['ip']}. Add an id= value or "
                        f"check the address.")

            # 2. Broadcast discovery, if enabled. Configured entries win so a
            #    hand-entered token/key is never overwritten.
            if self.discovery_enabled:
                for info in self._broadcast():
                    address = address_for(info['id'])
                    if address in found:
                        found[address].setdefault('ip', info['ip'])
                        continue
                    found[address] = info

            self._sync_nodes(found)
        finally:
            self._discovery_lock.release()

    def _device_info(self, device):
        """Flatten an msmart device into our config dict."""
        return {
            'address': address_for(device.id),
            'param_key': None,
            'ip': device.ip,
            'port': device.port,
            'id': device.id,
            'token': None,
            'key': None,
            'version': device.version,
            'name': safe_name(device.name or f'Midea {device.id}'),
            'supported': device.supported,
            'type': device.type,
            'sn': device.sn,
        }

    def _probe(self, host):
        """Unicast discovery against a single host. Never uses the cloud."""
        try:
            device = RUNNER.run(
                Discover.discover_single(
                    host,
                    timeout=self.discovery_timeout,
                    auto_connect=False),
                timeout=self.discovery_timeout + 20)
        except Exception as ex:
            LOGGER.warning('Probe of %s failed: %s', host, ex)
            return None

        if device is None:
            LOGGER.warning('No response from %s', host)
            return None

        return self._device_info(device)

    def _broadcast(self):
        """Broadcast discovery. Never uses the cloud."""
        LOGGER.info('Broadcasting for Midea devices')
        try:
            devices = RUNNER.run(
                Discover.discover(
                    timeout=self.discovery_timeout,
                    interface=self.discovery_interface,
                    auto_connect=False),
                timeout=self.discovery_timeout + 30)
        except Exception as ex:
            LOGGER.error('Broadcast discovery failed: %s', ex)
            return []

        results = []
        for device in devices:
            if device.type != DeviceType.AIR_CONDITIONER:
                LOGGER.info('Ignoring unsupported device type %s at %s',
                            device.type, device.ip)
                continue
            results.append(self._device_info(device))

        LOGGER.info('Discovery found %d air conditioner(s)', len(results))
        return results

    # ----------------------------------------------------------- node wrangling

    def _sync_nodes(self, found):
        """Create nodes for everything we found and note anything unusable."""
        for address, config in found.items():
            if config.get('supported') is False:
                self.Notices[f'unsup_{address}'] = (
                    f"Device at {config['ip']} reports that it is not "
                    f"supported by the msmart library.")
                LOGGER.warning('Device %s at %s is not supported',
                               config['id'], config['ip'])
                continue

            if config.get('version') == 3 and not (config.get('token')
                                                   and config.get('key')):
                self.Notices[f'token_{address}'] = (
                    f"{config['name']} ({config['ip']}) is a V3 device and "
                    f"needs a token and key. Add a custom parameter such as: "
                    f"{config['name']} = ip={config['ip']}; "
                    f"id={config['id']}; token=<TOKEN>; key=<KEY>")
                LOGGER.warning('V3 device %s has no token/key configured',
                               config['name'])

            node = self.poly.getNode(address)
            if node is None:
                LOGGER.info('Adding node %s for %s at %s',
                            address, config['name'], config['ip'])
                node = MideaACNode(self.poly, self.address, address,
                                   config['name'], config, self)
                self.poly.addNode(node)
            else:
                node.update_config(config)

            self.nodes_by_address[address] = node

        # Count the nodes we have, not what this one discovery run happened to
        # see: a unit that missed a broadcast still has a node.
        self.setDriver('GV0', len(self.nodes_by_address))
        self._update_online_count()

    def _update_online_count(self):
        online = sum(
            1 for node in self.nodes_by_address.values()
            if node.connection_state == CONN_ONLINE)
        self.setDriver('GV1', online)
        self.setDriver(
            'ST', CTRL_CONNECTED if self.nodes_by_address else CTRL_ERROR)

    # ------------------------------------------------------------------ polls

    def poll(self, polltype):
        if 'shortPoll' in polltype:
            self.short_poll()
        elif 'longPoll' in polltype:
            self.long_poll()

    def short_poll(self):
        if not self._poll_lock.acquire(blocking=False):
            LOGGER.warning('Previous poll still running, skipping this one')
            return

        try:
            for node in list(self.nodes_by_address.values()):
                node.update()
            self._update_online_count()
        finally:
            self._poll_lock.release()

    # Long polls between routine re-discoveries. At the default 300s long poll
    # this broadcasts about once an hour rather than every five minutes.
    REDISCOVER_EVERY = 12

    def long_poll(self):
        self._long_polls += 1

        # Something is wrong, or a configured device never got a node: look for
        # it now rather than waiting for the next routine sweep.
        unhealthy = any(node.connection_state != CONN_ONLINE
                        for node in self.nodes_by_address.values())
        unresolved = any(
            config.get('address') not in self.nodes_by_address
            for config in self.configured.values())

        routine = (self.discovery_enabled
                   and self._long_polls % self.REDISCOVER_EVERY == 0)

        if unhealthy or unresolved or routine:
            self.discover()

        self.reportDrivers()

    # --------------------------------------------------------------- commands

    def cmd_query(self, command=None):
        for node in list(self.nodes_by_address.values()):
            node.query()
        self._update_online_count()
        self.reportDrivers()

    def cmd_update_profile(self, command=None):
        LOGGER.info('Updating profile on the ISY')
        self.poly.updateProfile()

    def cmd_remove_notices(self, command=None):
        self.Notices.clear()

    commands = {
        'DISCOVER': cmd_discover,
        'QUERY': cmd_query,
        'UPDATE_PROFILE': cmd_update_profile,
        'REMOVE_NOTICES': cmd_remove_notices,
    }
