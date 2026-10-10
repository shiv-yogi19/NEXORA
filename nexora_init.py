"""
NEXORA INIT HELPER for Pydroid 3
Save this file inside:
NEXORA/NEXORA/mobile-server/

Then open this file in Pydroid 3 and press Run.
It runs nexora_server.py with the "init" command.
"""

import os
import runpy
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_FILE = os.path.join(BASE_DIR, "nexora_server.py")

# Change this only if your GitHub Pages origin is different.
SITE_ORIGIN = "https://shiv-yogi19.github.io"

if not os.path.isfile(SERVER_FILE):
    print("ERROR: nexora_server.py was not found.")
    print("Put this helper file in the same folder as nexora_server.py.")
else:
    os.chdir(BASE_DIR)
    sys.path.insert(0, BASE_DIR)
    sys.argv = [
        SERVER_FILE,
        "init",
        "--origin",
        SITE_ORIGIN,
    ]
    runpy.run_path(SERVER_FILE, run_name="__main__")
