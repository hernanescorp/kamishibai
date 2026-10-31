"""Stage an allowlisted SWA source package; never copy local settings or venv."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'frontend': ('index.html', 'login.html', 'acceso-denegado.html', 'staticwebapp.config.json'),
    'api': ('function_app.py', 'host.json', 'requirements.txt', '.funcignore'),
}


def prepare(destination=None):
    destination = Path(destination) if destination else ROOT / '.swa-publish'
    if destination.exists():
        shutil.rmtree(destination)
    for folder, names in FILES.items():
        target = destination / folder
        target.mkdir(parents=True)
        for name in names:
            shutil.copyfile(ROOT / folder / name, target / name)
    config = json.loads((destination / 'frontend/staticwebapp.config.json').read_text())
    assert config['platform']['apiRuntime'] == 'python:3.11'
    assert next(rule for rule in config['routes'] if rule['route'] == '/api/*')['allowedRoles'] == ['propietario']
    print('SWA source package ready; runtime ODBC availability remains unverified.')


if __name__ == '__main__':
    prepare()
