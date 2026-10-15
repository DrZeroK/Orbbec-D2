import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('d2_package',Path(__file__).resolve().parents[1]/'package.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PackageTest(unittest.TestCase):
    def test_reject_unpinned_driver(self):
        with self.assertRaises(ValueError):
            module.patch_driver(b'unknown binary')

    def test_wrong_source_creates_no_output(self):
        root=Path('/unused-d2-test')
        with patch.object(Path,'resolve',return_value=root/'source'), \
             patch.object(Path,'is_symlink',return_value=False), \
             patch.object(Path,'read_bytes',return_value=b'wrong'), \
             patch.object(Path,'mkdir') as mkdir:
            with self.assertRaises(ValueError):
                module.create(root/'source',root/'output')
            mkdir.assert_not_called()

if __name__=='__main__':
    unittest.main()
