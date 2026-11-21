"""Hardware tests, in the order from the build guide. Run this on the Pi.

  python3 test_pins.py blink
  python3 test_pins.py motors
  python3 test_pins.py distance
  python3 test_pins.py button

Put an LED on GPIO17 before `blink`. If the LED blinks, the code works and
any later motor problem is in the wiring.
"""

import sys
import time

import hw


def blink():
    print("LED on GPIO17 should blink every 0.5 s. Ctrl+C to stop.")
    while True:
        hw.motor("left", True)
        time.sleep(0.5)
        hw.motor("left", False)
        time.sleep(0.5)


def motors():
    for side in ("left", "right"):
        print(f"buzz {side} three times")
        hw.buzz(side, 3)
        time.sleep(0.4)


def distance():
    print("Move a hand from 2 m to 10 cm. Readings every 60 ms. Ctrl+C to stop.")
    while True:
        print(hw.read_distance_cm())
        time.sleep(0.06)


def button():
    print("Press the button. Ctrl+C to stop.")
    while True:
        print(hw.button_pressed())
        time.sleep(0.1)


STEPS = {
    "blink": blink,
    "motors": motors,
    "distance": distance,
    "button": button,
}


if __name__ == "__main__":
    if not hw.ON_PI:
        print("rpi_gpio is not installed. Run this on the Pi, from ~/cane/hw/.")
        sys.exit(1)
    name = sys.argv[1] if len(sys.argv) > 1 else "blink"
    if name not in STEPS:
        print(f"use one of: {', '.join(STEPS)}")
        sys.exit(2)
    try:
        STEPS[name]()
    except KeyboardInterrupt:
        hw.motors_off()
        print("\nstopped")
