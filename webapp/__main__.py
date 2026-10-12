"""python -m webapp [--port 8000] [--no-browser]   (normally started via run.sh / run.bat)"""
import argparse
import socket
import threading
import time
import webbrowser

import uvicorn


def open_when_ready(url, port, timeout=120):
    """Open the browser once the server accepts connections (the first start can take a
    while on slower machines while PyTorch/OpenCV load)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  Fight Analyzer running at {url}\n")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, args.port), daemon=True).start()
    uvicorn.run("webapp.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
