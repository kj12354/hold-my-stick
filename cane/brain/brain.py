"""Decide how the two wrist straps tick.

The distance sensor sets how urgent a warning is and applies it to both
straps. The camera sets which side. Each strap plays the higher of the two.
Vision messages arrive as JSON on UDP port 5005.

On the Pi, run this above the vision process (default priority is 10):

  on -p 20 python3 ~/cane/brain/brain.py
"""

import argparse
import errno
import json
import os
import socket
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hw"))

import describe
import hw

LATENCY_PATH = Path(os.environ.get("CANE_LATENCY", Path(__file__).resolve().parent / "latency.csv"))

# Shared with the strap threads. They read it; step() writes it.
level = {"left": 0, "right": 0}
stop = False


class State:
    def __init__(self):
        self.last_msg = {"objs": []}
        self.last_seen = 0.0
        self.dist = []
        self.hist = {"left": [], "right": []}
        self.prev = {"left": 0, "right": 0}
        self.was_pressed = False
        self.latency_ms = []


def level_from_cm(cm):
    if cm > 200:
        return 0
    if cm > 150:
        return 1
    if cm > 50:
        return 2
    return 3


def level_from_h(h):
    if h < 0.3:
        return 0
    if h < 0.5:
        return 1
    if h < 0.7:
        return 2
    return 3


def vision_levels(msg):
    """Left and right levels from one frame. Weak or broken boxes are skipped."""
    left = right = 0
    for obj in msg.get("objs", []):
        if obj.get("score", 0) < 0.5:
            continue
        try:
            lv = level_from_h(float(obj["h"]))
            x = float(obj["x"])
        except (KeyError, TypeError, ValueError):
            continue
        if x < 0.33:
            left = max(left, lv)
        elif x > 0.66:
            right = max(right, lv)
        else:
            left = max(left, lv)
            right = max(right, lv)
    return left, right


def confirmed(history):
    """A vision level counts only after it shows up in 2 of the last 3 frames.

    Missing frames count as 0, so one stray detection at startup does not buzz.
    """
    window = list(history[-3:])
    if len(window) < 3:
        window += [0] * (3 - len(window))
    return statistics.median_low(window)


def sensor_level(dist):
    """Middle of the last 3 readings. Missing ones count as nothing in range.

    Median of two numbers is their average, which is not a distance the sensor
    measured, so the window is always three values.
    """
    window = list(dist[-3:])
    if len(window) < 3:
        window += [999] * (3 - len(window))
    return level_from_cm(statistics.median(window))


def take_latest(sock, state):
    """Read every datagram waiting and keep the newest."""
    try:
        while True:
            data, _ = sock.recvfrom(4096)
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                print("ignored a vision packet that was not JSON", flush=True)
                continue
            if "objs" not in msg:
                print("ignored a vision packet with no objs", flush=True)
                continue
            state.last_msg = msg
            state.last_seen = time.monotonic()
    except BlockingIOError:
        return
    except OSError as exc:
        if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return
        raise


def step(state, distance_cm, now):
    """One brain update. now is time.monotonic(), same clock as last_seen."""
    sample = 999 if distance_cm is None else distance_cm
    state.dist = (state.dist + [sample])[-3:]
    sensor = sensor_level(state.dist)

    fresh = now - state.last_seen < 0.5
    vision = vision_levels(state.last_msg) if fresh else (0, 0)

    for side, seen in zip(("left", "right"), vision):
        state.hist[side] = (state.hist[side] + [seen])[-3:]
        seen_twice = confirmed(state.hist[side])
        new = max(sensor, seen_twice)
        # Frame-capture to buzz decision. Skip when vision is stale: an old
        # timestamp would invent a huge latency number for the QNX slide.
        if state.prev[side] == 0 and new >= 1 and fresh and "t" in state.last_msg:
            ms = time.time() * 1000 - state.last_msg["t"]
            state.latency_ms.append(ms)
            with LATENCY_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"{ms:.1f}\n")
            print(f"latency {ms:.0f} ms", flush=True)
        if new != level[side]:
            print(
                f"{side} {level[side]} -> {new} (sensor {sensor}, vision {seen_twice})",
                flush=True,
            )
        level[side] = new
        state.prev[side] = new


def play_pattern(side, n):
    """n ticks, then wait out the rest of the second.

    A higher level restarts the pattern now instead of finishing the second.
    """
    start = time.monotonic()
    for _ in range(n):
        if stop or level[side] > n:
            hw.motor(side, False)
            return
        hw.motor(side, True)
        time.sleep(0.1)
        hw.motor(side, False)
        time.sleep(0.1)
    while time.monotonic() - start < 1.0:
        if stop or level[side] > n:
            return
        time.sleep(0.05)


def player(side):
    while not stop:
        n = level[side]
        if n == 0:
            time.sleep(0.05)
            continue
        play_pattern(side, n)


def report(state):
    if not state.latency_ms:
        print("no latency samples yet", flush=True)
        return
    worst = max(state.latency_ms)
    print(
        f"worst-case latency: {worst:.0f} ms over {len(state.latency_ms)} warnings",
        flush=True,
    )


def main(argv=None):
    global stop
    parser = argparse.ArgumentParser(description="Strap tick decisions for the smart cane.")
    parser.add_argument(
        "--distance",
        type=float,
        default=None,
        help="Fixed sensor reading in cm, for a test with no hardware.",
    )
    parser.add_argument("--seconds", type=float, default=None, help="Exit after N seconds.")
    parser.add_argument("--no-web", action="store_true", help="Do not serve the phone page.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CANE_PORT", "8080")))
    args = parser.parse_args(argv)

    if args.distance is not None:
        hw.override_cm = args.distance

    if not args.no_web:
        try:
            describe.serve(args.port)
            print(
                f"phone page: http://{describe.local_ip()}:{args.port}  (tap it once so sound is allowed)",
                flush=True,
            )
        except OSError as exc:
            print(f"phone page did not start: {exc}", flush=True)
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set. The describe button will not call Gemini.", flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 5005))
    sock.setblocking(False)
    print("brain listening on udp 127.0.0.1:5005", flush=True)
    print("on the Pi run:  on -p 20 python3 brain.py", flush=True)

    for side in ("left", "right"):
        threading.Thread(target=player, args=(side,), daemon=True).start()

    state = State()
    deadline = None if args.seconds is None else time.monotonic() + args.seconds
    try:
        while not stop:
            loop_start = time.monotonic()
            try:
                take_latest(sock, state)
                step(state, hw.read_distance_cm(), time.monotonic())
                pressed = hw.button_pressed()
                if pressed and not state.was_pressed:
                    describe.on_press()
                state.was_pressed = pressed
            except Exception as exc:
                print(f"brain loop error: {exc}", flush=True)
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(max(0, 0.05 - (time.monotonic() - loop_start)))
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        stop = True
        hw.motors_off()
        report(state)
        sock.close()


if __name__ == "__main__":
    main()
