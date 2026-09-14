#!/usr/bin/env python3
"""
Checks the capability mapping against the real msmart library.

`serialize_capabilities()` is the single source of truth for what a unit can
do, and `override_capabilities()` accepts exactly the dict it produces. So a
real AirConditioner can be loaded with a capability report and this plugin's
view of it compared against the library's own supports_* properties.

The report used here is verbatim from real hardware.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'stubs'))
sys.path.insert(1, ROOT)

from msmart.device import AirConditioner as AC  # noqa: E402

from nodes.ac import (BREEZE_CAPABILITIES, CAPABILITY_DRIVERS,  # noqa: E402
                      DRIVER_COMMANDS, MideaACNode, unsupported_drivers)

# net_ac_E1E8, as logged by the plugin.
REAL_REPORT = {
    'min_target_temperature': 16.0,
    'max_target_temperature': 30.0,
    'supported_modes': ['FAN_ONLY', 'DRY', 'COOL', 'HEAT', 'AUTO'],
    'supported_swing_modes': ['OFF', 'VERTICAL'],
    'supported_fan_speeds': ['SILENT', 'LOW', 'MEDIUM', 'HIGH', 'AUTO', 'MAX'],
    'supported_aux_modes': ['OFF'],
    'supported_rate_selects': ['OFF'],
    'additional_capabilities': ['CUSTOM_FAN_SPEED', 'TURBO',
                                'DISPLAY_CONTROL', 'FILTER_REMINDER',
                                'SWING_VERTICAL_ANGLE'],
}

# Each capability flag beside the library property that tests it, so that a
# rename or a change of meaning in msmart is caught here.
FLAG_PROPERTIES = {
    'CUSTOM_FAN_SPEED': 'supports_custom_fan_speed',
    'DISPLAY_CONTROL': 'supports_display_control',
    'ECO': 'supports_eco',
    'FILTER_REMINDER': 'supports_filter_reminder',
    'FREEZE_PROTECTION': 'supports_freeze_protection',
    'FRESH_AIR': 'supports_fresh_air',
    'HUMIDITY': 'supports_humidity',
    'PURIFIER': 'supports_purifier',
    'SELF_CLEAN': 'supports_self_clean',
    'SWING_HORIZONTAL_ANGLE': 'supports_horizontal_swing_angle',
    'SWING_VERTICAL_ANGLE': 'supports_vertical_swing_angle',
    'TARGET_HUMIDITY': 'supports_target_humidity',
    'TURBO': 'supports_turbo',
}


def device_with(report):
    device = AC(ip='10.0.0.1', port=6444, device_id=1)
    device.override_capabilities(report)
    return device


class TestAgainstRealLibrary(unittest.TestCase):

    def setUp(self):
        self.device = device_with(REAL_REPORT)

    def test_report_round_trips_through_the_library(self):
        serialized = self.device.serialize_capabilities()
        for key, value in REAL_REPORT.items():
            if isinstance(value, list):
                self.assertEqual(sorted(serialized[key]), sorted(value), key)
            else:
                self.assertEqual(serialized[key], value, key)

    def test_mapping_agrees_with_the_library(self):
        """Our flag mapping must match msmart's own supports_* properties."""
        report = self.device.serialize_capabilities()
        hidden = unsupported_drivers(report)

        for flag, prop in FLAG_PROPERTIES.items():
            supported = getattr(self.device, prop)
            for driver in CAPABILITY_DRIVERS[flag]:
                if supported:
                    self.assertNotIn(
                        driver, hidden,
                        f'{prop} is True but {driver} was hidden')
                else:
                    self.assertIn(
                        driver, hidden,
                        f'{prop} is False but {driver} was kept')

    def test_breeze_agrees_with_the_library(self):
        hidden = unsupported_drivers(self.device.serialize_capabilities())
        any_breeze = (self.device.supports_breeze_away
                      or self.device.supports_breeze_mild
                      or self.device.supports_breezeless)
        self.assertEqual('GV17' not in hidden, any_breeze)

    def test_breeze_control_implies_all_three(self):
        device = device_with(
            {**REAL_REPORT,
             'additional_capabilities': ['BREEZE_CONTROL']})
        self.assertTrue(device.supports_breeze_away)
        self.assertTrue(device.supports_breeze_mild)
        self.assertTrue(device.supports_breezeless)
        self.assertNotIn(
            'GV17', unsupported_drivers(device.serialize_capabilities()))

    def test_real_unit_hides_what_it_should(self):
        hidden = unsupported_drivers(self.device.serialize_capabilities())
        self.assertEqual(
            hidden,
            # Not GV4: the unit reports OFF and VERTICAL, so it does swing.
            {'CLIHUM', 'GV3', 'GV6', 'GV7', 'GV10', 'GV12', 'GV15',
             'GV17', 'GV18', 'GV19', 'GV20', 'GV21', 'GV22'})

    def test_real_unit_keeps_what_it_has(self):
        hidden = unsupported_drivers(self.device.serialize_capabilities())
        for driver in ('ST', 'GV0', 'CLITEMP', 'GV1', 'CLISPC', 'CLIMD',
                       'CLIFS', 'GV2', 'GV4', 'GV5', 'GV8', 'GV11', 'GV14'):
            self.assertNotIn(driver, hidden)

    def test_a_fully_featured_unit_hides_nothing_capability_based(self):
        every_flag = sorted(set(CAPABILITY_DRIVERS) | set(BREEZE_CAPABILITIES))
        device = device_with({
            **REAL_REPORT,
            'additional_capabilities': every_flag,
            'supported_swing_modes': ['OFF', 'VERTICAL', 'HORIZONTAL', 'BOTH'],
            'supported_rate_selects': ['OFF', 'GEAR_50', 'GEAR_75'],
            'supported_aux_modes': ['OFF', 'AUX_HEAT', 'AUX_ONLY'],
        })
        self.assertEqual(
            unsupported_drivers(device.serialize_capabilities()), set())

    def test_an_empty_report_hides_every_optional_reading(self):
        device = device_with({
            **REAL_REPORT,
            'additional_capabilities': [],
            'supported_swing_modes': ['OFF'],
            'supported_rate_selects': ['OFF'],
            'supported_aux_modes': ['OFF'],
        })
        hidden = unsupported_drivers(device.serialize_capabilities())
        # Never the core climate readings, whatever the report says.
        for driver in ('ST', 'GV0', 'CLITEMP', 'CLISPC', 'CLIMD', 'CLIFS'):
            self.assertNotIn(driver, hidden)

    def test_every_mapped_driver_exists(self):
        known = {d['driver'] for d in MideaACNode.drivers}
        mapped = {d for drivers in CAPABILITY_DRIVERS.values()
                  for d in drivers}
        mapped |= {'GV17', 'GV4', 'GV19', 'GV20'}
        self.assertLessEqual(mapped, known)

    def test_flag_names_are_real_msmart_capabilities(self):
        names = {c.name for c in AC.Capability}
        for flag in set(CAPABILITY_DRIVERS) | set(BREEZE_CAPABILITIES):
            self.assertIn(flag, names, f'{flag} is not an msmart capability')

    def test_hidden_readings_take_their_commands_with_them(self):
        hidden = unsupported_drivers(self.device.serialize_capabilities())
        dropped = {DRIVER_COMMANDS[d] for d in hidden if d in DRIVER_COMMANDS}
        # The commands that failed against real hardware must all be gone.
        for command in ('SETRATE', 'SETHANGLE', 'SETAUX', 'SETFRESH',
                        'SETFREEZE', 'SETECO', 'SETPURIFY', 'SETBREEZE',
                        'SELFCLEAN'):
            self.assertIn(command, dropped)

        # Swing survives, because this unit really does have vertical swing.
        self.assertNotIn('SETSWING', dropped)


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestAgainstLiveNodeDefinition(unittest.TestCase):
    """Checks against a node definition read back from a real ISY.

    The definition captured there was built from a hand written hide_drivers
    list, before the unit's capabilities had been applied, which is why it
    still offered Start Self Clean on a unit with no self clean.
    """

    LIVE_HIDDEN = {'GV3', 'GV6', 'GV10', 'GV12', 'GV19', 'GV24', 'GV27'}

    def test_the_live_definition_came_from_a_manual_list(self):
        """Two of its hidden rows are ones no capability can imply."""
        capability_driven = set()
        for drivers in CAPABILITY_DRIVERS.values():
            capability_driven.update(drivers)
        capability_driven.update({'GV17', 'GV4', 'GV19', 'GV20'})

        self.assertTrue(self.LIVE_HIDDEN - capability_driven,
                        'this set could have come from capabilities alone')

    def test_capabilities_would_have_dropped_self_clean(self):
        device = device_with(REAL_REPORT)
        learned = unsupported_drivers(device.serialize_capabilities())

        self.assertIn('GV15', learned)
        self.assertEqual(DRIVER_COMMANDS['GV15'], 'SELFCLEAN')
        self.assertNotIn('GV15', self.LIVE_HIDDEN)

    def test_combined_set_hides_self_clean(self):
        device = device_with(REAL_REPORT)
        combined = self.LIVE_HIDDEN | unsupported_drivers(
            device.serialize_capabilities())

        self.assertIn('GV15', combined)
        dropped = {DRIVER_COMMANDS[d] for d in combined if d in DRIVER_COMMANDS}
        self.assertIn('SELFCLEAN', dropped)
        # The manual entries are kept alongside the learned ones.
        self.assertIn('GV24', combined)
        self.assertIn('GV27', combined)
