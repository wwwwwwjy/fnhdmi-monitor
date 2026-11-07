"""The branded release must never install an upstream package over its extensions."""
import tempfile
import unittest
from unittest.mock import patch
from fnm_support import load_server


class ProductUpdateTests(unittest.TestCase):
    def test_saved_auto_update_cannot_replace_product(self):
        m = load_server()
        with tempfile.TemporaryDirectory() as data, patch.object(m.UpdateManager, 'start_auto_job', side_effect=AssertionError('upstream auto job')):
            updater = m.ProductUpdateManager(data)
            updater.start_auto_job(True, True)
            result = updater.check(force=True)
            self.assertTrue(result['manual'])
            self.assertFalse(result['has_update'])
            self.assertIsNone(result['asset'])
            self.assertIsNone(updater._job)
            self.assertFalse(updater.install_latest()['ok'])
            self.assertFalse(updater.install_fpk('/nonexistent/upstream.fpk')[0])


if __name__ == '__main__':
    unittest.main()
