import subprocess
import sys
import unittest


class IsolationTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux parser isolation")
    def test_worker_cannot_open_files_or_network_sockets(self):
        code = """
import socket
from aegis.pdf_worker import restrict_linux_worker
restrict_linux_worker()
for operation in (lambda: open('/etc/hosts', 'rb'), lambda: socket.socket()):
    try:
        operation()
    except PermissionError:
        continue
    raise SystemExit(1)
"""
        subprocess.run([sys.executable, "-c", code], check=True, timeout=5)
