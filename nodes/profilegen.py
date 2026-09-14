"""
Generate per-capability node definitions at runtime.

The ISY builds a node's list of rows from the profile, not from what the node
server reports, so a driver that is merely left unreported still shows up as an
empty row. The only way to remove it is to give the node a definition that does
not contain it.

UDI's own plugins handle this by shipping one node definition per capability
combination; with twenty independent optional features that is not practical to
write by hand, so the variants are generated here instead.

The `MIDEAAC` definition shipped in the profile is the template and is never
modified. Variants are added alongside it, named `MIDEAAC` plus a short hash of
the hidden driver list so that a given set of hidden rows always produces the
same definition, and regenerating first removes every previously generated
variant. That makes this safe to run on every start.
"""

import hashlib
import os
import re
import xml.etree.ElementTree as ET

import udi_interface

LOGGER = udi_interface.LOGGER

BASE_NODEDEF = 'MIDEAAC'

# Ids of generated variants, so a regeneration can clear out the previous run.
VARIANT_RE = re.compile(r'^' + BASE_NODEDEF + r'[0-9a-f]{6}$')

NLS_MARKER = ('# ==== generated capability variants - '
              'everything below is rewritten ====')


def variant_id(hidden) -> str:
    """A stable node definition id for a given set of hidden drivers."""
    if not hidden:
        return BASE_NODEDEF
    digest = hashlib.md5(','.join(sorted(hidden)).encode()).hexdigest()
    return BASE_NODEDEF + digest[:6]


def _indent(element, level=1):
    """Keep the generated XML readable next to the hand-written definitions."""
    pad = '\n' + '  ' * level
    if len(element):
        if not (element.text or '').strip():
            element.text = pad + '  '
        for child in element:
            _indent(child, level + 1)
        if not (element.tail or '').strip():
            element.tail = pad
        if not (element[-1].tail or '').strip():
            element[-1].tail = pad
    elif level and not (element.tail or '').strip():
        element.tail = pad


def build_nodedefs(source: str, variants, driver_commands) -> str:
    """Return the nodedef XML with one definition per set of hidden drivers."""
    root = ET.fromstring(source)

    base = None
    stale = 0
    for nodedef in list(root.findall('nodeDef')):
        node_id = nodedef.get('id')
        if node_id == BASE_NODEDEF:
            base = nodedef
        elif VARIANT_RE.match(node_id or ''):
            # Left over from a previous run with a different configuration.
            root.remove(nodedef)
            stale += 1

    if base is None:
        raise ValueError(f'{BASE_NODEDEF} is missing from the profile')

    # Nothing to add and nothing to strip: hand back the file untouched rather
    # than rewriting it into an equivalent but differently formatted one.
    if not stale and not any(variants):
        return source

    import copy
    for hidden in sorted(variants, key=lambda h: sorted(h)):
        if not hidden:
            continue

        node_id = variant_id(hidden)
        clone = copy.deepcopy(base)
        clone.set('id', node_id)
        clone.set('nls', node_id)

        sts = clone.find('sts')
        for st in list(sts.findall('st')):
            if st.get('id') in hidden:
                sts.remove(st)

        # A row that is gone should not leave its command behind.
        drop = {driver_commands[d] for d in hidden if d in driver_commands}
        accepts = clone.find('.//accepts')
        for cmd in list(accepts.findall('cmd')):
            if cmd.get('id') in drop:
                accepts.remove(cmd)

        _indent(clone)
        root.append(clone)

    return ET.tostring(root, encoding='unicode')


def build_nls(source: str, variants, driver_commands) -> str:
    """Return the NLS file with names for every generated variant."""
    if not any(variants) and NLS_MARKER not in source:
        return source

    base = source.split(NLS_MARKER)[0].rstrip() + '\n'

    node_lines = {}
    for line in base.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key = stripped.split('=', 1)[0].strip()
        if (key.startswith(f'ND-{BASE_NODEDEF}-')
                or key.startswith(f'ST-{BASE_NODEDEF}-')
                or key.startswith(f'CMD-{BASE_NODEDEF}-')):
            node_lines[key] = stripped.split('=', 1)[1].strip()

    if not any(variants):
        return base

    out = [base, NLS_MARKER, '']
    for hidden in sorted(variants, key=lambda h: sorted(h)):
        if not hidden:
            continue

        node_id = variant_id(hidden)
        drop = {driver_commands[d] for d in hidden if d in driver_commands}
        out.append(f'# {node_id}: without ' + ', '.join(sorted(hidden)))

        for key, value in node_lines.items():
            kind, _, rest = key.partition(f'-{BASE_NODEDEF}-')
            if kind == 'ST' and rest[:-len('-NAME')] in hidden:
                continue
            if kind == 'CMD' and rest[:-len('-NAME')] in drop:
                continue
            out.append(f'{kind}-{node_id}-{rest} = {value}')
        out.append('')

    return '\n'.join(out)


def regenerate(profile_dir: str, variants, driver_commands) -> bool:
    """Rewrite the profile in place. True if anything actually changed."""
    nodedef_path = os.path.join(profile_dir, 'nodedef', 'nodedefs.xml')
    nls_path = os.path.join(profile_dir, 'nls', 'en_us.txt')

    with open(nodedef_path) as handle:
        nodedef_source = handle.read()
    with open(nls_path) as handle:
        nls_source = handle.read()

    nodedefs = build_nodedefs(nodedef_source, variants, driver_commands)
    nls = build_nls(nls_source, variants, driver_commands)

    changed = False
    for path, content, original in ((nodedef_path, nodedefs, nodedef_source),
                                    (nls_path, nls, nls_source)):
        if content != original:
            with open(path, 'w') as handle:
                handle.write(content)
            changed = True

    if changed:
        LOGGER.info('Profile regenerated with %d capability variant(s)',
                    len([h for h in variants if h]))
    return changed
