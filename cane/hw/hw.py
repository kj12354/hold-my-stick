"""Distance sensor, vibration motors, and the Gemini button.

BCM pins, matching the build guide:
  TRIG 23, ECHO 24, button 22, left motor 17, right motor 27.

On the Pi this talks to QNX's rpi_gpio. On a laptop, where that module
does not exist, the same functions run against stand-in values so
brain.py can be tested. Set override_cm to force a distance reading.
"""

import time

TRIG, ECHO, BUTTON = 23, 24, 22
MOTOR = {"left": 17, "right": 27}

# When set, read_distance_cm returns this and does not touch the sensor.
override_cm = None
# Used only when rpi_gpio is missing.
simulated_cm = None
simulated_button = False


class _FakeGPIO:
    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"

    def __init__(self):
        self.pins = {}

    def setmode(self, mode):
        return None

    def setup(self, pin, mode, pull=None):
        self.pins[pin] = self.LOW

    def output(self, pin, value):
        self.pins[pin] = value

    def input(self, pin):
        return self.pins.get(pin, self.HIGH)


try:
    import rpi_gpio as GPIO
    ON_PI = True
except ImportError:
    GPIO = _FakeGPIO()
    ON_PI = False


GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIG, GPIO.OUT)
GPIO.setup(ECHO, GPIO.IN)
GPIO.setup(BUTTON, GPIO.IN, GPIO.PUD_UP)
for _pin in MOTOR.values():
    GPIO.setup(_pin, GPIO.OUT)
    GPIO.output(_pin, GPIO.LOW)


def read_distance_cm(timeout=0.03):
    """Centimetres to the nearest echo, or None when nothing is in range."""
    if override_cm is not None:
        return override_cm
    if not ON_PI:
        return simulated_cm

    GPIO.output(TRIG, GPIO.HIGH)
    time.sleep(0.00001)  # 10 microsecond trigger pulse
    GPIO.output(TRIG, GPIO.LOW)

    t0 = time.monotonic()
    while GPIO.input(ECHO) == GPIO.LOW:
        if time.monotonic() - t0 > timeout:
            return None  # no echo: nothing in range
    t1 = time.monotonic()
    while GPIO.input(ECHO) == GPIO.HIGH:
        if time.monotonic() - t1 > timeout:
            return None
    return (time.monotonic() - t1) * 1_000_000 / 58


def motor(side, on):
    """Turn one strap motor on or off. side is 'left' or 'right'."""
    GPIO.output(MOTOR[side], GPIO.HIGH if on else GPIO.LOW)
    if not ON_PI:
        print(f"MOTOR {side} {'ON' if on else 'off'}", flush=True)


def buzz(side, times=1):
    """One tick is 100 ms on, 100 ms off."""
    for _ in range(times):
        motor(side, True)
        time.sleep(0.1)
        motor(side, False)
        time.sleep(0.1)


def button_pressed():
    """True while the button is held. Wiring pulls the pin to ground."""
    if not ON_PI:
        return simulated_button
    return GPIO.input(BUTTON) == GPIO.LOW


def motors_off():
    for side in MOTOR:
        try:
            motor(side, False)
        except Exception:
            pass


if __name__ == "__main__":
    where = "QNX rpi_gpio" if ON_PI else "laptop stand-in (no rpi_gpio)"
    print(f"hw.py using {where}")
    print(f"TRIG GPIO{TRIG}  ECHO GPIO{ECHO}  button GPIO{BUTTON}")
    print(f"left motor GPIO{MOTOR['left']}  right motor GPIO{MOTOR['right']}")
