#!/usr/bin/env python3
"""Run every test in this directory."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'stubs'))
sys.path.insert(1, os.path.dirname(HERE))

if __name__ == '__main__':
    suite = unittest.TestLoader().discover(HERE, pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
