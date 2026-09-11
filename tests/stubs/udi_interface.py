"""
Minimal stand-in for the real udi_interface package.

Only exists so the node server can be exercised off-box, without a running
Polyglot. It is never imported when the plugin runs on an EISY/Polisy, where
the real package shadows it.
"""

import logging

logging.basicConfig(level=logging.INFO,
                    format='%(levelname)s %(name)s: %(message)s')
LOGGER = logging.getLogger('midea-test')


class Custom(dict):
    def __init__(self, polyglot=None, name=''):
        super().__init__()
        self.name = name

    def load(self, data, save=False):
        self.clear()
        self.update(data or {})

    def dump(self):
        return dict(self)


class Node:
    id = ''
    drivers = []
    commands = {}

    def __init__(self, polyglot, primary, address, name):
        self.poly = polyglot
        self.primary = primary
        self.address = address
        self.name = name
        self.driver_values = {
            d['driver']: d['value'] for d in type(self).drivers}
        self.driver_uoms = {d['driver']: d['uom'] for d in type(self).drivers}

    def setDriver(self, driver, value, report=True, force=False, uom=None):
        self.driver_values[driver] = value
        if uom is not None:
            self.driver_uoms[driver] = uom

    def getDriver(self, driver):
        return self.driver_values.get(driver)

    def reportDrivers(self):
        pass


class Interface:
    START = 'start'
    STOP = 'stop'
    CUSTOMPARAMS = 'customparams'
    CUSTOMDATA = 'customdata'
    CUSTOMNS = 'customns'
    POLL = 'poll'
    DISCOVER = 'discover'
    CONFIGDONE = 'configdone'
    ADDNODEDONE = 'addnodedone'

    def __init__(self, *args, **kwargs):
        self.subscriptions = {}
        self.nodes_dict = {}
        self.started = False

    def start(self, version=None):
        self.started = True

    def ready(self):
        pass

    def subscribe(self, event, callback, address=None):
        self.subscriptions.setdefault(event, []).append((callback, address))

    def addNode(self, node, rename=False):
        self.nodes_dict[node.address] = node

    def getNode(self, address):
        return self.nodes_dict.get(address)

    def nodes(self):
        return list(self.nodes_dict.values())

    def updateProfile(self):
        pass

    def setCustomParamsDoc(self, doc=None):
        pass

    def runForever(self):
        pass

    def stop(self):
        self.started = False
