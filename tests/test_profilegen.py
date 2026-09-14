#!/usr/bin/env python3
"""
Tests for runtime profile generation.

The ISY draws a node's rows from the profile, so hiding a reading means giving
the node a definition that does not contain it.
"""

import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'stubs'))
sys.path.insert(1, ROOT)

from nodes import profilegen  # noqa: E402
from nodes.ac import DRIVER_COMMANDS  # noqa: E402


class TestProfileGen(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for part, name in (('nodedef', 'nodedefs.xml'), ('nls', 'en_us.txt')):
            os.makedirs(os.path.join(self.dir, part))
            shutil.copy(os.path.join(ROOT, 'profile', part, name),
                        os.path.join(self.dir, part, name))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def nodedefs(self):
        return ET.parse(
            os.path.join(self.dir, 'nodedef', 'nodedefs.xml')).getroot()

    def nls(self):
        with open(os.path.join(self.dir, 'nls', 'en_us.txt')) as handle:
            return handle.read()

    def ids(self):
        return {n.get('id') for n in self.nodedefs().findall('nodeDef')}

    def test_variant_id_is_stable_and_distinct(self):
        first = profilegen.variant_id({'GV5', 'GV6'})
        self.assertEqual(first, profilegen.variant_id({'GV6', 'GV5'}))
        self.assertNotEqual(first, profilegen.variant_id({'GV6'}))
        self.assertEqual(profilegen.variant_id(set()), 'MIDEAAC')
        self.assertTrue(profilegen.VARIANT_RE.match(first))

    def test_nothing_to_hide_changes_nothing(self):
        before = self.nls()
        changed = profilegen.regenerate(
            self.dir, {frozenset()}, DRIVER_COMMANDS)
        self.assertFalse(changed)
        self.assertEqual(self.nls(), before)
        self.assertEqual(self.ids(), {'MIDEACTRL', 'MIDEAAC'})

    def test_variant_omits_hidden_rows_and_their_commands(self):
        hidden = frozenset({'GV6'})
        profilegen.regenerate(self.dir, {hidden}, DRIVER_COMMANDS)

        node_id = profilegen.variant_id(hidden)
        self.assertIn(node_id, self.ids())

        variant = next(n for n in self.nodedefs().findall('nodeDef')
                       if n.get('id') == node_id)
        drivers = {st.get('id') for st in variant.iter('st')}
        self.assertNotIn('GV6', drivers)
        self.assertIn('GV5', drivers)

        commands = {c.get('id')
                    for c in variant.find('.//accepts').findall('cmd')}
        self.assertNotIn('SETHANGLE', commands)
        self.assertIn('SETVANGLE', commands)
        self.assertIn('DON', commands)

    def test_base_definition_is_never_touched(self):
        original = next(n for n in self.nodedefs().findall('nodeDef')
                        if n.get('id') == 'MIDEAAC')
        before = {st.get('id') for st in original.iter('st')}

        profilegen.regenerate(
            self.dir, {frozenset({'GV6'})}, DRIVER_COMMANDS)

        after_node = next(n for n in self.nodedefs().findall('nodeDef')
                          if n.get('id') == 'MIDEAAC')
        self.assertEqual({st.get('id') for st in after_node.iter('st')},
                         before)

    def test_regeneration_is_idempotent(self):
        variants = {frozenset({'GV6'}), frozenset({'GV5', 'GV21'})}
        profilegen.regenerate(self.dir, variants, DRIVER_COMMANDS)
        first = (self.nls(), self.ids())

        self.assertFalse(
            profilegen.regenerate(self.dir, variants, DRIVER_COMMANDS))
        self.assertEqual((self.nls(), self.ids()), first)

    def test_old_variants_are_removed(self):
        profilegen.regenerate(
            self.dir, {frozenset({'GV6'})}, DRIVER_COMMANDS)
        stale = profilegen.variant_id({'GV6'})
        self.assertIn(stale, self.ids())

        profilegen.regenerate(
            self.dir, {frozenset({'GV21'})}, DRIVER_COMMANDS)
        self.assertNotIn(stale, self.ids())
        self.assertIn(profilegen.variant_id({'GV21'}), self.ids())
        self.assertIn('MIDEAAC', self.ids())

    def test_generated_xml_stays_valid_and_parseable(self):
        profilegen.regenerate(
            self.dir,
            {frozenset({'GV6'}), frozenset({'GV5', 'GV6', 'GV21', 'GV22'})},
            DRIVER_COMMANDS)
        # Would raise if the output were malformed.
        self.nodedefs()

    def test_variant_has_nls_names_for_every_remaining_row(self):
        hidden = frozenset({'GV6'})
        profilegen.regenerate(self.dir, {hidden}, DRIVER_COMMANDS)

        node_id = profilegen.variant_id(hidden)
        nls = {}
        for line in self.nls().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                nls[key.strip()] = value.strip()

        variant = next(n for n in self.nodedefs().findall('nodeDef')
                       if n.get('id') == node_id)

        self.assertIn(f'ND-{node_id}-NAME', nls)
        self.assertIn(f'ND-{node_id}-ICON', nls)
        for st in variant.iter('st'):
            self.assertIn(f'ST-{node_id}-{st.get("id")}-NAME', nls)
        for cmd in variant.find('.//accepts').findall('cmd'):
            self.assertIn(f'CMD-{node_id}-{cmd.get("id")}-NAME', nls)

        # The hidden row's name must not be carried over.
        self.assertNotIn(f'ST-{node_id}-GV6-NAME', nls)

    def test_hidden_command_keeps_its_shared_format_string(self):
        """CMDP and PGM lines are global, so they stay for other variants."""
        profilegen.regenerate(
            self.dir, {frozenset({'GV6'})}, DRIVER_COMMANDS)
        nls = self.nls()
        self.assertIn('PGM-CMD-SETVANGLE-FMT', nls)
        self.assertIn('CMDP-VANGLE-NAME', nls)

    def test_every_mapped_command_exists_in_the_profile(self):
        accepts = next(
            n for n in self.nodedefs().findall('nodeDef')
            if n.get('id') == 'MIDEAAC').find('.//accepts')
        commands = {c.get('id') for c in accepts.findall('cmd')}
        for driver, command in DRIVER_COMMANDS.items():
            self.assertIn(command, commands,
                          f'{driver} maps to unknown command {command}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
