"""Stand-in for the C++ vision app. Sends the UDP JSON brain.py expects.

The real app on the Pi does the same thing, to 127.0.0.1 port 5005, once
per frame, including frames with no detections:

  {"t": 1732170000123, "objs": [{"cls": "person", "score": 0.82, "x": 0.41, "h": 0.55}]}

  t      milliseconds since 1970, when the frame was captured
  cls    name from labelmap.txt
  score  0 to 1; brain ignores anything under 0.5
  x      box centre across the frame, 0 = left edge, 1 = right edge
  h      box height as a fraction of the frame; bigger means closer

  python3 fake_vision.py right
  python3 fake_vision.py left
  python3 fake_vision.py center
  python3 fake_vision.py flicker
  python3 fake_vision.py empty
"""

import argparse
import json
import socket
import time


def packet(objs):
    return json.dumps({"t": int(time.time() * 1000), "objs": objs}).encode("utf-8")


def person(x, h, score=0.9):
    return {"cls": "person", "score": score, "x": x, "h": h}


# Each scenario is a list of obj-lists. One entry is one frame.
SCENARIOS = {
    "right": [
        [person(0.82, 0.35)],
        [person(0.82, 0.35)],
        [person(0.82, 0.60)],
        [person(0.82, 0.60)],
        [person(0.82, 0.85)],
        [person(0.82, 0.85)],
    ],
    "left": [
        [person(0.15, 0.40)],
        [person(0.15, 0.40)],
        [person(0.15, 0.80)],
        [person(0.15, 0.80)],
    ],
    "center": [
        [person(0.50, 0.85)],
        [person(0.50, 0.85)],
    ],
    "flicker": [
        [person(0.82, 0.90)],
        [],
        [],
        [],
    ],
    "empty": [[]],
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send fake cane detections over UDP.")
    parser.add_argument("scenario", nargs="?", default="right", choices=sorted(SCENARIOS))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--fps", type=float, default=5)
    parser.add_argument("--count", type=int, default=0, help="Stop after this many frames. 0 loops.")
    args = parser.parse_args(argv)

    frames = SCENARIOS[args.scenario]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    delay = 1 / args.fps if args.fps else 0
    sent = 0
    print(f"sending {args.scenario} to {args.host}:{args.port}", flush=True)
    try:
        while True:
            for objs in frames:
                sock.sendto(packet(objs), (args.host, args.port))
                sent += 1
                if args.count and sent >= args.count:
                    print(f"sent {sent} frames", flush=True)
                    return
                time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\nsent {sent} frames", flush=True)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
