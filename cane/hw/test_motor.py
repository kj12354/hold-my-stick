"""Pulse a coin vibration motor. Run on the Pi:

  python3 cane/hw/test_motor.py
  python3 cane/hw/test_motor.py 27

Default pin is BCM 17, physical pin 11, the same pin the servo used.
Pass 27 for the right motor, physical pin 13.

One lead goes to that pin, the other to ground (physical pin 6).
Either way around. The motor is on/off. It does not want the servo's
50 Hz pulse. The brain already buzzes this way: 100 ms on, 100 ms off.
"""

import sys
import time

try:
    import rpi_gpio as GPIO
except ImportError:
    print("rpi_gpio is not installed. Run this on the Pi.")
    sys.exit(1)

PIN = int(sys.argv[1]) if len(sys.argv) > 1 else 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT)
GPIO.output(PIN, GPIO.LOW)

def pulse(on, off):
    GPIO.output(PIN, GPIO.HIGH)
    time.sleep(on)
    GPIO.output(PIN, GPIO.LOW)
    time.sleep(off)

print(f"motor on GPIO{PIN}", flush=True)
try:
    print("long pulse", flush=True)
    pulse(0.4, 0.3)
    print("three ticks", flush=True)
    for _ in range(3):
        pulse(0.1, 0.1)
finally:
    GPIO.output(PIN, GPIO.LOW)
    print("stopped", flush=True)
