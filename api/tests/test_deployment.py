import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('deployment', ROOT / 'scripts/prepare_deployment.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


class DeploymentTests(unittest.TestCase):
    def test_package_has_only_allowed_files_and_config_at_root(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'publish'
            deployment.prepare(target)
            expected = {f'{folder}/{name}' for folder, names in deployment.FILES.items() for name in names}
            actual = {str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()}
            self.assertEqual(actual, expected)
            self.assertTrue((target / 'frontend/staticwebapp.config.json').is_file())
            (target / 'api/local.settings.json').write_text('must disappear')
            deployment.prepare(target)
            self.assertFalse((target / 'api/local.settings.json').exists())
