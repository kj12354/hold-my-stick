"""Watch the HW-416 motion sensor. Run on the Pi:

  python3 cane/hw/test_pir.py

Wave a hand in front of the dome. Prints MOVEMENT! when the output goes high.
The sensor needs about a minute after power-on before it is ready.
"""

import sys
import time

try:
    import rpi_gpio as GPIO
except ImportError:
    print("rpi_gpio is not installed. Run this on the Pi.")
    sys.exit(1)

PIN = 23  # BCM, physical pin 16

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN)

print("watching GPIO23. Wave in front of the dome. Ctrl+C to stop.", flush=True)
last = None
try:
    while True:
        high = GPIO.input(PIN) == GPIO.HIGH
        if high != last:
            print("MOVEMENT!" if high else "clear", flush=True)
            last = high
        time.sleep(0.05)
except KeyboardInterrupt:
    print("\nstopped", flush=True)
