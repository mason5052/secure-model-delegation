"""Opt-in, empty-profile startup check for the standalone MLX distribution."""

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    helper = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='smd-mlx-bundle-check-') as directory:
        root = Path(directory)
        (root / 'models').mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        key = secrets.token_urlsafe(32)
        env = {name: value for name, value in os.environ.items()
               if name in {'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL'}}
        env.update(PATH='/usr/bin:/bin', HF_HOME=str(root / 'hf'), HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', NO_PROXY='127.0.0.1,localhost')
        command = [str(helper), 'serve', '--model-dir', str(root / 'models'), '--host',
                   '127.0.0.1', '--port', str(port), '--headless', '--no-cache', '--api-key',
                   key, '--log-level', 'error', '--base-path', str(root / 'state')]
        with (root / 'service-output').open('w+') as output:
            process = subprocess.Popen(command, env=env, stdout=output, stderr=output)
            try:
                for _ in range(200):
                    if process.poll() is not None:
                        break
                    try:
                        request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/models',
                                                         headers={'Authorization': 'Bearer ' + key})
                        with urllib.request.urlopen(request, timeout=1) as response:
                            models = json.load(response)
                        print(json.dumps({'standalone_mlx_ready': True, 'models': len(models.get('data', [])),
                                          'developer_python_on_path': False, 'downloads_disabled': True}))
                        return
                    except Exception:
                        time.sleep(.2)
                output.seek(0)
                print(output.read()[-6000:].replace(key, '[internal test token]'))
                raise SystemExit('The standalone MLX service did not become ready.')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    main()
