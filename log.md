# Hold My Stick — status

Hack Western 13, Nov 21 2026. Vision work for the QNX smart cane. This is what is done, what is running, and what is still open.

The cane is a Raspberry Pi 5 on QNX 8.0 (`qnxpi`). The Logitech C270 is the webcam. Vision finds objects and sends them as JSON. The brain decides left and right. Vision does not choose a direction.

## Done

- Laptop pieces are in the repo and tested: `cane/hw/hw.py`, `cane/brain/brain.py`, `cane/brain/describe.py`, `cane/vision/fake_vision.py`. 14 unit tests, including a fake hand-wave on UDP.
- QNX SDP 8.0 is installed on the Mac under `~/qnx800`, cross-compiling from an Ubuntu container because the Mac is Apple Silicon. A hello-world binary was compiled and ran on the Pi.
- QNX TensorFlow Lite (`libtensorflow-lite.so` from qnx-ports) is built for `aarch64le`, with the C API. Numpy and `flatc` were built because the port needs them. OpenCV was not built and is not required.
- The camera works. The C270 is camera unit 5. Frames are YCbYCr, 640x480. JPEG and RGB888 are rejected by this sensor.
- `cane/vision/detect.cpp` is the real vision app. It opens unit 5, runs SSD MobileNet v1 COCO (quantized, 300x300 uint8, 4 threads), and sends one UDP packet per frame to `127.0.0.1:5005`, including empty frames. It also writes `/tmp/latest.jpg` about once a second.
- On the Pi it holds about 15 fps. A person in frame now comes through as `person`. One checked frame was `PERSON 0.61` with a box about half the frame tall.

Packet shape, same as `fake_vision.py`:

```json
{"t": 1795259969604, "objs": [{"cls": "person", "score": 0.61, "x": 0.48, "h": 0.72}]}
```

`t` is milliseconds since 1970. `x` is the box center. `h` is the box height. Both are 0 to 1. The brain ignores scores under 0.5. Vision still sends weaker scores.

## Running on the Pi right now

These paths are in `/tmp`, so a reboot wipes them.

- Binary: `/tmp/cane-dist/detect.fix`
- Libraries: `/tmp/cane-dist/lib` (56 shared libraries, including `libtensorflow-lite.so` and `libXNNPACK.so`)
- Model: `/tmp/cane-dist/detect.tflite`
- Labels: `/tmp/cane-dist/labelmap.txt`
- Log: `/tmp/cane-detect.log`
- Brain copy, not left running: `/tmp/cane-brain/`

Start the detector again with:

```sh
slay -f detect.fix
on -d sh -c 'LD_LIBRARY_PATH=/tmp/cane-dist/lib /tmp/cane-dist/detect.fix /tmp/cane-dist/detect.tflite /tmp/cane-dist/labelmap.txt > /tmp/cane-detect.log 2>&1'
```

If `camera_open unit 5` fails with error 2, the sensor service lost the webcam. Restart it, then start the detector:

```sh
sudo slay -f sensor
sudo sh -c 'sensor -U 521:521 -b external -r /data/share/sensor -c /etc/config/sensor/sensor_rpi5.conf >/tmp/sensor.log 2>&1 &'
```

`/dev/sensor/camera5` should show up. The C270 has to be plugged into the blue USB 3 port.

The Mac only reaches the Pi on the phone hotspot named `QNX`, with Maximize Compatibility on (2.4 GHz). Campus Wi-Fi cannot see the Pi. When both are on that hotspot the Pi is `qnxuser@172.20.10.3`.

## Bugs that looked like a bad model

The model did not need to be replaced.

1. Class index. This TFLite file numbers person as class `0`. `labelmap.txt` has a blank `???` line at index 0 and `person` at index 1. The app was skipping class 0, so the real detection (score about 0.7, box covering the frame) was dropped and the junk leftovers were labeled cake, chair, and tennis racket. The fix adds 1 before looking up the label. Raw log line that proved it: `[0 0.69 h0.96]`.
2. Exposure. The C270 exposes for the white wall, so a person was a near-black shape and the model missed them. A gamma of 0.45 is applied to the 300x300 RGB image before inference. A shirt that was about brightness 20 becomes visible, and the wall stays bright. Do not lower the brain's 0.5 cutoff to paper over this.
3. Camera unit 5 disappears if the sensor process dies. Restart command is above. The custom sensor file that pinned the C270 does not survive reboot. The stock `sensor_rpi5.conf` is enough after a sensor restart.
4. Copying a new `detect` binary over the running one fails because QNX will not overwrite an executing file. Copy to a new name, slay the old process, then start the new file.

## Left

- Run the brain on the Pi for real: `on -p 20 python3 /tmp/cane-brain/brain/brain.py`. It was smoke-tested for 8 seconds with a fake distance of 80 cm. It received vision packets in about 45 ms and set both straps to level 2 from the sensor. It is not running now.
- Wire the hardware. BCM pins in `cane/hw/hw.py`: ultrasonic trigger 23, echo 24, button 22, left motor 17, right motor 27. Until `rpi_gpio` exists on the Pi, the brain uses stand-in GPIO and will not buzz real motors.
- Set `GEMINI_API_KEY` on the Pi if the describe-the-scene button is wanted. The straps do not need it. The phone page is served by `describe.py` from `/tmp/latest.jpg`.
- Make the detector and the sensor start on boot. Right now both are manual and live under `/tmp`.
- Put the Mac and the Pi back on the `QNX` hotspot before any copy or SSH. Western Wi-Fi is fine for compiling on the Mac only.
- `cane/vision/detect.cpp` and `cane/vision/build.sh` are the source for the app. The cross-compile runs in Docker image `qnx-tflite-env` with `~/qnx800` and `~/.qnx` mounted. Do not re-run the TFLite build script that deletes the build directory.
