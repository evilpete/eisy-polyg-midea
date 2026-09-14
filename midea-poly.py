#!/usr/bin/env python3
"""
Universal Devices EISY / Polisy - Polyglot v3 node server for Midea
(and associated brand) smart air conditioners.

Uses the msmart-ng library for local LAN control:
    https://github.com/mill1000/midea-msmart
"""

import sys

import udi_interface

LOGGER = udi_interface.LOGGER
VERSION = '1.0.0'


def main():
    polyglot = None
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start(VERSION)

        # Importing here keeps a missing msmart install from killing the
        # process before the interface can report the problem.
        from nodes import Controller

        Controller(polyglot, 'controller', 'controller', 'Midea AC')

        polyglot.runForever()
    except (KeyboardInterrupt, SystemExit):
        LOGGER.warning('Received interrupt, exiting')
        if polyglot is not None:
            polyglot.stop()
        sys.exit(0)
    except ImportError as ex:
        LOGGER.error('Missing dependency: %s. Check that requirements.txt '
                     'installed correctly (msmart-ng).', ex)
        if polyglot is not None:
            polyglot.stop()
        sys.exit(1)
    except Exception:
        LOGGER.exception('Node server failed to start')
        if polyglot is not None:
            polyglot.stop()
        sys.exit(1)


if __name__ == '__main__':
    main()
