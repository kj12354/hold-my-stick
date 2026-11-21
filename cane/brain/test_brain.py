"""Tick rules from the build guide. No Pi and no camera required."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import brain


def fresh_state(objs, age=0.0):
    state = brain.State()
    state.last_msg = {"t": int(time.time() * 1000), "objs": objs}
    state.last_seen = 1000.0 - age
    return state


class TickRules(unittest.TestCase):
    def setUp(self):
        brain.level["left"] = 0
        brain.level["right"] = 0
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        brain.LATENCY_PATH = Path(handle.name)

    def test_distance_boundaries(self):
        self.assertEqual(brain.level_from_cm(201), 0)
        self.assertEqual(brain.level_from_cm(200), 1)
        self.assertEqual(brain.level_from_cm(151), 1)
        self.assertEqual(brain.level_from_cm(150), 2)
        self.assertEqual(brain.level_from_cm(51), 2)
        self.assertEqual(brain.level_from_cm(50), 3)
        self.assertEqual(brain.level_from_cm(10), 3)

    def test_box_height_boundaries(self):
        self.assertEqual(brain.level_from_h(0.29), 0)
        self.assertEqual(brain.level_from_h(0.30), 1)
        self.assertEqual(brain.level_from_h(0.49), 1)
        self.assertEqual(brain.level_from_h(0.50), 2)
        self.assertEqual(brain.level_from_h(0.69), 2)
        self.assertEqual(brain.level_from_h(0.70), 3)

    def test_sides(self):
        self.assertEqual(brain.vision_levels({"objs": [{"score": 0.9, "x": 0.1, "h": 0.8}]}), (3, 0))
        self.assertEqual(brain.vision_levels({"objs": [{"score": 0.9, "x": 0.9, "h": 0.8}]}), (0, 3))
        self.assertEqual(brain.vision_levels({"objs": [{"score": 0.9, "x": 0.5, "h": 0.8}]}), (3, 3))
        # 0.33 and 0.66 are the centre band, so both straps.
        self.assertEqual(brain.vision_levels({"objs": [{"score": 0.9, "x": 0.33, "h": 0.4}]}), (1, 1))
        self.assertEqual(brain.vision_levels({"objs": [{"score": 0.9, "x": 0.66, "h": 0.4}]}), (1, 1))

    def test_weak_detection_is_ignored(self):
        state = fresh_state([{"cls": "person", "score": 0.4, "x": 0.8, "h": 0.9}])
        brain.step(state, None, 1000.0)
        brain.step(state, None, 1000.1)
        self.assertEqual(brain.level, {"left": 0, "right": 0})

    def test_one_frame_does_not_buzz(self):
        state = fresh_state([{"cls": "person", "score": 0.9, "x": 0.8, "h": 0.9}])
        brain.step(state, None, 1000.0)
        self.assertEqual(brain.level["right"], 0)

    def test_two_frames_on_the_right_buzz_the_right_strap(self):
        state = fresh_state([{"cls": "person", "score": 0.9, "x": 0.82, "h": 0.85}])
        brain.step(state, None, 1000.0)
        brain.step(state, None, 1000.1)
        self.assertEqual(brain.level["right"], 3)
        self.assertEqual(brain.level["left"], 0)

    def test_flicker_dies(self):
        self.assertEqual(brain.confirmed([3, 0, 0]), 0)
        self.assertEqual(brain.confirmed([3]), 0)
        self.assertEqual(brain.confirmed([3, 3, 0]), 3)
        self.assertEqual(brain.confirmed([3, 0, 3]), 3)

    def test_one_close_reading_does_not_buzz(self):
        state = fresh_state([])
        state.last_seen = 0.0  # vision is stale; sensor only
        brain.step(state, 30, 1000.0)
        self.assertEqual(brain.level, {"left": 0, "right": 0})

    def test_two_close_readings_buzz_both_straps(self):
        state = fresh_state([])
        state.last_seen = 0.0
        brain.step(state, 30, 1000.0)
        brain.step(state, 30, 1000.1)
        self.assertEqual(brain.level, {"left": 3, "right": 3})

    def test_sensor_wins_over_a_quiet_camera(self):
        # Camera sees nothing, sensor sees 40 cm. Both straps go to level 3.
        state = fresh_state([])
        brain.step(state, 40, 1000.0)
        brain.step(state, 40, 1000.1)
        self.assertEqual(brain.level, {"left": 3, "right": 3})

    def test_stale_vision_is_dropped(self):
        state = fresh_state([{"cls": "person", "score": 0.9, "x": 0.1, "h": 0.9}], age=1.0)
        brain.step(state, None, 1000.0)
        brain.step(state, None, 1000.1)
        self.assertEqual(brain.level, {"left": 0, "right": 0})

    def test_closer_cuts_the_pattern_short(self):
        def bump(side, on):
            if on:
                brain.level[side] = 3

        original = brain.hw.motor
        brain.hw.motor = bump
        brain.level["left"] = 1
        try:
            started = time.monotonic()
            brain.play_pattern("left", 1)
            elapsed = time.monotonic() - started
        finally:
            brain.hw.motor = original
            brain.level["left"] = 0
        # One tick is 0.2 s. Waiting out the second would take about 1 s.
        self.assertLess(elapsed, 0.6)

    def test_right_hand_wave_on_the_loop(self):
        self._run_brain(
            ["--no-web", "--seconds", "2.5"],
            send_right=True,
            expect=("right 0 -> 3", "MOTOR right ON"),
            absent=("MOTOR left ON",),
        )

    def test_close_sensor_ticks_both_straps(self):
        self._run_brain(
            ["--distance", "40", "--no-web", "--seconds", "1.5"],
            send_right=False,
            expect=("left 0 -> 3", "right 0 -> 3", "MOTOR left ON", "MOTOR right ON"),
            absent=(),
        )

    def _run_brain(self, args, send_right, expect, absent):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["CANE_LATENCY"] = str(Path(tmp) / "latency.csv")
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                [sys.executable, "-u", str(Path(__file__).resolve().parent / "brain.py"), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            try:
                time.sleep(0.4)
                if send_right:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    obj = {"cls": "person", "score": 0.91, "x": 0.82, "h": 0.85}
                    for _ in range(4):
                        msg = json.dumps({"t": int(time.time() * 1000), "objs": [obj]}).encode()
                        sock.sendto(msg, ("127.0.0.1", 5005))
                        time.sleep(0.05)
                    sock.close()
                out, _ = proc.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                out = proc.stdout.read()
                self.fail(f"brain did not exit\n{out}")
        for text in expect:
            self.assertIn(text, out, out)
        for text in absent:
            self.assertNotIn(text, out, out)


if __name__ == "__main__":
    unittest.main()
