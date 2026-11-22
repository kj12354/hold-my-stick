"""Swing the SG92R servo left, middle, right, middle. Run on the Pi:

  python3 cane/hw/test_servo.py

50 Hz PWM on BCM 17. 5% is about 45 degrees, 7.5% is 90, 10% is 135.
"""

import sys
import time

try:
    import rpi_gpio as GPIO
except ImportError:
    print("rpi_gpio is not installed. Run this on the Pi.")
    sys.exit(1)

PIN = 17  # BCM, physical pin 11
POSITIONS = (("left", 5.0), ("middle", 7.5), ("right", 10.0), ("middle", 7.5))

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT)
if not hasattr(GPIO, "PWM"):
    print("rpi_gpio has no PWM. Have:", ", ".join(sorted(dir(GPIO))))
    sys.exit(2)

pwm = GPIO.PWM(PIN, 50)
pwm.start(7.5)
print("servo on GPIO17, 50 Hz", flush=True)
try:
    for name, duty in POSITIONS:
        print(f"{name}  {duty}%", flush=True)
        pwm.ChangeDutyCycle(duty)
        time.sleep(0.8)
finally:
    pwm.stop()
    GPIO.output(PIN, GPIO.LOW)
    print("stopped", flush=True)
