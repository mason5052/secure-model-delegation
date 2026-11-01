#!/usr/bin/env python3
"""Create an ad-hoc-signed development application and compressed DMG."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build' / 'desktop'
NAME = 'aethon'


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def create_icon(resources: Path) -> None:
    artwork = BUILD / 'artwork'
    artwork.mkdir(exist_ok=True)
    electron = ROOT / 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'
    run(str(electron), str(ROOT / 'desktop/render-assets.cjs'),
        str(ROOT / 'src/smd_app/static/assets/aethon-mark.svg'), str(artwork))
    iconset = BUILD / 'aethon.iconset'
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = '@2x' if scale == 2 else ''
            target = iconset / f'icon_{size}x{size}{suffix}.png'
            run('/usr/bin/sips', '-z', str(size * scale), str(size * scale),
                str(artwork / 'icon.png'), '--out', str(target))
    run('/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(resources / 'aethon.icns'))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-dmg', action='store_true')
    parser.add_argument('--reuse-app', action='store_true', help='Rebuild only the image from an unchanged verified app.')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('The development DMG must be built on macOS.')
    electron = ROOT / 'node_modules' / 'electron' / 'dist' / 'Electron.app'
    service = BUILD / 'python' / 'smd-desktop-service'
    if not electron.is_dir():
        from build_desktop import download
        checksum_file = electron.parent.parent / 'checksums.json'
        if not checksum_file.is_file():
            raise SystemExit('Install the pinned npm dependency first.')
        filename = 'electron-v42.3.3-darwin-arm64.zip'
        expected = json.loads(checksum_file.read_text())[filename]
        archive = BUILD / 'downloads' / filename
        download('https://github.com/electron/electron/releases/download/v42.3.3/' + filename, archive, expected)
        run('/usr/bin/ditto', '-x', '-k', str(archive), str(electron.parent))
    if not electron.is_dir() or not (service / 'smd-desktop-service').is_file():
        raise SystemExit('Install the pinned npm dependency and build the Python service first.')
    stage = BUILD / 'stage'
    stage.mkdir(parents=True, exist_ok=True)
    app = stage / (NAME + '.app')
    if not args.reuse_app:
        if app.exists():
            shutil.rmtree(app)
        run('/usr/bin/ditto', str(electron), str(app))
        contents = app / 'Contents'
        executable = contents / 'MacOS' / 'Electron'
        executable.rename(contents / 'MacOS' / NAME)
        info_path = contents / 'Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update({'CFBundleName': NAME, 'CFBundleDisplayName': NAME,
            'CFBundleIdentifier': 'io.github.mason5052.aethon', 'CFBundleExecutable': NAME,
            'CFBundleShortVersionString': '0.3.0', 'CFBundleVersion': '3', 'CFBundleIconFile': 'aethon.icns',
            'LSMinimumSystemVersion': '15.0', 'NSHighResolutionCapable': True,
            'NSMicrophoneUsageDescription': 'Dictate a prompt for local transcription when you choose the microphone.',
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True}})
        info_path.write_bytes(plistlib.dumps(info))
        resources = contents / 'Resources'
        create_icon(resources)
        (resources / 'default_app.asar').unlink(missing_ok=True)
        application = resources / 'app'
        application.mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'package.json', application / 'package.json')
        shutil.copytree(ROOT / 'desktop', application / 'desktop', ignore=shutil.ignore_patterns('tests', '__pycache__'))
        run('/usr/bin/ditto', str(service), str(resources / 'service'))
        if (BUILD / 'helpers').is_dir():
            run('/usr/bin/ditto', str(BUILD / 'helpers'), str(resources / 'helpers'))
        if (BUILD / 'runtimes').is_dir():
            run('/usr/bin/ditto', str(BUILD / 'runtimes'), str(resources / 'runtimes'))
        shutil.copy2(BUILD / 'build-manifest.json', resources / 'build-manifest.json')
        licenses = resources / 'licenses'
        licenses.mkdir(exist_ok=True)
        for name in ('LICENSE', 'LICENSES.chromium.html'):
            source = electron.parent / name
            if source.is_file():
                shutil.copy2(source, licenses / name)
        # This identifies a local test build; it does not replace Developer ID notarization.
        run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app))
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
    resources = app / 'Contents' / 'Resources'
    if args.reuse_app:
        for name in ('main.cjs', 'preload.cjs', 'lifecycle.cjs', 'provider-connection.cjs'):
            if (ROOT / 'desktop' / name).read_bytes() != (resources / 'app' / 'desktop' / name).read_bytes():
                raise SystemExit('The desktop source changed. Rebuild the app before packaging it.')
        from PyInstaller.archive.readers import CArchiveReader
        payloads = []
        for executable in (service / 'smd-desktop-service', resources / 'service' / 'smd-desktop-service'):
            archive = CArchiveReader(str(executable))
            entry = next(name for name in archive.toc if name.endswith('.pyz'))
            payloads.append(hashlib.sha256(archive.extract(entry)).hexdigest())
        if len(set(payloads)) != 1:
            raise SystemExit('The frozen backend changed. Rebuild the app before packaging it.')
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
    manifest = {'application': str(app), 'signing': 'ad-hoc development; not notarized'}
    if not args.no_dmg:
        distribution = ROOT / 'dist' / 'desktop'
        distribution.mkdir(parents=True, exist_ok=True)
        image = distribution / 'aethon-arm64.dmg'
        image.unlink(missing_ok=True)
        import dmgbuild
        entries = [path for path in app.rglob('*') if path.is_file() and not path.is_symlink()]
        required = sum(path.stat().st_size for path in entries) + len(entries) * 16384 + 512 * 1024**2
        image_size = str((required + 1024**3 - 1) // 1024**3) + 'G'
        dmgbuild.build_dmg(str(image), NAME, settings={
            'files': [str(app)], 'symlinks': {'Applications': '/Applications'},
            'background': str(BUILD / 'artwork' / 'dmg-background.png'),
            'icon': str(resources / 'aethon.icns'), 'format': 'UDZO', 'size': image_size,
            'window_rect': ((160, 160), (660, 420)), 'default_view': 'icon-view',
            'icon_locations': {NAME + '.app': (170, 230), 'Applications': (485, 230)},
            'icon_size': 96, 'text_size': 13, 'show_icon_preview': False,
            'show_toolbar': False, 'show_status_bar': False, 'show_sidebar': False,
        })
        run('/usr/bin/hdiutil', 'verify', str(image))
        verification_mount = BUILD / 'verified-image'
        verification_mount.mkdir(exist_ok=True)
        run('/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(verification_mount), str(image))
        try:
            packaged_app = verification_mount / (NAME + '.app')
            run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(packaged_app))
            framework = packaged_app / 'Contents/Frameworks/Electron Framework.framework/Electron Framework'
            if not framework.is_file() or not (verification_mount / 'Applications').is_symlink():
                raise RuntimeError('The image is incomplete.')
        finally:
            run('/usr/bin/hdiutil', 'detach', str(verification_mount))
        result = hashlib.sha256()
        with image.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                result.update(chunk)
        manifest.update({'disk_image': str(image), 'sha256': result.hexdigest(),
                         'image_app_signature_verified': True, 'build_image_capacity': image_size})
    (BUILD / 'package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
