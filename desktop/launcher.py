"""Start the existing Aegis workspace on the current Windows user's computer."""
import argparse
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import webbrowser


def launch(open_browser=True):
    import uvicorn
    from aegis.api import make_app
    from aegis.store import Store

    folder = Path(os.environ["LOCALAPPDATA"]) / "Aegis"
    key = secrets.token_urlsafe(36)
    app = make_app(Store(str(folder / "documents.sqlite3")), {"local": key},
                   os.getenv("AEGIS_MODEL"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/"
        server = uvicorn.Server(uvicorn.Config(app, loop="asyncio", http="h11",
            ws="none", lifespan="on", proxy_headers=False, access_log=False, log_level="warning"))

        def ready():
            while not server.started:
                if server.should_exit:
                    return
                time.sleep(0.05)
            print(f"Workspace: {url}\nAccess key: {key}", flush=True)
            print("Paste the access key into the workspace. Press Ctrl+C here to stop Aegis.", flush=True)
            if open_browser:
                webbrowser.open(url, new=2)

        threading.Thread(target=ready, daemon=True).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    if sys.argv[1:] == ["--pdf-worker"]:
        from aegis.pdf_worker import main
        try:
            result = main()
        except Exception:
            result = 1
        sys.exit(result)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="print the local URL without opening it")
    options = parser.parse_args()
    try:
        launch(not options.no_browser)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"Aegis could not start: {error}", file=sys.stderr, flush=True)
        if sys.stdin.isatty():
            input("Press Enter to close.")
        sys.exit(1)
