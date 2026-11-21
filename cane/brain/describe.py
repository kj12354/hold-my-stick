"""Gemini describe-the-scene button. Runs off the motor thread.

The phone opens the page this module serves and reads the reply aloud.
Set GEMINI_API_KEY on the Pi. The vision app saves /tmp/latest.jpg.
"""

import base64
import json
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROMPT = "describe obstacles and layout in one sentence for a blind person."
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
IMAGE_PATH = Path(os.environ.get("CANE_LATEST_JPG", "/tmp/latest.jpg"))

_latest = ""
_latest_lock = threading.Lock()
_busy = False
_busy_lock = threading.Lock()


def latest_text():
    with _latest_lock:
        return _latest


def set_latest(text):
    global _latest
    with _latest_lock:
        _latest = text


def describe_image(path=None):
    path = Path(path) if path else IMAGE_PATH
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    if not path.is_file():
        raise RuntimeError(
            f"no frame at {path}. The vision app should save it once a second."
        )

    with path.open("rb") as handle:
        image = base64.b64encode(handle.read()).decode("ascii")

    body = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image}},
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": 120},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no description: {data.get('error', data)}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = " ".join(
        part.get("text", "")
        for part in parts
        if part.get("text") and not part.get("thought")
    ).strip()
    if not text:
        reason = candidates[0].get("finishReason", "unknown")
        raise RuntimeError(f"Gemini returned an empty description ({reason})")
    return text


def on_press():
    """Start one description. Does nothing if one is already running."""
    global _busy
    with _busy_lock:
        if _busy:
            return
        _busy = True
    threading.Thread(target=_run, daemon=True).start()


def _run():
    global _busy
    try:
        text = describe_image()
        set_latest(text)
        print(f"gemini: {text}", flush=True)
    except Exception as exc:
        message = f"Scene description failed: {exc}"
        set_latest(message)
        print(message, flush=True)
    finally:
        with _busy_lock:
            _busy = False


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hold My Stick</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         margin: 0; padding: 24px; background: #111; color: #fff; }
  h1 { font-size: 1.1rem; font-weight: 600; color: #bbb; }
  #line { font-size: 1.8rem; line-height: 1.35; min-height: 3em; }
  button { font-size: 1.25rem; padding: 16px 20px; margin-top: 24px; }
</style>
</head>
<body>
<h1>Hold My Stick</h1>
<p id="line">Waiting for the cane button.</p>
<button id="tap" type="button">Tap so this phone can speak</button>
<script>
let armed = false;
let last = "";
const line = document.getElementById("line");
document.getElementById("tap").onclick = function () {
  armed = true;
  this.hidden = true;
  speechSynthesis.speak(new SpeechSynthesisUtterance(
    "Ready. Press the button on the cane."));
};
async function poll() {
  try {
    const text = (await (await fetch("/latest")).text()).trim();
    if (!text || text === last) return;
    last = text;
    line.textContent = text;
    if (!armed) return;
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  } catch (err) {}
}
setInterval(poll, 700);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/latest"):
            body = latest_text().encode("utf-8")
            content_type = "text/plain; charset=utf-8"
        else:
            body = PAGE.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def serve(port):
    """Listen on all interfaces so a phone on the hotspot can open the page."""
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
