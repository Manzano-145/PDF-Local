"""Desktop entry point: runs the server in the background with a system tray icon.

- Opens the browser on start.
- If PDF Local is already running, it just opens the browser and exits.
- "Salir" in the tray menu (or "Cerrar" in the web UI) stops the server.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.request
import webbrowser

# A windowed (no console) build has no stdout/stderr; libraries that print would crash.
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")

import pystray  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from app import APP_ID, app  # noqa: E402

HOST = "127.0.0.1"
PORTS = range(5000, 5011)


def make_icon_image(size: int = 256) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 6, fill=(229, 50, 45, 255))
    try:
        font = ImageFont.truetype("arialbd.ttf", size // 3)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2), "PDF", fill="white", font=font, anchor="mm")
    return image


def running_instance(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=0.5) as response:
            return json.load(response).get("app") == APP_ID
    except (OSError, ValueError):
        return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((HOST, port)) != 0


def main() -> None:
    for port in PORTS:
        if running_instance(port):
            webbrowser.open(f"http://{HOST}:{port}")
            return
    port = next((p for p in PORTS if port_is_free(p)), None)
    if port is None:
        raise SystemExit("No hay un puerto libre entre 5000 y 5010.")

    url = f"http://{HOST}:{port}"
    server = make_server(HOST, port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    icon = pystray.Icon("PDF Local", make_icon_image(64), f"PDF Local ({url})")

    def stop() -> None:
        # Run apart from the caller so an HTTP request can finish replying first.
        def _stop():
            server.shutdown()
            icon.stop()

        threading.Timer(0.3, _stop).start()

    app.config["SHUTDOWN_HOOK"] = stop
    icon.menu = pystray.Menu(
        pystray.MenuItem("Abrir PDF Local", lambda: webbrowser.open(url), default=True),
        pystray.MenuItem("Salir", stop),
    )
    webbrowser.open(url)
    icon.run()


if __name__ == "__main__":
    main()
