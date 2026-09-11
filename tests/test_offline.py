#!/usr/bin/env python3
"""
Offline tests for the Midea node server.

Runs the controller's configuration parsing and the AC node's state publishing
and command handling against a fake device, so behaviour can be checked without
an EISY or a real air conditioner.

    python3 tests/test_offline.py
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# The stub udi_interface must win over any real install.
sys.path.insert(0, os.path.join(HERE, 'stubs'))
sys.path.insert(1, os.path.dirname(HERE))

import udi_interface  # noqa: E402  (stub)
from msmart.device import AirConditioner as AC  # noqa: E402

from nodes.ac import MideaACNode  # noqa: E402
from nodes.aioloop import RUNNER  # noqa: E402
from nodes.controller import Controller  # noqa: E402
from nodes.mapping import (CONN_OFFLINE, CONN_ONLINE, UOM_CELSIUS,  # noqa: E402
                           UOM_FAHRENHEIT, address_for, c_to_f, f_to_c)


class FakeDevice:
    """Stands in for msmart's AirConditioner.

    Mirrors the state dump from a real MSmartHome unit, including the awkward
    parts: humidity unsupported, target_humidity reporting 0, energy counters
    returning None.
    """

    def __init__(self):
        self.applied = 0
        self.refreshed = 0
        self.display_toggled = 0
        self.self_cleaned = 0

        self.ip = '10.1.1.39'
        self.port = 6444
        self.id = 151732604872862
        self.online = True
        self.supported = True
        self.name = 'net_ac_E1E8'
        self.version = 3

        self.power_state = False
        self.operational_mode = AC.OperationalMode.COOL
        self.fan_speed = AC.FanSpeed.MAX
        self.swing_mode = AC.SwingMode.OFF
        self.horizontal_swing_angle = AC.SwingAngle.OFF
        self.vertical_swing_angle = AC.SwingAngle.OFF
        self.target_temperature = 20.5
        self.indoor_temperature = 22.5
        self.outdoor_temperature = 23.0
        self.target_humidity = 0
        self.indoor_humidity = None
        self.eco = False
        self.turbo = False
        self.freeze_protection = False
        self.sleep = False
        self.display_on = True
        self.beep = False
        self.fahrenheit = True
        self.filter_alert = True
        self.follow_me = False
        self.purifier = False
        self.self_clean_active = False
        self.rate_select = AC.RateSelect.OFF
        self.aux_mode = AC.AuxHeatMode.OFF
        self.error_code = 0
        self.defrost_active = None
        self.compressor_frequency = None
        self.indoor_coil_temperature = None
        self.outdoor_coil_temperature = None

        self.min_target_temperature = 16.0
        self.max_target_temperature = 30.0

        # Capabilities as reported by the real unit.
        self.supports_custom_fan_speed = True
        self.supports_eco = False
        self.supports_turbo = True
        self.supports_freeze_protection = False
        self.supports_display_control = True
        self.supports_filter_reminder = True
        self.supports_humidity = False
        self.supports_target_humidity = False
        self.supports_self_clean = False
        self.supports_fresh_air = False
        self.supports_breeze_away = False
        self.supports_breezeless = False
        self.supports_vertical_swing_angle = False
        self.supports_horizontal_swing_angle = False

        self.enable_energy_usage_requests = False
        self.enable_group1_data_requests = False
        self.enable_group5_data_requests = False
        self.enable_group7_data_requests = False
        self.enable_group11_data_requests = False

        self.breeze_away = False
        self.breeze_mild = False
        self.breezeless = False
        self.fresh_air_fan_speed = AC.FreshAirFanSpeed.OFF

    def get_total_energy_usage(self, *_a, **_k):
        return None

    def get_real_time_power_usage(self, *_a, **_k):
        return None

    def serialize_capabilities(self):
        return {'supports_turbo': True}

    async def refresh(self):
        self.refreshed += 1

    async def apply(self):
        self.applied += 1

    async def get_capabilities(self):
        pass

    async def authenticate(self, token, key):
        pass

    async def toggle_display(self):
        self.display_toggled += 1
        self.display_on = not self.display_on

    async def start_self_clean(self):
        self.self_cleaned += 1


def build_node(fahrenheit=True):
    polyglot = udi_interface.Interface([])
    controller = Controller(polyglot, 'controller', 'controller', 'Midea AC')
    controller.fahrenheit = fahrenheit

    config = {'ip': '10.1.1.39', 'port': 6444, 'id': 151732604872862,
              'token': None, 'key': None, 'version': 3, 'name': 'Bedroom'}

    node = MideaACNode(polyglot, 'controller', address_for(config['id']),
                       'Bedroom', config, controller)
    node.device = FakeDevice()
    node.capabilities_read = True
    return controller, node


class TestMapping(unittest.TestCase):

    def test_address_fits_isy_limit(self):
        address = address_for(151732604872862)
        self.assertLessEqual(len(address), 14)
        self.assertTrue(address.isalnum())
        self.assertEqual(address, address_for(151732604872862))
        self.assertNotEqual(address, address_for(151732604872863))

    def test_temperature_round_trip(self):
        self.assertAlmostEqual(f_to_c(c_to_f(20.5)), 20.5, places=6)


class TestParameterParsing(unittest.TestCase):

    def setUp(self):
        self.polyglot = udi_interface.Interface([])
        self.controller = Controller(
            self.polyglot, 'controller', 'controller', 'Midea AC')

    def test_full_device_entry(self):
        self.controller.parameter_handler({
            'temp_units': 'C',
            'beep': 'true',
            'discovery': 'false',
            'Bedroom': ('ip=10.1.1.39; id=151732604872862; port=6444; '
                        'token=AABB; key=CCDD'),
        })

        self.assertFalse(self.controller.fahrenheit)
        self.assertTrue(self.controller.beep)
        self.assertFalse(self.controller.discovery_enabled)

        config = self.controller.configured['Bedroom']
        self.assertEqual(config['address'], address_for(151732604872862))
        self.assertEqual(config['ip'], '10.1.1.39')
        self.assertEqual(config['id'], 151732604872862)
        self.assertEqual(config['token'], 'AABB')
        self.assertEqual(config['key'], 'CCDD')
        self.assertEqual(config['name'], 'Bedroom')

    def test_bare_ip_value(self):
        self.controller.parameter_handler({'Den': '10.1.1.40'})
        configs = list(self.controller.configured.values())
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]['ip'], '10.1.1.40')
        self.assertIsNone(configs[0]['id'])

    def test_devices_without_an_id_do_not_collide(self):
        self.controller.parameter_handler(
            {'Den': '10.1.1.40', 'Office': '10.1.1.41'})
        self.assertEqual(len(self.controller.configured), 2)
        self.assertEqual(
            {c['ip'] for c in self.controller.configured.values()},
            {'10.1.1.40', '10.1.1.41'})

    def test_token_without_key_is_rejected(self):
        self.controller.parameter_handler(
            {'Den': 'ip=10.1.1.40; id=1; token=AABB'})
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(self.controller.Notices)

    def test_non_hex_token_is_rejected(self):
        self.controller.parameter_handler(
            {'Den': 'ip=10.1.1.40; id=1; token=ZZ; key=AABB'})
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(any('hexadecimal' in text
                            for text in self.controller.Notices.values()))

    def test_odd_length_key_is_rejected(self):
        self.controller.parameter_handler(
            {'Den': 'ip=10.1.1.40; id=1; token=AABB; key=ABC'})
        self.assertEqual(self.controller.configured, {})

    def test_valid_hex_credentials_are_accepted(self):
        self.controller.parameter_handler(
            {'Den': 'ip=10.1.1.40; id=1; token=aabbCC; key=0011'})
        self.assertEqual(len(self.controller.configured), 1)
        self.assertFalse(self.controller.Notices)

    def test_missing_ip_is_rejected(self):
        self.controller.parameter_handler({'Den': 'id=1; token=A; key=B'})
        self.assertEqual(self.controller.configured, {})

    def test_reserved_params_are_not_devices(self):
        self.controller.parameter_handler(
            {'temp_units': 'F', 'discovery_timeout': '9'})
        self.assertEqual(self.controller.configured, {})
        self.assertEqual(self.controller.discovery_timeout, 9)


class TestPublish(unittest.TestCase):

    def setUp(self):
        RUNNER.start()
        self.controller, self.node = build_node()

    def test_publish_fahrenheit(self):
        self.node.publish()
        drivers = self.node.driver_values

        self.assertEqual(drivers['GV0'], CONN_ONLINE)
        self.assertEqual(drivers['ST'], 0)                     # power off
        self.assertAlmostEqual(drivers['CLITEMP'], 72.5, places=1)
        self.assertAlmostEqual(drivers['GV1'], 73.4, places=1)
        self.assertAlmostEqual(drivers['CLISPC'], 68.9, places=1)
        self.assertEqual(drivers['CLIMD'], 2)                  # cool
        self.assertEqual(drivers['CLIFS'], 100)                # max
        self.assertEqual(drivers['GV2'], 100)
        self.assertEqual(drivers['GV4'], 0)                    # swing off
        self.assertEqual(drivers['GV8'], 0)                    # turbo
        self.assertEqual(drivers['GV11'], 1)                   # display on
        self.assertEqual(drivers['GV14'], 1)                   # filter alert
        self.assertEqual(drivers['GV19'], 100)                 # rate off
        self.assertEqual(self.node.driver_uoms['CLITEMP'], UOM_FAHRENHEIT)

    def test_publish_celsius(self):
        self.controller.fahrenheit = False
        self.node.publish()
        self.assertAlmostEqual(self.node.driver_values['CLITEMP'], 22.5)
        self.assertAlmostEqual(self.node.driver_values['CLISPC'], 20.5)
        self.assertEqual(self.node.driver_uoms['CLISPC'], UOM_CELSIUS)

    def test_unsupported_features_are_not_published(self):
        # Humidity is unsupported on this unit, so the 0 the device reports
        # must not be mistaken for a real reading.
        self.node.publish()
        self.assertEqual(self.node.driver_values['CLIHUM'], 0)
        self.assertEqual(self.node.driver_values['GV3'], 0)

    def test_offline_device_marks_connection(self):
        self.node.device.online = False
        self.node.publish()
        self.assertEqual(self.node.driver_values['GV0'], CONN_OFFLINE)
        self.assertEqual(self.node.driver_values['ST'], 0)

    def test_custom_fan_speed_reports_percent_only(self):
        self.node.device.fan_speed = 37
        self.node.publish()
        self.assertEqual(self.node.driver_values['GV2'], 37)
        # 37 is not a preset, so the preset driver keeps its previous value.
        self.assertEqual(self.node.driver_values['CLIFS'], 102)


class TestCommands(unittest.TestCase):

    def setUp(self):
        RUNNER.start()
        self.controller, self.node = build_node()
        self.device = self.node.device

    def test_power_on(self):
        self.node.cmd_don()
        self.assertTrue(self.device.power_state)
        self.assertEqual(self.device.applied, 1)
        self.assertEqual(self.node.driver_values['ST'], 1)

    def test_setpoint_fahrenheit_converts_to_celsius(self):
        self.node.cmd_set_temperature({'value': '72'})
        self.assertAlmostEqual(self.device.target_temperature, 22.0, places=1)
        self.assertEqual(self.device.applied, 1)

    def test_setpoint_celsius(self):
        self.controller.fahrenheit = False
        self.node.cmd_set_temperature({'value': '21'})
        self.assertAlmostEqual(self.device.target_temperature, 21.0)

    def test_setpoint_scaled_integer_is_recovered(self):
        # Some ISY firmware sends prec-scaled integers: 720 means 72.0F.
        self.node.cmd_set_temperature({'value': '720'})
        self.assertAlmostEqual(self.device.target_temperature, 22.0, places=1)

    def test_setpoint_is_clamped_to_device_limits(self):
        self.node.cmd_set_temperature({'value': '32'})   # 0C
        self.assertAlmostEqual(self.device.target_temperature, 16.0)

    def test_setpoint_snaps_to_half_degrees(self):
        self.node.cmd_set_temperature({'value': '75'})
        doubled = self.device.target_temperature * 2
        self.assertEqual(doubled, int(doubled))

    def test_set_mode(self):
        self.node.cmd_set_mode({'value': '4'})
        self.assertEqual(self.device.operational_mode, AC.OperationalMode.HEAT)

    def test_set_fan_preset(self):
        self.node.cmd_set_fan({'value': '40'})
        self.assertEqual(self.device.fan_speed, AC.FanSpeed.LOW)

    def test_set_fan_percent(self):
        self.node.cmd_set_fan_percent({'value': '55'})
        self.assertEqual(self.device.fan_speed, 55)

    def test_set_fan_percent_refused_when_unsupported(self):
        self.device.supports_custom_fan_speed = False
        self.node.cmd_set_fan_percent({'value': '55'})
        self.assertEqual(self.device.applied, 0)

    def test_set_swing(self):
        self.node.cmd_set_swing({'value': '12'})
        self.assertEqual(self.device.swing_mode, AC.SwingMode.VERTICAL)

    def test_boolean_command(self):
        self.node.cmd_set_turbo({'value': '1'})
        self.assertTrue(self.device.turbo)
        self.node.cmd_set_turbo({'value': '0'})
        self.assertFalse(self.device.turbo)

    def test_display_only_toggles_on_change(self):
        self.device.display_on = True
        self.node.cmd_set_display({'value': '1'})
        self.assertEqual(self.device.display_toggled, 0)
        self.node.cmd_set_display({'value': '0'})
        self.assertEqual(self.device.display_toggled, 1)
        self.assertFalse(self.device.display_on)

    def test_self_clean_refused_when_unsupported(self):
        self.node.cmd_self_clean()
        self.assertEqual(self.device.self_cleaned, 0)

    def test_self_clean_runs_when_supported(self):
        self.device.supports_self_clean = True
        self.node.cmd_self_clean()
        self.assertEqual(self.device.self_cleaned, 1)

    def test_beep_is_applied_with_every_command(self):
        self.controller.beep = True
        self.node.cmd_don()
        self.assertTrue(self.device.beep)

    def test_breeze_mode_maps_to_booleans(self):
        self.node.cmd_set_breeze({'value': '4'})
        self.assertTrue(self.device.breezeless)
        self.node.cmd_set_breeze({'value': '1'})
        self.assertFalse(self.device.breeze_away)

    def test_command_table_matches_methods(self):
        for name, function in MideaACNode.commands.items():
            self.assertTrue(callable(function), name)

    def test_query_value_form_is_accepted(self):
        self.node.cmd_set_mode({'query': {'CLIMD.uom25': '3'}})
        self.assertEqual(self.device.operational_mode, AC.OperationalMode.DRY)


class TestDiscoveryAndPolling(unittest.TestCase):
    """Discovery and node syncing, with the network stubbed out."""

    def setUp(self):
        RUNNER.start()
        self.polyglot = udi_interface.Interface([])
        self.controller = Controller(
            self.polyglot, 'controller', 'controller', 'Midea AC')

        self.broadcast_result = []
        self.probe_result = {}
        self.broadcasts = 0

        def fake_broadcast():
            self.broadcasts += 1
            return list(self.broadcast_result)

        self.controller._broadcast = fake_broadcast
        self.controller._probe = lambda host: self.probe_result.get(host)

    @staticmethod
    def found(device_id, ip, version=3, name='net_ac_E1E8', supported=True):
        return {
            'address': address_for(device_id),
            'param_key': None,
            'ip': ip,
            'port': 6444,
            'id': device_id,
            'token': None,
            'key': None,
            'version': version,
            'name': name,
            'supported': supported,
            'sn': 'SN',
        }

    def test_broadcast_creates_a_node(self):
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]
        self.controller.discover()

        address = address_for(151732604872862)
        self.assertIn(address, self.controller.nodes_by_address)
        self.assertEqual(self.controller.driver_values['GV0'], 1)

    def test_v3_device_without_credentials_raises_a_notice(self):
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]
        self.controller.discover()
        self.assertTrue(
            any('token' in text.lower()
                for text in self.controller.Notices.values()))

    def test_configured_token_survives_discovery(self):
        self.controller.parameter_handler({
            'Bedroom': ('ip=10.1.1.39; id=151732604872862; '
                        'token=AABB; key=CCDD')})
        self.probe_result['10.1.1.39'] = self.found(
            151732604872862, '10.1.1.39')
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]

        self.controller.discover()

        node = self.controller.nodes_by_address[
            address_for(151732604872862)]
        self.assertEqual(node.config['token'], 'AABB')
        self.assertEqual(node.config['key'], 'CCDD')
        self.assertEqual(node.name, 'Bedroom')

    def test_unreachable_configured_device_still_gets_a_node_via_id(self):
        self.controller.parameter_handler({
            'Bedroom': 'ip=10.1.1.39; id=151732604872862; token=AA; key=BB'})
        self.controller.discover()
        self.assertIn(address_for(151732604872862),
                      self.controller.nodes_by_address)

    def test_unreachable_device_without_an_id_raises_a_notice(self):
        self.controller.parameter_handler({'Bedroom': 'ip=10.1.1.39'})
        self.controller.discover()
        self.assertEqual(self.controller.nodes_by_address, {})
        self.assertTrue(self.controller.Notices)

    def test_unsupported_device_gets_no_node(self):
        self.broadcast_result = [
            self.found(151732604872862, '10.1.1.39', supported=False)]
        self.controller.discover()
        self.assertEqual(self.controller.nodes_by_address, {})

    def test_rediscovery_is_throttled_when_everything_is_healthy(self):
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]
        self.controller.discover()
        node = self.controller.nodes_by_address[
            address_for(151732604872862)]
        node.connection_state = CONN_ONLINE
        node.update = lambda: True

        before = self.broadcasts
        for _ in range(self.controller.REDISCOVER_EVERY - 1):
            self.controller.long_poll()
        self.assertEqual(self.broadcasts, before)

        self.controller.long_poll()
        self.assertEqual(self.broadcasts, before + 1)

    def test_offline_node_triggers_immediate_rediscovery(self):
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]
        self.controller.discover()
        node = self.controller.nodes_by_address[
            address_for(151732604872862)]
        node.connection_state = CONN_OFFLINE

        before = self.broadcasts
        self.controller.long_poll()
        self.assertEqual(self.broadcasts, before + 1)

    def test_device_count_survives_a_missed_broadcast(self):
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]
        self.controller.discover()
        self.assertEqual(self.controller.driver_values['GV0'], 1)

        self.broadcast_result = []
        self.controller.discover()
        self.assertEqual(self.controller.driver_values['GV0'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
