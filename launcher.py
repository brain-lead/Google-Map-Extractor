"""Brain Lead - desktop launcher.

This is the PyInstaller entry point. It starts the local FastAPI server
(uvicorn) and opens the default browser to the web UI. No GUI toolkit is
required - license activation and branding live in the web UI itself.

Build (on your Python 3.10 + PyArmor 9 machine, conda env build310):

    pyi-makespec --onefile --noconsole --name BrainLead ^
        --add-data "frontend/dist;frontend/dist" ^
        --hidden-import backend.licensing --collect-all curl_cffi launcher.py
    pyarmor gen --pack BrainLead.spec -r launcher.py backend

(or just run build.bat, which does the above and also builds the frontend).
"""
import os
import sys
import time
import socket
import webbrowser
import threading
import uvicorn
from pathlib import Path

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "127.0.0.1")


def find_free_port(start):
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def open_browser(port):
    url = f"http://127.0.0.1:{port}/"
    # Give the server a moment to come up before opening the browser.
    time.sleep(1.5)
    for _ in range(10):
        try:
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(1)


def main():
    # When running without a console, ensure stdout and stderr have valid streams
    # so uvicorn's log formatters and third-party libraries don't crash on isatty().
    _logdir = Path(os.environ.get("APPDATA", Path.home())) / "BrainLead"
    _logdir.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or not hasattr(sys.stdout, "isatty"):
        try:
            sys.stdout = open(_logdir / "stdout.log", "a", buffering=1, encoding="utf-8")
        except Exception:
            pass
    if sys.stderr is None or not hasattr(sys.stderr, "isatty"):
        try:
            sys.stderr = open(_logdir / "stderr.log", "a", buffering=1, encoding="utf-8")
        except Exception:
            pass

    port = find_free_port(PORT)
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    # Imported here so PyInstaller/PyArmor hooks resolve the backend cleanly.
    from backend.app import app
    print(f"Brain Lead running at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
