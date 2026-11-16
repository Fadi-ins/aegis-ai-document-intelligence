"""Exercise the packaged executable twice with a disposable Windows profile."""
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

import httpx
from aegis.demo import sample_pdf


@contextmanager
def running(executable, profile):
    proc = subprocess.Popen([executable, "--no-browser"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            env={**os.environ, "LOCALAPPDATA": profile})
    lines = queue.Queue()
    def read_output():
        for line in proc.stdout:
            lines.put(line.strip())
        lines.put(None)
    threading.Thread(target=read_output, daemon=True).start()
    try:
        deadline = time.monotonic() + 60
        url = key = None
        while not (url and key):
            line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError("Aegis exited before serving its workspace")
            if line.startswith("Workspace: "):
                url = line.removeprefix("Workspace: ")
            elif line.startswith("Access key: "):
                key = line.removeprefix("Access key: ")
        with httpx.Client(base_url=url, trust_env=False, timeout=30) as client:
            assert client.base_url.host == "127.0.0.1"
            assert "Unlock workspace" in client.get("/").raise_for_status().text
            assert client.get("/api/v1/documents").status_code == 401
            client.headers["Authorization"] = "Bearer " + key
            yield client
    finally:
        # One-file executables have a bootloader parent and a server child.
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait(timeout=15)
        proc.stdout.close()


if __name__ == "__main__":
    exe = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory() as profile:
        with running(exe, profile) as client:
            doc = client.post("/api/v1/documents", files={
                "file": ("handbook.pdf", sample_pdf(), "application/pdf")
            }).raise_for_status().json()
            result = client.post("/api/v1/chat/query", json={
                "question": "archive retention", "document_ids": [doc["id"]]
            }).raise_for_status().json()
            assert result["citations"][0]["page"] == 2
            assert "45 days" in result["citations"][0]["quote"]
            old_key = client.headers["Authorization"]
        with running(exe, profile) as client:
            assert client.get("/api/v1/documents").raise_for_status().json()[0]["id"] == doc["id"]
            assert client.get("/api/v1/documents", headers={"Authorization": old_key}).status_code == 401
