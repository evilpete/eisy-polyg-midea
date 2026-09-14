#!/usr/bin/env python3
"""
Offline tests for the Midea node server.

Runs the controller's configuration parsing and the AC node's state publishing
and command handling against a fake device, so behaviour can be checked without
an EISY or a real air conditioner.

    python3 tests/test_offline.py
"""

import os
import shutil
import sys
import tempfile
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
from nodes.mapping import (CONN_OFFLINE, CONN_ONLINE,  # noqa: E402
                           CONN_UNSUPPORTED, UOM_CELSIUS, UOM_FAHRENHEIT,
                           address_for, c_to_f, f_to_c)


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

        # Capabilities exactly as the real unit reports them.
        self.supported_operation_modes = [
            AC.OperationalMode.FAN_ONLY, AC.OperationalMode.DRY,
            AC.OperationalMode.COOL, AC.OperationalMode.HEAT,
            AC.OperationalMode.AUTO]
        self.supported_swing_modes = [
            AC.SwingMode.OFF, AC.SwingMode.VERTICAL]
        self.supported_fan_speeds = [
            AC.FanSpeed.SILENT, AC.FanSpeed.LOW, AC.FanSpeed.MEDIUM,
            AC.FanSpeed.HIGH, AC.FanSpeed.AUTO, AC.FanSpeed.MAX]
        self.supported_aux_modes = [AC.AuxHeatMode.OFF]
        self.supported_rate_selects = [AC.RateSelect.OFF]
        self.additional_capabilities = [
            'CUSTOM_FAN_SPEED', 'TURBO', 'DISPLAY_CONTROL',
            'FILTER_REMINDER', 'SWING_VERTICAL_ANGLE']

        self.supports_custom_fan_speed = True
        self.supports_turbo = True
        self.supports_display_control = True
        self.supports_filter_reminder = True
        self.supports_vertical_swing_angle = True
        self.supports_eco = False
        self.supports_freeze_protection = False
        self.supports_humidity = False
        self.supports_target_humidity = False
        self.supports_self_clean = False
        self.supports_fresh_air = False
        self.supports_purifier = False
        self.supports_breeze_away = False
        self.supports_breeze_mild = False
        self.supports_breezeless = False
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
        return {
            'min_target_temperature': self.min_target_temperature,
            'max_target_temperature': self.max_target_temperature,
            'supported_modes': [m.name for m in
                                self.supported_operation_modes],
            'supported_swing_modes': [m.name for m in
                                      self.supported_swing_modes],
            'supported_fan_speeds': [f.name for f in
                                     self.supported_fan_speeds],
            'supported_aux_modes': [a.name for a in self.supported_aux_modes],
            'supported_rate_selects': [r.name for r in
                                       self.supported_rate_selects],
            'additional_capabilities': list(self.additional_capabilities),
        }

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

    # The Plugin Management page edits custom parameters as JSON, so values
    # can arrive as real objects, numbers and booleans, not only strings.

    def test_nested_json_object_value(self):
        self.controller.parameter_handler({
            'Bedroom': {
                'ip': '10.1.1.39',
                'id': 151732604872862,
                'token': 'AABB',
                'key': 'CCDD',
            },
        })
        config = self.controller.configured['Bedroom']
        self.assertEqual(config['ip'], '10.1.1.39')
        self.assertEqual(config['id'], 151732604872862)
        self.assertEqual(config['token'], 'AABB')
        self.assertEqual(config['address'], address_for(151732604872862))

    def test_json_object_as_a_string_value(self):
        self.controller.parameter_handler({
            'Bedroom': ('{"ip": "10.1.1.39", "id": 151732604872862, '
                        '"token": "AABB", "key": "CCDD"}'),
        })
        config = self.controller.configured['Bedroom']
        self.assertEqual(config['id'], 151732604872862)
        self.assertEqual(config['key'], 'CCDD')

    def test_devices_collection_as_an_object(self):
        self.controller.parameter_handler({
            'devices': {
                'Bedroom': {'ip': '10.1.1.39', 'id': 151732604872862,
                            'token': 'AABB', 'key': 'CCDD'},
                'Den': '10.1.1.40',
            },
        })
        self.assertEqual(set(self.controller.configured), {'Bedroom', 'Den'})
        self.assertEqual(
            self.controller.configured['Den']['ip'], '10.1.1.40')

    def test_devices_collection_as_an_array(self):
        self.controller.parameter_handler({
            'devices': [
                {'name': 'Bedroom', 'ip': '10.1.1.39',
                 'id': 151732604872862, 'token': 'AABB', 'key': 'CCDD'},
                {'ip': '10.1.1.40'},
            ],
        })
        self.assertIn('Bedroom', self.controller.configured)
        # An entry with no name still gets a stable, unique key.
        self.assertEqual(len(self.controller.configured), 2)

    def test_devices_collection_as_a_json_string(self):
        self.controller.parameter_handler({
            'devices': ('{"Bedroom": {"ip": "10.1.1.39", '
                        '"id": 151732604872862}}'),
        })
        self.assertEqual(
            self.controller.configured['Bedroom']['id'], 151732604872862)

    def test_settings_as_real_json_types(self):
        self.controller.parameter_handler({
            'temp_units': 'C',
            'discovery': False,
            'beep': True,
            'discovery_timeout': 9,
            'extended_sensors': True,
        })
        self.assertFalse(self.controller.fahrenheit)
        self.assertFalse(self.controller.discovery_enabled)
        self.assertTrue(self.controller.beep)
        self.assertEqual(self.controller.discovery_timeout, 9)
        self.assertTrue(self.controller.extended_sensors)
        self.assertEqual(self.controller.configured, {})

    def test_devices_is_never_treated_as_a_device_name(self):
        self.controller.parameter_handler({
            'devices': {'Bedroom': {'ip': '10.1.1.39',
                                    'id': 151732604872862}},
        })
        self.assertNotIn('devices', self.controller.configured)

    def test_malformed_json_raises_a_notice(self):
        self.controller.parameter_handler({'Bedroom': '{"ip": "10.1.1.39",}'})
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(any('JSON' in text
                            for text in self.controller.Notices.values()))

    def test_json_placeholder_is_ignored(self):
        self.controller.parameter_handler({
            'example_device': {'ip': '<IP ADDRESS>', 'id': '<DEVICE ID>'},
        })
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(any('PLACEHOLDER' in text
                            for text in self.controller.Notices.values()))

    def test_json_host_alias_and_bad_token(self):
        self.controller.parameter_handler({
            'Bedroom': {'host': '10.1.1.39', 'id': 1,
                        'token': 'NOTHEX', 'key': 'AABB'},
        })
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(any('hexadecimal' in text
                            for text in self.controller.Notices.values()))

    def test_example_placeholder_is_ignored(self):
        self.controller.parameter_handler({
            'temp_units': 'F',
            'discovery': 'true',
            'example_device': ('ip=<IP ADDRESS>; id=<DEVICE ID>; '
                               'token=<TOKEN>; key=<KEY>'),
        })
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(any('PLACEHOLDER' in text
                            for text in self.controller.Notices.values()))

    def test_server_json_defaults_are_understood(self):
        """Every customParams default in server.json must parse cleanly."""
        import json
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'server.json')) as handle:
            defaults = json.load(handle)['customParams']

        self.controller.parameter_handler(defaults)
        # The seeded settings must be recognised as settings, not devices.
        self.assertEqual(self.controller.configured, {})
        self.assertTrue(self.controller.fahrenheit)
        self.assertTrue(self.controller.discovery_enabled)

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

    def test_unsupported_device_is_reported_after_connecting(self):
        # Once a device has really been talked to, supported is meaningful.
        self.node.device.supported = False
        self.node.publish()
        self.assertEqual(self.node.driver_values['GV0'], CONN_UNSUPPORTED)

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
        self.device.supports_breezeless = True
        self.device.supports_breeze_away = True
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


class TestCapabilityGating(unittest.TestCase):
    """Every command the unit is not capable of must be refused outright.

    msmart only logs a warning and carries on, which leaves the rejected value
    set on the device object so that it is re-sent with every later command.
    Each case here is one taken from a real device log.
    """

    def setUp(self):
        RUNNER.start()
        self.controller, self.node = build_node()
        self.device = self.node.device

    def assert_refused(self, method, command=None):
        before = self.device.applied
        method(command) if command is not None else method()
        self.assertEqual(self.device.applied, before,
                         'the command reached the device')

    def test_eco_is_refused(self):
        self.assert_refused(self.node.cmd_set_eco, {'value': '1'})
        self.assertFalse(self.device.eco)

    def test_freeze_protection_is_refused(self):
        self.assert_refused(self.node.cmd_set_freeze, {'value': '1'})
        self.assertFalse(self.device.freeze_protection)

    def test_purifier_is_refused(self):
        self.assert_refused(self.node.cmd_set_purifier, {'value': '1'})
        self.assertFalse(self.device.purifier)

    def test_fresh_air_is_refused(self):
        self.assert_refused(self.node.cmd_set_fresh_air, {'value': '60'})
        self.assertEqual(self.device.fresh_air_fan_speed,
                         AC.FreshAirFanSpeed.OFF)

    def test_horizontal_angle_is_refused(self):
        self.assert_refused(self.node.cmd_set_horizontal_angle,
                            {'value': '1'})
        self.assertEqual(self.device.horizontal_swing_angle,
                         AC.SwingAngle.OFF)

    def test_breeze_is_refused(self):
        self.assert_refused(self.node.cmd_set_breeze, {'value': '4'})
        self.assertFalse(self.device.breezeless)

    def test_rate_select_is_refused(self):
        self.assert_refused(self.node.cmd_set_rate, {'value': '40'})
        self.assertEqual(self.device.rate_select, AC.RateSelect.OFF)

    def test_aux_heat_is_refused(self):
        self.assert_refused(self.node.cmd_set_aux, {'value': '1'})
        self.assertEqual(self.device.aux_mode, AC.AuxHeatMode.OFF)

    def test_self_clean_is_refused(self):
        self.node.cmd_self_clean()
        self.assertEqual(self.device.self_cleaned, 0)

    def test_unsupported_swing_mode_is_refused(self):
        # This unit reports only OFF and VERTICAL.
        self.assert_refused(self.node.cmd_set_swing, {'value': '3'})
        self.assert_refused(self.node.cmd_set_swing, {'value': '15'})
        self.assertEqual(self.device.swing_mode, AC.SwingMode.OFF)

    def test_supported_swing_mode_still_works(self):
        self.node.cmd_set_swing({'value': '12'})
        self.assertEqual(self.device.swing_mode, AC.SwingMode.VERTICAL)

    def test_unsupported_mode_is_refused(self):
        # SMART_DRY is not in this unit's list.
        self.assert_refused(self.node.cmd_set_mode, {'value': '6'})
        self.assertEqual(self.device.operational_mode,
                         AC.OperationalMode.COOL)

    def test_turning_a_gated_feature_off_is_always_allowed(self):
        """OFF is how a feature gets cleared, so it must not be blocked."""
        self.node.cmd_set_rate({'value': '100'})
        self.assertEqual(self.device.applied, 1)
        self.node.cmd_set_aux({'value': '0'})
        self.assertEqual(self.device.applied, 2)

    def test_a_refused_command_does_not_spoil_later_ones(self):
        """The bug this gating exists to prevent.

        An unsupported rate select used to stay set on the device object, so
        msmart re-sent it with every later command and warned about it every
        time.
        """
        self.node.cmd_set_rate({'value': '40'})
        self.assertEqual(self.device.rate_select, AC.RateSelect.OFF)

        self.node.cmd_don()
        self.assertTrue(self.device.power_state)
        self.assertEqual(self.device.rate_select, AC.RateSelect.OFF)

    def test_supported_features_are_untouched(self):
        self.node.cmd_set_turbo({'value': '1'})
        self.assertTrue(self.device.turbo)
        self.node.cmd_set_fan_percent({'value': '55'})
        self.assertEqual(self.device.fan_speed, 55)
        self.node.cmd_set_vertical_angle({'value': '50'})
        self.assertEqual(self.device.vertical_swing_angle,
                         AC.SwingAngle.POS_3)

    def test_commands_before_connection_are_ignored(self):
        self.node.device = None
        self.node.cmd_set_mode({'value': '2'})
        self.node.cmd_set_eco({'value': '1'})
        self.node.cmd_self_clean()


class TestUnsupportedDrivers(unittest.TestCase):
    """Readings a unit has no hardware for, derived from its capabilities."""

    def setUp(self):
        RUNNER.start()
        _, self.node = build_node()
        self.device = self.node.device

    def test_matches_the_real_capability_report(self):
        from nodes.ac import unsupported_drivers
        hidden = unsupported_drivers(self.device.serialize_capabilities())

        # Absent on this unit.
        for driver in ('GV6', 'GV7', 'GV10', 'GV12', 'GV15', 'GV17', 'GV18',
                       'GV19', 'GV20', 'GV21', 'GV22', 'CLIHUM', 'GV3'):
            self.assertIn(driver, hidden, f'{driver} should be hidden')

        # Present on this unit.
        for driver in ('ST', 'CLITEMP', 'CLISPC', 'CLIMD', 'CLIFS', 'GV2',
                       'GV5', 'GV8', 'GV11', 'GV14'):
            self.assertNotIn(driver, hidden, f'{driver} should be kept')

    def test_swing_with_only_off_is_hidden(self):
        from nodes.ac import unsupported_drivers
        self.assertNotIn("GV4", unsupported_drivers(self.device.serialize_capabilities()))

        self.device.supported_swing_modes = [AC.SwingMode.OFF]
        self.assertIn("GV4", unsupported_drivers(self.device.serialize_capabilities()))

    def test_every_hidden_driver_is_a_real_driver(self):
        from nodes.ac import unsupported_drivers
        known = {d['driver'] for d in MideaACNode.drivers}
        self.assertLessEqual(unsupported_drivers(self.device.serialize_capabilities()), known)


class TestCapabilityLearning(unittest.TestCase):
    """What a unit reports it cannot do is remembered across restarts."""

    def setUp(self):
        RUNNER.start()
        self.polyglot = udi_interface.Interface([])
        self.controller = Controller(
            self.polyglot, 'controller', 'controller', 'Midea AC')
        self.address = address_for(151732604872862)

        # Never let a test rewrite the profile that ships in the repository.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.profile_dir = tempfile.mkdtemp()
        for part, name in (('nodedef', 'nodedefs.xml'), ('nls', 'en_us.txt')):
            os.makedirs(os.path.join(self.profile_dir, part))
            shutil.copy(os.path.join(root, 'profile', part, name),
                        os.path.join(self.profile_dir, part, name))
        self.controller.profile_dir = self.profile_dir

    def tearDown(self):
        shutil.rmtree(self.profile_dir, ignore_errors=True)

    def test_learning_stores_and_raises_a_notice(self):
        self.controller.learn_capabilities(self.address, {'GV6', 'GV7'})

        self.assertEqual(self.controller.capability_cache[self.address],
                         {'GV6', 'GV7'})
        self.assertEqual(self.controller.Data['capabilities'],
                         {self.address: ['GV6', 'GV7']})
        self.assertTrue(self.controller.Notices)

    def test_learning_the_same_thing_twice_is_quiet(self):
        self.controller.learn_capabilities(self.address, {'GV6'})
        self.controller.Notices.clear()
        self.controller.learn_capabilities(self.address, {'GV6'})
        self.assertFalse(self.controller.Notices)

    def test_remembered_capabilities_are_reloaded(self):
        self.controller.data_handler(
            {'capabilities': {self.address: ['GV6', 'GV18']}})
        self.assertEqual(self.controller.capability_cache[self.address],
                         {'GV6', 'GV18'})

    def test_remembered_capabilities_hide_rows(self):
        self.controller.data_handler(
            {'capabilities': {self.address: ['GV6', 'GV18']}})
        hidden = self.controller.hidden_for({'address': self.address})
        self.assertEqual(hidden, frozenset({'GV6', 'GV18'}))

    def test_auto_hide_can_be_turned_off(self):
        self.controller.parameter_handler({'auto_hide_unsupported': 'false'})
        self.controller.data_handler(
            {'capabilities': {self.address: ['GV6']}})
        self.assertEqual(
            self.controller.hidden_for({'address': self.address}),
            frozenset())

    def test_manual_and_learned_hiding_combine(self):
        self.controller.parameter_handler({'hide_drivers': 'total_energy'})
        self.controller.data_handler(
            {'capabilities': {self.address: ['GV6']}})
        self.assertEqual(
            self.controller.hidden_for({'address': self.address}),
            frozenset({'GV6', 'GV21'}))

    def test_node_picks_up_learned_capabilities(self):
        self.controller.data_handler(
            {'capabilities': {self.address: ['GV6', 'GV7']}})
        config = {'ip': '10.1.1.39', 'port': 6444, 'id': 151732604872862,
                  'address': self.address, 'name': 'Bedroom'}
        node = MideaACNode(self.polyglot, 'controller', self.address,
                           'Bedroom', config, self.controller)

        self.assertEqual(node.hidden, {'GV6', 'GV7'})
        self.assertNotIn('GV6', {d['driver'] for d in node.drivers})
        self.assertNotEqual(node.id, 'MIDEAAC')

    def test_learning_applies_without_waiting_for_a_restart(self):
        """The node moves onto its new definition as soon as it connects."""
        config = {'ip': '10.1.1.39', 'port': 6444, 'id': 151732604872862,
                  'address': self.address, 'name': 'Bedroom'}
        node = MideaACNode(self.polyglot, 'controller', self.address,
                           'Bedroom', config, self.controller)
        self.polyglot.addNode(node)
        self.assertEqual(node.id, 'MIDEAAC')

        self.controller.learn_capabilities(self.address, {'GV15', 'GV7'})
        node.apply_hidden(self.controller.hidden_for(config))

        self.assertEqual(node.hidden, {'GV15', 'GV7'})
        self.assertNotEqual(node.id, 'MIDEAAC')
        self.assertNotIn('GV15', {d['driver'] for d in node.drivers})

    def test_applying_the_same_hidden_set_is_a_no_op(self):
        config = {'address': self.address, 'name': 'Bedroom',
                  'ip': '10.1.1.39', 'id': 151732604872862}
        node = MideaACNode(self.polyglot, 'controller', self.address,
                           'Bedroom', config, self.controller)
        before = node.id
        node.apply_hidden(set())
        self.assertEqual(node.id, before)

    def test_manual_hiding_survives_learning(self):
        """The real case: a hand written hide list plus what the unit reports.

        The live profile on real hardware hid defrost and outdoor coil
        temperature, which no capability implies, so they came from
        hide_drivers. Learning must add to that, not replace it.
        """
        self.controller.parameter_handler(
            {'hide_drivers': 'defrost, outdoor_coil_temperature'})
        self.controller.learn_capabilities(self.address, {'GV15', 'GV7'})

        hidden = self.controller.hidden_for({'address': self.address})
        self.assertEqual(hidden, frozenset({'GV24', 'GV27', 'GV15', 'GV7'}))

    def test_profile_variants_cover_remembered_devices(self):
        self.controller.data_handler(
            {'capabilities': {self.address: ['GV6']}})
        # build_profile writes into the real profile directory, so just check
        # the variant set it would use.
        variants = {frozenset(self.controller.hidden_drivers)}
        for address in self.controller.capability_cache:
            variants.add(self.controller.hidden_for({'address': address}))
        self.assertIn(frozenset({'GV6'}), variants)


class TestHiddenDrivers(unittest.TestCase):
    """Drivers the user does not want on a node are never reported."""

    def setUp(self):
        RUNNER.start()
        self.polyglot = udi_interface.Interface([])
        self.controller = Controller(
            self.polyglot, 'controller', 'controller', 'Midea AC')

    def build(self, config_extra=None):
        config = {'ip': '10.1.1.39', 'port': 6444, 'id': 151732604872862,
                  'token': None, 'key': None, 'version': 3, 'name': 'Bedroom'}
        config.update(config_extra or {})
        node = MideaACNode(self.polyglot, 'controller',
                           address_for(config['id']), 'Bedroom',
                           config, self.controller)
        node.device = FakeDevice()
        node.capabilities_read = True
        return node

    def test_no_hiding_by_default(self):
        node = self.build()
        self.assertEqual(node.hidden, set())
        self.assertEqual(len(node.drivers), len(MideaACNode.drivers))

    def test_hide_by_driver_id(self):
        self.controller.parameter_handler({'hide_drivers': 'GV6, GV5'})
        node = self.build()
        self.assertEqual(node.hidden, {'GV5', 'GV6'})
        published = {d['driver'] for d in node.drivers}
        self.assertNotIn('GV6', published)
        self.assertIn('GV4', published)

    def test_hide_by_friendly_name(self):
        self.controller.parameter_handler(
            {'hide_drivers': 'horizontal_louver, Vertical Louver'})
        node = self.build()
        self.assertEqual(node.hidden, {'GV5', 'GV6'})

    def test_hidden_drivers_are_never_reported(self):
        self.controller.parameter_handler({'hide_drivers': 'GV6'})
        node = self.build()
        node.publish()
        # publish() would otherwise have written GV6 from the device state.
        self.assertNotIn('GV6', node.driver_values)

    def test_per_device_hide_field(self):
        node = self.build({'hide': 'GV21,GV22'})
        self.assertEqual(node.hidden, {'GV21', 'GV22'})

    def test_global_and_per_device_hiding_combine(self):
        self.controller.parameter_handler({'hide_drivers': 'GV6'})
        node = self.build({'hide': 'total_energy'})
        self.assertEqual(node.hidden, {'GV6', 'GV21'})

    def test_hide_is_parsed_from_a_device_parameter(self):
        self.controller.parameter_handler({
            'Bedroom': 'ip=10.1.1.39; id=151732604872862; hide=GV5,GV6'})
        self.assertEqual(
            self.controller.configured['Bedroom']['hide'], 'GV5,GV6')

    def test_commas_inside_a_value_survive(self):
        """A comma is a list separator inside a field, not a field separator."""
        self.controller.parameter_handler({
            'Bedroom': ('ip=10.1.1.39; id=151732604872862; '
                        'hide=vertical_louver,horizontal_louver')})
        config = self.controller.configured['Bedroom']
        self.assertEqual(config['hide'],
                         'vertical_louver,horizontal_louver')
        self.assertEqual(config['ip'], '10.1.1.39')

        node = self.build(config)
        self.assertEqual(node.hidden, {'GV5', 'GV6'})

    def test_unknown_driver_names_are_dropped(self):
        """server.json seeds hide_drivers with a placeholder; a name that is
        not a real reading must not create a node definition variant."""
        self.controller.parameter_handler({'hide_drivers': 'GV99'})
        self.assertEqual(self.controller.hidden_drivers, set())

        node = self.build()
        self.assertEqual(node.hidden, set())
        self.assertEqual(node.id, 'MIDEAAC')
        self.assertEqual(len(node.drivers), len(MideaACNode.drivers))

    def test_unknown_names_do_not_spoil_valid_ones(self):
        self.controller.parameter_handler(
            {'hide_drivers': 'GV99, horizontal_louver, nonsense'})
        self.assertEqual(self.controller.hidden_drivers, {'GV6'})

    def test_server_json_default_hides_nothing(self):
        import json
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'server.json')) as handle:
            defaults = json.load(handle)['customParams']

        self.controller.parameter_handler(defaults)
        self.assertEqual(self.controller.hidden_drivers, set())

    def test_every_driver_has_a_friendly_alias(self):
        from nodes.ac import DRIVER_ALIASES
        self.assertEqual(
            set(DRIVER_ALIASES.values()),
            {d['driver'] for d in MideaACNode.drivers})


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

    def test_credentials_survive_a_failed_probe(self):
        """A configured unit found only by broadcast keeps its token and key."""
        self.controller.parameter_handler({
            'Bedroom': ('ip=10.1.1.39; token=AABB; key=CCDD')})
        # No probe_result, so the probe fails and the entry has no id.
        self.broadcast_result = [self.found(151732604872862, '10.1.1.39')]

        self.controller.discover()

        node = self.controller.nodes_by_address[
            address_for(151732604872862)]
        self.assertEqual(node.config['token'], 'AABB')
        self.assertEqual(node.config['key'], 'CCDD')
        self.assertEqual(node.config['id'], 151732604872862)

    def test_unreachable_device_without_an_id_raises_a_notice(self):
        self.controller.parameter_handler({'Bedroom': 'ip=10.1.1.39'})
        self.controller.discover()
        self.assertEqual(self.controller.nodes_by_address, {})
        self.assertTrue(self.controller.Notices)

    def test_discovery_supported_flag_does_not_block_node_creation(self):
        """Regression: msmart reports supported=False for every discovery.

        Discovery runs with auto_connect=False so the Midea cloud is never
        contacted, which means refresh() never runs and Device.supported is
        still False. Treating that as "unsupported" refused to create nodes
        for perfectly good units.
        """
        self.broadcast_result = [
            self.found(151732604872862, '10.1.1.39', supported=False)]
        self.controller.discover()

        self.assertIn(address_for(151732604872862),
                      self.controller.nodes_by_address)
        self.assertFalse(
            [text for text in self.controller.Notices.values()
             if 'not supported' in text])

    def test_device_info_carries_no_supported_field(self):
        """The flag is meaningless at discovery time, so it is not recorded."""
        class FakeDiscovered:
            id = 151732604872862
            ip = '10.1.1.39'
            port = 6444
            version = 3
            name = 'net_ac_E1E8'
            sn = 'SN'
            type = 'AIR_CONDITIONER'
            supported = False          # what msmart actually reports here

        info = self.controller._device_info(FakeDiscovered())
        self.assertNotIn('supported', info)
        self.assertEqual(info['id'], 151732604872862)

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
