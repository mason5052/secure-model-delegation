"""Collect public dependencies as files without importing model modules at build time."""

import os
import sysconfig
from pathlib import Path

project = Path(SPECPATH).parent
site = Path(sysconfig.get_path('purelib'))
standard = Path(sysconfig.get_path('stdlib'))
datas = []
binaries = []
excluded = {'__pycache__', 'tests', 'test', 'pytest', '_pytest', 'pip', 'setuptools',
            'PyInstaller', '_pyinstaller_hooks_contrib', 'altgraph', 'macholib',
            'torch', 'torchvision', 'tensorflow', 'matplotlib', 'idlelib', 'ensurepip',
            'turtledemo', 'tkinter', 'venv', 'site-packages', 'config-3.12-darwin'}


def collect(root, target, exclude):
    for source in root.rglob('*'):
        relative = source.relative_to(root)
        if set(relative.parts) & exclude or source.suffix in {'.pyc', '.pyo'} or not source.is_file():
            continue
        destination = str(Path(target) / relative.parent)
        if source.suffix in {'.so', '.dylib'}:
            binaries.append((str(source), destination))
        else:
            datas.append((str(source), destination))


collect(site, 'site-packages', excluded - {'site-packages'})
collect(standard, '.', {'__pycache__', 'tests', 'test', 'site-packages', 'lib-dynload',
                        'idlelib', 'ensurepip', 'turtledemo', 'tkinter', 'venv', 'config-3.12-darwin'})
collect(standard / 'lib-dynload', 'lib-dynload', set())
datas.append((str(site / 'mlx/lib/mlx.metallib'), 'mlx/lib'))
analysis = Analysis([str(project / 'desktop' / 'mlx-entry.py')], pathex=[],
                    binaries=binaries, datas=datas, hiddenimports=[], hookspath=[],
                    hooksconfig={}, runtime_hooks=[], excludes=['torch', 'tensorflow', 'tkinter'],
                    noarchive=False, optimize=0)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
                 name='smd-mlx-runtime', debug=False, bootloader_ignore_signals=False,
                 strip=False, upx=False, console=True, target_arch='arm64',
                 codesign_identity=None, entitlements_file=None)
collection = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False,
                     name='smd-mlx-runtime')
