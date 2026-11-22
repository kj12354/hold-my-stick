# Hold My Stick — hardware

Hack Western 13, Nov 21 2026. The hardware for the smart cane: the parts, how they're wired to the Raspberry Pi, and how to test them.

## How it works

- The **webcam** sees what's in front of the cane. The vision app on the Pi detects objects and works out whether each one is on the left or the right, and how close it is.
- The **motion sensor** detects people moving nearby.
- The **servo** taps the user's wrist: a tap on the left side means "obstacle on the left", a tap on the right side means "obstacle on the right", and more taps mean it's closer.

## Parts

| Part | What it does |
|---|---|
| Raspberry Pi 5 running QNX 8.0 | The brain. Runs the vision app and the control code |
| Logitech C270 USB webcam | The eyes. Plugged into a blue USB 3 port on the Pi |
| HW-416 (HC-SR501) PIR motion sensor | Detects people moving in front of the cane |
| SG92R micro servo | Taps the left or right side of the wrist |
| Half-size breadboard (rows a–e, columns 1–30) | Connects the parts to the Pi without soldering |
| 7 female-to-male jumper wires | Pi pins and sensor pins to the breadboard |
| 3 male-to-male jumper wires | The servo plug to the breadboard |
| Phone hotspot named `QNX` | Lets a laptop reach the Pi over Wi-Fi |

## Wiring

Pin numbers are the Pi's **physical** pin numbers. Pin 1 is at the end of the header farthest from the USB ports, in the inside row; the pins count in zig-zag (1, 2, 3, 4...). The BCM number is what the code uses.

### Power

| Wire | From | To | Wire type |
|---|---|---|---|
| 5V | Pi pin 2 | breadboard red + strip | female-to-male |
| Ground | Pi pin 6 | breadboard blue − strip | female-to-male |

### Motion sensor (HW-416)

The sensor's three pins are VCC, OUT and GND (the labels are under the white dome; OUT is the middle pin).

| Wire | From | To | Wire type |
|---|---|---|---|
| Signal | Pi pin 16 (BCM 23) | a2 | female-to-male |
| Signal | sensor OUT | b2 | female-to-male |
| Power | sensor VCC | red + strip | female-to-male |
| Ground | sensor GND | blue − strip | female-to-male |

a2 and b2 are in the same column, so the sensor's OUT pin is connected to Pi pin 16.

### Servo (SG92R)

| Wire | From | To | Wire type |
|---|---|---|---|
| Signal | Pi pin 11 (BCM 17) | a20 | female-to-male |
| Signal | servo orange wire | b20 | male-to-male |
| Power | servo red wire | red + strip | male-to-male |
| Ground | servo brown wire | blue − strip | male-to-male |

### Webcam

Plugged straight into a **blue USB 3 port** on the Pi. No breadboard.

### Pin summary

| Pi pin | BCM | Used for |
|---|---|---|
| 2 | 5V | Power strip |
| 6 | GND | Ground strip |
| 11 | 17 | Servo signal |
| 16 | 23 | Motion sensor signal |

No resistors are needed. The motion sensor runs on 5V but its signal comes out at 3.3V, which is safe for the Pi's pins, and the servo's signal wire only carries the Pi's own 3.3V signal into the servo.

## Connecting to the Pi

1. Turn on a phone hotspot named `QNX` with password `everywhere` (on iPhone, turn on Maximize Compatibility). The Pi joins it automatically.
2. Join the laptop to the same hotspot.
3. `ssh qnxuser@qnxpi.local` (password `qnxuser`).

## Testing

The test scripts are in `cane/hw/`.

**Motion sensor:** wait about a minute after power-on for it to warm up, then run:

```sh
python3 cane/hw/test_pir.py
```

Wave a hand in front of the dome. It prints `MOVEMENT!` when it sees you. Press Ctrl+C to stop. The two orange knobs on the sensor set its sensitivity and how long it stays triggered; turn the time knob all the way down for quick responses.

**Servo:**

```sh
python3 cane/hw/test_servo.py
```

The arm swings left, middle, right, middle. The servo is driven with 50 Hz PWM through QNX's `rpi_gpio`: about 5% duty is 45° (left), 7.5% is 90° (middle), and 10% is 135° (right).

**Webcam:** see `log.md` for starting the camera service and the vision app.

## Wristband

- The servo sits on its side on top of the wrist, on a small 3D-printed base held on with a snug velcro strap.
- A longer 3D-printed arm (5–7 cm) with a soft tip rests pointing up, and swings down like a windshield wiper to tap either side of the wrist.
- The servo cable is extended with jumper wires and taped along the arm to the breadboard on the cane, with some slack so it doesn't pull out.

## Safety notes

- Shut the Pi down before changing any wiring: `su root -c shutdown`, wait about 10 seconds, then unplug.
- Never swap the servo's red and brown wires, or the sensor's VCC and GND.
- The Pi gets warm when the vision app runs. Give it airflow; a small fan or heatsink helps.
- If the Pi restarts when the servo moves, power the servo from its own 5V supply and keep the grounds connected together.
