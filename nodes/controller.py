"""
Controller node: configuration, discovery and polling for the Midea plugin.
"""

import json
import os
import threading

import udi_interface

from msmart.discover import Discover
from msmart.const import DeviceType

from . import profilegen
from .ac import DRIVER_COMMANDS, MideaACNode, resolve_drivers
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
    'hide_drivers',
    'auto_hide_unsupported',
    # Not a setting, but not a device name either: it holds a JSON collection
    # of devices. Handled separately.
    'devices',
}

DEVICE_FIELDS = ('ip', 'host', 'id', 'port', 'token', 'key', 'name', 'version',
                 'hide')


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
        self.hidden_drivers = set()
        self.auto_hide = True

        # Where the generated node definitions are written. An attribute so
        # that tests can point it somewhere harmless.
        self.profile_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'profile')

        # address -> readings the unit reported it has no hardware for,
        # remembered across restarts because the profile has to be built
        # before any device is contacted.
        self.capability_cache = {}

        # address -> device config dict
        self.configured = {}
        self.nodes_by_address = {}

        self._params_ready = threading.Event()
        self._data_ready = threading.Event()
        self._discovery_lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self._long_polls = 0

        polyglot.subscribe(polyglot.START, self.start, address)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.parameter_handler)
        polyglot.subscribe(polyglot.CUSTOMDATA, self.data_handler)
        polyglot.subscribe(polyglot.POLL, self.poll)
        polyglot.subscribe(polyglot.DISCOVER, self.cmd_discover)
        polyglot.subscribe(polyglot.STOP, self.stop)

        polyglot.ready()
        polyglot.addNode(self)

    # -------------------------------------------------------------- lifecycle

    def start(self):
        LOGGER.info('Midea node server starting')

        # Wait for custom parameters and the remembered capabilities before
        # the profile is built, since which rows each node carries depends on
        # both.
        self._params_ready.wait(timeout=20)
        self._data_ready.wait(timeout=10)

        self.build_profile()
        self.poly.updateProfile()
        self.poly.setCustomParamsDoc()

        RUNNER.start()

        self.setDriver('ST', CTRL_CONNECTED, force=True)
        self.discover()

    def stop(self):
        LOGGER.info('Midea node server stopping')
        self.setDriver('ST', CTRL_NOT_CONNECTED, force=True)
        RUNNER.stop()
        self.poly.stop()

    def data_handler(self, data):
        self.Data.load(data)
        self.capability_cache = {
            address: set(drivers)
            for address, drivers in (self.Data.get('capabilities') or {}).items()
        }
        if self.capability_cache:
            LOGGER.info('Remembered capabilities for %d device(s)',
                        len(self.capability_cache))
        self._data_ready.set()

    def hidden_for(self, config) -> frozenset:
        """Rows to leave off one device.

        The global list, plus the device's own `hide`, plus whatever the unit
        told us last time it connected that it has no hardware for.
        """
        hidden = set(self.hidden_drivers)
        hidden |= resolve_drivers(
            str(config.get('hide') or '').replace(';', ',').split(','))
        if self.auto_hide:
            hidden |= self.capability_cache.get(config.get('address'), set())
        return frozenset(hidden)

    def learn_capabilities(self, address, unsupported) -> None:
        """Remember what a unit cannot do, for the next profile build.

        The profile has to exist before any device is contacted, so a newly
        learned capability set can only take effect on the next start.
        """
        unsupported = set(unsupported)
        if self.capability_cache.get(address) == unsupported:
            return

        self.capability_cache[address] = unsupported
        self.Data['capabilities'] = {
            key: sorted(value)
            for key, value in self.capability_cache.items()}

        LOGGER.info('%s reports it has no: %s', address,
                    ', '.join(sorted(unsupported)) or 'missing features')

        if not self.auto_hide:
            return

        # Rebuild and send the profile now rather than waiting for the next
        # start, so the node can move onto its new definition immediately.
        self.build_profile()
        self.poly.updateProfile()

        self.Notices['capabilities'] = (
            'Adjusted the nodes to match what your units report they can do. '
            'Close and reopen the Admin Console to see the change; if a '
            'reading is still listed, restart the node server.')

    def build_profile(self) -> None:
        """Generate a node definition for each distinct set of hidden rows."""
        variants = {frozenset(self.hidden_drivers)}
        for config in self.configured.values():
            variants.add(self.hidden_for(config))
        for address in self.capability_cache:
            variants.add(self.hidden_for({'address': address}))

        if not any(variants):
            return

        try:
            profilegen.regenerate(
                self.profile_dir, variants, DRIVER_COMMANDS)
        except OSError as ex:
            self.Notices['profile'] = (
                'Could not write the profile, so hidden readings will still '
                f'appear as empty rows: {ex}')
            LOGGER.error('Could not regenerate the profile: %s', ex)
        except Exception:
            LOGGER.exception('Could not regenerate the profile')

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

        from .ac import resolve_drivers
        self.hidden_drivers = resolve_drivers(
            str(self.Parameters.get('hide_drivers') or '')
            .replace(';', ',').split(','))
        if self.hidden_drivers:
            LOGGER.info('Hiding drivers on every node: %s',
                        ', '.join(sorted(self.hidden_drivers)))

        self.auto_hide = parse_bool(
            self.Parameters.get('auto_hide_unsupported'), True)

        self.configured = {}
        for key, value in self._device_entries():
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

    def _device_entries(self):
        """Yield (name, value) for every parameter that describes a device.

        The Plugin Management page edits custom parameters as JSON, so a value
        may be a plain string, a nested object, or a JSON string. A `devices`
        parameter may also hold an object or array of several devices at once.
        """
        for key, value in self.Parameters.items():
            if key != 'devices':
                continue

            collection = value
            if isinstance(collection, str):
                collection = self._load_json(key, collection)
                if collection is None:
                    continue

            if isinstance(collection, dict):
                for name, entry in collection.items():
                    yield str(name), entry
            elif isinstance(collection, list):
                for index, entry in enumerate(collection, 1):
                    name = None
                    if isinstance(entry, dict):
                        name = entry.get('name')
                    yield str(name or f'device_{index}'), entry
            else:
                self.Notices['cfg_devices'] = (
                    "The 'devices' parameter must be a JSON object or array.")
                LOGGER.error("'devices' parameter is neither object nor array")

        for key, value in self.Parameters.items():
            if key not in RESERVED_PARAMS:
                yield key, value

    def _load_json(self, key, raw):
        try:
            return json.loads(raw)
        except ValueError as ex:
            self.Notices[f'cfg_{key}'] = (
                f"Parameter '{key}' looks like JSON but could not be parsed: "
                f"{ex}")
            LOGGER.error("Parameter '%s' is not valid JSON: %s", key, ex)
            return None

    def _extract_fields(self, key, value):
        """Pull device fields out of whichever shape the parameter arrived in."""
        # A JSON object, either nested by the UI or typed as a string.
        if isinstance(value, str) and value.strip().startswith('{'):
            value = self._load_json(key, value.strip())
            if value is None:
                return None

        if isinstance(value, dict):
            fields = {}
            for field, field_value in value.items():
                field = str(field).strip().lower()
                if field == 'host':
                    field = 'ip'
                if field in DEVICE_FIELDS:
                    fields[field] = (field_value if field_value is None
                                     else str(field_value).strip())
                else:
                    LOGGER.warning(
                        "Ignoring unknown field '%s' in parameter '%s'",
                        field, key)
            return fields

        raw = str(value if value is not None else '').strip()
        if not raw:
            return None

        if '=' not in raw:
            # Bare value is treated as the address of the unit.
            return {'ip': raw}

        fields = {}
        # Split on ';' only. A comma has to stay usable inside a value, for
        # list valued fields such as hide=GV5,GV6.
        for part in raw.split(';'):
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
        return fields

    @staticmethod
    def _is_template(value) -> bool:
        """True while a value still carries <PLACEHOLDER> text."""
        if isinstance(value, dict):
            return any(Controller._is_template(v) for v in value.values())
        if isinstance(value, list):
            return any(Controller._is_template(v) for v in value)
        text = str(value if value is not None else '')
        return '<' in text or '>' in text

    def _parse_device_param(self, key, value):
        """Parse one device parameter, in any of the accepted shapes."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None

        # server.json seeds an "example_device" parameter so the Custom
        # Parameters page shows the expected shape. Skip it until the
        # placeholders have actually been filled in.
        if self._is_template(value):
            self.Notices[f'cfg_{key}'] = (
                f"Parameter '{key}' still contains the <PLACEHOLDER> text. "
                f"Replace it with your device's values, or delete the "
                f"parameter.")
            LOGGER.info("Ignoring template parameter '%s'", key)
            return None

        fields = self._extract_fields(key, value)
        if fields is None:
            return None

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
            'hide': fields.get('hide'),
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

                    # A configured entry whose probe failed is not in `found`
                    # yet. Match it up by ip or id so that its credentials are
                    # carried over rather than replaced with the nothing that
                    # discovery knows.
                    config = self._configured_for(info)
                    if config is not None:
                        info = {**info,
                                **{k: v for k, v in config.items()
                                   if v is not None and k != 'address'}}
                        info['address'] = address

                    found[address] = info

            self._sync_nodes(found)
        finally:
            self._discovery_lock.release()

    def _configured_for(self, info):
        """Find the configured entry describing a discovered device, if any."""
        for config in self.configured.values():
            if config.get('id') is not None and config['id'] == info['id']:
                return config
            if config.get('id') is None and config['ip'] == info['ip']:
                return config
        return None

    def _device_info(self, device):
        """Flatten an msmart device into our config dict.

        Deliberately carries no 'supported' field. msmart only sets
        Device.supported after a successful refresh, and discovery runs with
        auto_connect False so that the Midea cloud is never contacted -- so it
        is False for every device seen here and says nothing about the unit.
        Whether a unit really is supported is settled by the node's own
        connection, and shown on its Connection driver.
        """
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
