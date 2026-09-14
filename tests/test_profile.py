#!/usr/bin/env python3
"""
Validates the ISY profile: XML is well formed, every editor referenced by a
nodedef exists, and every driver, command and index value has an NLS entry.

    python3 tests/test_profile.py
"""

import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, 'profile')


def load_nls():
    entries = {}
    with open(os.path.join(PROFILE, 'nls', 'en_us.txt')) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            entries[key.strip()] = value.strip()
    return entries


class TestProfile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.nodedefs = ET.parse(
            os.path.join(PROFILE, 'nodedef', 'nodedefs.xml')).getroot()
        cls.editors = ET.parse(
            os.path.join(PROFILE, 'editor', 'editors.xml')).getroot()
        cls.nls = load_nls()
        cls.editor_ids = {e.get('id') for e in cls.editors.findall('editor')}

    def test_every_referenced_editor_exists(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            for element in nodedef.iter():
                editor = element.get('editor')
                if editor:
                    self.assertIn(
                        editor, self.editor_ids,
                        f'{nodedef.get("id")} references missing editor {editor}')

    def test_every_editor_is_used(self):
        used = set()
        for element in self.nodedefs.iter():
            if element.get('editor'):
                used.add(element.get('editor'))
        self.assertEqual(self.editor_ids - used, set(),
                         'unused editors left in editors.xml')

    def test_node_and_driver_names(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            nls = nodedef.get('nls')
            self.assertTrue(nls, f'{nodedef.get("id")} has no nls prefix')
            self.assertIn(f'ND-{nls}-NAME', self.nls)
            self.assertIn(f'ND-{nls}-ICON', self.nls)

            for st in nodedef.iter('st'):
                key = f'ST-{nls}-{st.get("id")}-NAME'
                self.assertIn(key, self.nls, f'missing NLS entry {key}')

    def test_command_names(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            nls = nodedef.get('nls')
            accepts = nodedef.find('.//accepts')
            for cmd in accepts.findall('cmd'):
                key = f'CMD-{nls}-{cmd.get("id")}-NAME'
                self.assertIn(key, self.nls, f'missing NLS entry {key}')

    def test_index_editor_values_have_labels(self):
        for editor in self.editors.findall('editor'):
            for rng in editor.findall('range'):
                nls_prefix = rng.get('nls')
                if not nls_prefix:
                    continue
                for value in self._expand_subset(rng.get('subset')):
                    key = f'{nls_prefix}-{value}'
                    self.assertIn(key, self.nls, f'missing NLS entry {key}')

    def test_no_orphan_index_labels(self):
        """Every M_*-<n> label must belong to an editor subset."""
        declared = set()
        for editor in self.editors.findall('editor'):
            for rng in editor.findall('range'):
                prefix = rng.get('nls')
                if prefix:
                    for value in self._expand_subset(rng.get('subset')):
                        declared.add(f'{prefix}-{value}')

        for key in self.nls:
            if re.match(r'^M_[A-Z]+-\d+$', key):
                self.assertIn(key, declared, f'orphan NLS entry {key}')

    def test_drivers_match_node_classes(self):
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
        sys.path.insert(1, ROOT)
        from nodes.ac import MideaACNode
        from nodes.controller import Controller

        for node_class in (Controller, MideaACNode):
            nodedef = next(n for n in self.nodedefs.findall('nodeDef')
                           if n.get('id') == node_class.id)
            profile_drivers = {st.get('id') for st in nodedef.iter('st')}
            code_drivers = {d['driver'] for d in node_class.drivers}
            self.assertEqual(
                profile_drivers, code_drivers,
                f'{node_class.id} drivers differ between profile and code')

    def test_commands_match_node_classes(self):
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
        sys.path.insert(1, ROOT)
        from nodes.ac import MideaACNode
        from nodes.controller import Controller

        for node_class in (Controller, MideaACNode):
            nodedef = next(n for n in self.nodedefs.findall('nodeDef')
                           if n.get('id') == node_class.id)
            profile_cmds = {c.get('id')
                            for c in nodedef.find('.//accepts').findall('cmd')}
            code_cmds = set(node_class.commands)
            self.assertEqual(
                profile_cmds, code_cmds,
                f'{node_class.id} commands differ between profile and code')

    def test_command_init_drivers_exist(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            drivers = {st.get('id') for st in nodedef.iter('st')}
            for param in nodedef.iter('p'):
                init = param.get('init')
                if init:
                    self.assertIn(init, drivers,
                                  f'init="{init}" is not a driver of '
                                  f'{nodedef.get("id")}')

    # ---- structural rules learned from a working PG3 profile -------------

    def test_command_parameters_have_named_ids(self):
        """An empty <p id=""> stops the Admin Console sending the command."""
        for nodedef in self.nodedefs.findall('nodeDef'):
            for param in nodedef.iter('p'):
                self.assertTrue(
                    (param.get('id') or '').strip(),
                    f'{nodedef.get("id")} has a command parameter with no id')

    def test_command_parameters_have_nls_names(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            for param in nodedef.iter('p'):
                key = f'CMDP-{param.get("id")}-NAME'
                self.assertIn(key, self.nls, f'missing NLS entry {key}')

    def test_parameterised_commands_have_a_format_string(self):
        """Without PGM-CMD-<id>-FMT the Admin Console will not offer the
        command at all, which is how every settable control went missing."""
        for nodedef in self.nodedefs.findall('nodeDef'):
            accepts = nodedef.find('.//accepts')
            for cmd in accepts.findall('cmd'):
                if not cmd.findall('p'):
                    continue
                key = f'PGM-CMD-{cmd.get("id")}-FMT'
                self.assertIn(key, self.nls, f'missing NLS entry {key}')

    def test_format_strings_name_their_parameters(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            accepts = nodedef.find('.//accepts')
            for cmd in accepts.findall('cmd'):
                params = cmd.findall('p')
                if not params:
                    continue
                fmt = self.nls[f'PGM-CMD-{cmd.get("id")}-FMT']
                for param in params:
                    self.assertIn(
                        f'/{param.get("id")}/', fmt,
                        f'{cmd.get("id")} format string does not mention '
                        f'parameter {param.get("id")}')

    def test_nodedefs_declare_an_editors_element(self):
        for nodedef in self.nodedefs.findall('nodeDef'):
            self.assertIsNotNone(
                nodedef.find('editors'),
                f'{nodedef.get("id")} is missing its <editors /> element')

    def test_driver_defaults_are_inside_their_editor_range(self):
        """A default outside its editor's range leaves nothing valid to show."""
        sys.path.insert(0, os.path.join(ROOT, 'tests', 'stubs'))
        sys.path.insert(1, ROOT)
        from nodes.ac import MideaACNode
        from nodes.controller import Controller

        editors = {e.get('id'): e for e in self.editors.findall('editor')}

        for node_class in (Controller, MideaACNode):
            nodedef = next(n for n in self.nodedefs.findall('nodeDef')
                           if n.get('id') == node_class.id)
            driver_editor = {st.get('id'): st.get('editor')
                             for st in nodedef.iter('st')}

            for driver in node_class.drivers:
                editor = editors[driver_editor[driver['driver']]]
                self.assertTrue(
                    self._value_in_editor(
                        driver['value'], driver['uom'], editor),
                    f'{node_class.id} driver {driver["driver"]} defaults to '
                    f'{driver["value"]} (uom {driver["uom"]}), outside '
                    f'editor {editor.get("id")}')

    def _value_in_editor(self, value, uom, editor):
        ranges = [r for r in editor.findall('range')
                  if int(r.get('uom')) == int(uom)]
        if not ranges:
            # The driver reports a uom the editor does not declare.
            return False

        for rng in ranges:
            subset = rng.get('subset')
            if subset:
                if value in self._expand_subset(subset):
                    return True
                continue
            low, high = rng.get('min'), rng.get('max')
            if low is None or high is None:
                return True
            if float(low) <= float(value) <= float(high):
                return True
        return False

    @staticmethod
    def _expand_subset(subset):
        values = []
        if not subset:
            return values
        for part in subset.split(','):
            part = part.strip()
            if '-' in part:
                low, _, high = part.partition('-')
                values.extend(range(int(low), int(high) + 1))
            elif part:
                values.append(int(part))
        return values


if __name__ == '__main__':
    unittest.main(verbosity=2)
