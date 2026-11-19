#!/usr/bin/env python3
"""Long-running parent and child used to verify proxy signal cleanup."""

import os
import subprocess
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "parent-waits"
if mode == "leader-exits":
    child = subprocess.Popen([
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
    ])
    print(f"{os.getpid()}:{child.pid}", flush=True)
    raise SystemExit(0)

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(f"{os.getpid()}:{child.pid}", flush=True)
try:
    while True:
        time.sleep(1)
finally:
    child.terminate()
    child.wait()
