#!/usr/bin/env python3
"""Build public desktop components without copying a workspace or user data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build' / 'desktop'
OPENCODE_VERSION = '1.19.5'
OPENCODE_SHA256 = 'c1c9e62521192192ef4c3ed1355ada2144055bddb61682217e997b03c55203c1'
OPENCODE_URL = f'https://github.com/anomalyco/opencode/releases/download/v{OPENCODE_VERSION}/opencode-darwin-arm64.zip'
LIBREOFFICE_VERSION = '26.8.2'
LIBREOFFICE_SHA256 = '9f24fe83ab1ed5c95eb3df580119f32932f713e577feeac02bf619fb00749b55'


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def download(url: str, destination: Path, expected: str | None = None) -> None:
    if destination.is_file() and (expected is None or digest(destination) == expected):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.partial')
    request = urllib.request.Request(url, headers={'User-Agent': 'SecureModelDelegation-Build/0.3'})
    try:
        with urllib.request.urlopen(request, timeout=120) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        if expected is not None and digest(temporary) != expected:
            raise RuntimeError('The official release archive failed SHA256 verification.')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-python', action='store_true')
    parser.add_argument('--skip-opencode', action='store_true')
    parser.add_argument('--ollama-dir', type=Path)
    parser.add_argument('--mlx-dir', type=Path)
    parser.add_argument('--mlx-python', type=Path, help='Build a separate frozen MLX helper with this prepared environment.')
    parser.add_argument('--libreoffice', action='store_true', help='Bundle the official ARM64 office conversion engine.')
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Build this release on an Apple Silicon Mac.')
    BUILD.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(BUILD).free < 2 * 1024**3:
        raise SystemExit('At least 2 GB of free build space is required.')
    runtimes = BUILD / 'runtimes'
    runtimes.mkdir(exist_ok=True)
    support = ROOT / 'desktop' / 'opencode-support'
    if not args.skip_opencode and support.is_dir():
        subprocess.run(['npm', 'ci', '--prefix', str(support), '--ignore-scripts', '--no-audit', '--no-fund'], check=True)
        destination = runtimes / 'opencode-support'
        shutil.copytree(support, destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    if args.libreoffice:
        filename = f'LibreOffice_{LIBREOFFICE_VERSION}_MacOS_aarch64.dmg'
        url = f'https://download.documentfoundation.org/libreoffice/stable/{LIBREOFFICE_VERSION}/mac/aarch64/{filename}'
        archive = BUILD / 'downloads' / filename
        download(url, archive, LIBREOFFICE_SHA256)
        mount = BUILD / 'libreoffice-mount'
        mount.mkdir(exist_ok=True)
        subprocess.run(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(archive)], check=True)
        try:
            source = mount / 'LibreOffice.app'
            if not (source / 'Contents' / 'MacOS' / 'soffice').is_file():
                raise RuntimeError('The official disk image does not contain the office executable.')
            subprocess.run(['/usr/bin/ditto', str(source), str(runtimes / 'LibreOffice.app')], check=True)
        finally:
            subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)], check=True)
    if not args.skip_opencode:
        archive = BUILD / 'downloads' / f'opencode-{OPENCODE_VERSION}-darwin-arm64.zip'
        download(OPENCODE_URL, archive, OPENCODE_SHA256)
        destination = runtimes / 'opencode'
        destination.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            candidates = [name for name in source.namelist() if Path(name).name == 'opencode' and not name.endswith('/')]
            if len(candidates) != 1:
                raise RuntimeError('The release archive does not contain one OpenCode executable.')
            with source.open(candidates[0]) as input_file, (destination / 'opencode').open('wb') as output:
                shutil.copyfileobj(input_file, output)
        (destination / 'opencode').chmod(0o755)
        download(f'https://raw.githubusercontent.com/anomalyco/opencode/v{OPENCODE_VERSION}/LICENSE', destination / 'LICENSE')
        (destination / 'receipt.json').write_text(json.dumps({'version': OPENCODE_VERSION,
            'source': OPENCODE_URL, 'archive_sha256': OPENCODE_SHA256,
            'executable_sha256': digest(destination / 'opencode')}, indent=2) + '\n')
    if args.ollama_dir:
        source = args.ollama_dir.resolve(strict=True)
        if not (source / 'runtime.json').is_file() or not (source / 'ollama').is_file():
            raise RuntimeError('Choose the public engine directory containing its receipt.')
        subprocess.run(['/usr/bin/ditto', str(source), str(runtimes / 'ollama')], check=True)
    if args.mlx_dir:
        source = args.mlx_dir.resolve(strict=True)
        if not (source / 'smd-mlx-runtime').is_file():
            raise RuntimeError('The portable MLX runtime must contain smd-mlx-runtime.')
        subprocess.run(['/usr/bin/ditto', str(source), str(runtimes / 'mlx')], check=True)
    build_env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(BUILD / 'pyinstaller-cache'))
    if args.mlx_python:
        command = [str(args.mlx_python.absolute()), '-m', 'PyInstaller', '--noconfirm', '--clean',
            '--distpath', str(BUILD / 'mlx-python'), '--workpath', str(BUILD / 'mlx-work'),
            str(ROOT / 'desktop' / 'mlx-runtime.spec')]
        mlx_env = dict(build_env, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                       HF_HOME=str(BUILD / 'offline-build-cache'))
        subprocess.run(command, cwd=ROOT, env=mlx_env, check=True)
        subprocess.run(['/usr/bin/ditto', str(BUILD / 'mlx-python' / 'smd-mlx-runtime'), str(runtimes / 'mlx')], check=True)
    if not args.skip_python:
        helpers = BUILD / 'helpers'
        helpers.mkdir(exist_ok=True)
        subprocess.run(['/usr/bin/swiftc', '-O', '-target', 'arm64-apple-macos15.0',
            '-framework', 'AppKit', '-module-cache-path', str(BUILD / 'swift-cache'),
            str(ROOT / 'desktop' / 'key-entry.swift'), '-o', str(helpers / 'aethon-key-entry')], check=True)
        frontend = ROOT / 'frontend'
        canvas = ROOT / 'src/smd_app/static/canvas/canvas.js'
        pdf = ROOT / 'src/smd_app/static/pdf/preview.js'
        if frontend.is_dir() and (not canvas.exists() or not pdf.exists()):
            subprocess.run(['npm', 'ci', '--prefix', str(frontend), '--ignore-scripts', '--no-audit', '--no-fund'], check=True)
            subprocess.run(['npm', 'run', '--prefix', str(frontend), 'build'], check=True)
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
            '--name', 'smd-desktop-service', '--target-arch', 'arm64', '--paths', str(ROOT / 'src'),
            '--distpath', str(BUILD / 'python'), '--workpath', str(BUILD / 'pyinstaller-work'),
            '--specpath', str(BUILD), '--collect-data', 'smd_app', '--collect-data', 'certifi',
            '--hidden-import', 'uvicorn.logging', '--hidden-import', 'uvicorn.loops.auto',
            '--hidden-import', 'uvicorn.protocols.http.auto', '--hidden-import', 'uvicorn.lifespan.on',
            str(ROOT / 'desktop' / 'server-entry.py')]
        subprocess.run(command, cwd=ROOT, env=build_env, check=True)
    manifest = {'version': '0.3.0', 'platform': 'darwin-arm64', 'minimum_macos': '15.0',
        'electron': '42.3.3', 'opencode': OPENCODE_VERSION,
        'bundled_ollama': (runtimes / 'ollama' / 'runtime.json').exists(),
        'bundled_mlx': (runtimes / 'mlx' / 'smd-mlx-runtime').exists(),
        'selected_chat_or_speech_weights': False,
        'auxiliary_onnx_assets': [{'path': str(path.relative_to(runtimes)), 'bytes': path.stat().st_size}
                                  for path in runtimes.rglob('*.onnx') if path.is_file()]}
    manifest['bundled_libreoffice'] = (runtimes / 'LibreOffice.app' / 'Contents' / 'MacOS' / 'soffice').exists()
    (BUILD / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
