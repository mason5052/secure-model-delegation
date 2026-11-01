"""Restricted entry for the bundled MLX inference runtime."""

import multiprocessing
import importlib
import os
import sys


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if len(sys.argv) < 2 or sys.argv[1] not in {'serve', '--version', '--help'}:
        raise SystemExit('Use this private runtime through Secure Model Delegation.')
    if getattr(sys, 'frozen', False):
        sys.path[0:0] = [os.path.join(sys._MEIPASS, folder)
                         for folder in ('site-packages', 'stdlib', 'lib-dynload')]
    importlib.import_module('omlx.cli').main()
