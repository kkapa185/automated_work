"""Run the whole suite: python3 tests/run_all.py"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, 'tests'),
                                                top_level_dir=ROOT)
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)
