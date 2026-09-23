"""Requirements-only import smoke, invoked by the workstation lease wrapper."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from weather.paths import REPO_ROOT


IMPORT_CHILD = r'''
import importlib, json, sys
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('network forbidden during import smoke')
    if event == 'open' and isinstance(args[0], str) and args[0].replace('\\', '/').split('/')[-1] == '.env':
        raise RuntimeError('.env forbidden during import smoke')
sys.addaudithook(audit)
try:
    importlib.import_module(sys.argv[1])
except Exception as exc:
    print(json.dumps({'module': sys.argv[1], 'status': 'FAIL', 'exception': type(exc).__name__,
                      'missing_package': getattr(exc, 'name', None), 'message': str(exc)[:200]}))
    sys.exit(1)
print(json.dumps({'module': sys.argv[1], 'status': 'PASS'}))
'''


def smoke(*, require_re1=True):
    if os.name != 'nt' or os.environ.get('WEATHER_WORKSTATION_WRAPPER_ACTIVE') != '1':
        raise RuntimeError('run through scripts/ops/fresh_venv_smoke.ps1 on the assigned workstation')
    scratch = REPO_ROOT / 'scratch'
    scratch.mkdir(exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix='fresh-venv-', dir=scratch)).resolve()
    failed = False
    try:
        subprocess.run([sys.executable, '-m', 'venv', str(target)], check=True, timeout=120)
        python = target / 'Scripts/python.exe'
        install = subprocess.run([
            str(python), '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
            '--no-input', '--index-url', 'https://pypi.org/simple', '-r', str(REPO_ROOT / 'requirements.txt'),
        ], timeout=900, capture_output=True, text=True)
        if install.returncode:
            print(json.dumps({'step': 'requirements_install', 'status': 'FAIL',
                              'message': install.stderr[-2000:]}), flush=True)
            return 1
        print(json.dumps({'step': 'requirements_install', 'status': 'PASS'}), flush=True)
        modules = sorted(path for pattern in ('mm_*.py', 're1_*.py')
                         for path in (REPO_ROOT / 'src/weather/market').glob(pattern))
        re1_count = sum(path.name.startswith('re1_') for path in modules)
        print(json.dumps({'step': 'module_inventory', 'mm': len(modules) - re1_count, 're1': re1_count,
                          'status': 'FAIL' if require_re1 and not re1_count else 'PASS'}), flush=True)
        failed = require_re1 and not re1_count
        child_env = os.environ.copy()
        child_env['PYTHONPATH'] = str(REPO_ROOT / 'src')
        child_env['PYTHONNOUSERSITE'] = '1'
        for path in modules:
            module = 'weather.market.' + path.stem
            try:
                result = subprocess.run([str(python), '-c', IMPORT_CHILD, module], cwd=target,
                                        env=child_env, capture_output=True, text=True, timeout=30)
                print(result.stdout.strip() or json.dumps({'module': module, 'status': 'FAIL',
                                                          'message': result.stderr[-200:]}), flush=True)
                failed |= result.returncode != 0
            except subprocess.TimeoutExpired:
                print(json.dumps({'module': module, 'status': 'FAIL', 'message': 'import timed out'}), flush=True)
                failed = True
        return int(failed)
    finally:
        # Delete only this invocation's random, direct scratch child. Reject
        # reparse points throughout the tree before recursive deletion.
        if target.parent != scratch.resolve() or not target.name.startswith('fresh-venv-'):
            raise RuntimeError('unsafe temporary venv cleanup target')
        import stat
        for directory, dirs, files in os.walk(target, followlinks=False):
            for name in ['.'] + dirs + files:
                entry = Path(directory) / name
                if getattr(entry.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise RuntimeError('refusing cleanup of redirected temporary venv')
        shutil.rmtree(target)
        print(json.dumps({'step': 'venv_cleanup', 'status': 'PASS'}), flush=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    return smoke()


if __name__ == '__main__':
    raise SystemExit(main())
